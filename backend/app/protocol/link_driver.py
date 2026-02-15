"""High-level driver for Davis WeatherLink communication.

Orchestrates serial communication: station detection, LOOP polling,
memory reads, archive sync, and calibration.
"""

import logging
import struct
from dataclasses import dataclass
from typing import Optional

from .serial_port import SerialPort
from .commands import (
    build_loop_command,
    build_wrd_command,
    build_rrd_command,
    build_srd_command,
    build_stop_command,
    build_start_command,
    build_crc0_command,
)
from .crc import crc_validate, crc_calculate
from .constants import (
    StationModel,
    LOOP_DATA_SIZE,
    SOH,
    ACK,
    CAN,
    MAX_RETRIES,
)
from .loop_packet import parse_loop_packet
from .station_types import SensorReading
from .memory_map import BasicBank0, BasicBank1, MemAddr

logger = logging.getLogger(__name__)


@dataclass
class CalibrationOffsets:
    """Calibration offsets read from station memory."""
    inside_temp: int = 0    # tenths F to add
    outside_temp: int = 0   # tenths F to add
    barometer: int = 0      # thousandths inHg to subtract
    outside_hum: int = 0    # percent to add
    rain_cal: int = 100     # clicks per inch


class LinkDriver:
    """High-level WeatherLink serial communication driver."""

    def __init__(self, port: str, baud_rate: int = 19200, timeout: float = 2.0):
        self.serial = SerialPort(port, baud_rate, timeout)
        self.station_model: Optional[StationModel] = None
        self.calibration = CalibrationOffsets()
        self.is_rev_e = False
        self._connected = False
        self._stop_requested = False

    @property
    def connected(self) -> bool:
        return self._connected and self.serial.is_open

    def request_stop(self) -> None:
        """Signal the blocking poll_loop thread to exit early."""
        self._stop_requested = True

    def open(self) -> None:
        """Open serial port and initialize connection."""
        self.serial.open()
        self._connected = True

    def close(self) -> None:
        """Close serial port."""
        self.serial.close()
        self._connected = False

    def detect_station_type(self) -> StationModel:
        """Read model nibble from station memory to determine station type.

        WRD command: 1 nibble from bank 0 at address 0x4D.
        """
        data = self.read_station_memory(
            BasicBank0.MODEL.bank,
            BasicBank0.MODEL.address,
            BasicBank0.MODEL.nibbles,
        )
        if data is None:
            raise ConnectionError("Failed to read station model")

        model_code = data[0] & 0x0F
        try:
            self.station_model = StationModel(model_code)
        except ValueError:
            logger.warning("Unknown model code: 0x%X, defaulting to Monitor", model_code)
            self.station_model = StationModel.MONITOR

        logger.info("Detected station type: %s (code=%d)", self.station_model.name, model_code)
        return self.station_model

    def read_calibration(self) -> CalibrationOffsets:
        """Read calibration offsets from station memory.

        Applies to Monitor/Wizard/Perception stations.
        Reference: techref.txt lines 847-1108.
        """
        # Inside temp calibration: bank 1, address 0x52, 4 nibbles
        data = self.read_station_memory(
            BasicBank1.INSIDE_TEMP_CAL.bank,
            BasicBank1.INSIDE_TEMP_CAL.address,
            BasicBank1.INSIDE_TEMP_CAL.nibbles,
        )
        if data and len(data) >= 2:
            self.calibration.inside_temp = struct.unpack("<h", data[:2])[0]

        # Outside temp calibration
        data = self.read_station_memory(
            BasicBank1.OUTSIDE_TEMP_CAL.bank,
            BasicBank1.OUTSIDE_TEMP_CAL.address,
            BasicBank1.OUTSIDE_TEMP_CAL.nibbles,
        )
        if data and len(data) >= 2:
            self.calibration.outside_temp = struct.unpack("<h", data[:2])[0]

        # Barometer calibration
        data = self.read_station_memory(
            BasicBank1.BAR_CAL.bank,
            BasicBank1.BAR_CAL.address,
            BasicBank1.BAR_CAL.nibbles,
        )
        if data and len(data) >= 2:
            self.calibration.barometer = struct.unpack("<H", data[:2])[0]

        # Outside humidity calibration
        data = self.read_station_memory(
            BasicBank1.OUTSIDE_HUMIDITY_CAL.bank,
            BasicBank1.OUTSIDE_HUMIDITY_CAL.address,
            BasicBank1.OUTSIDE_HUMIDITY_CAL.nibbles,
        )
        if data and len(data) >= 2:
            self.calibration.outside_hum = struct.unpack("<h", data[:2])[0]

        # Rain calibration (clicks per inch)
        data = self.read_station_memory(
            BasicBank1.RAIN_CAL.bank,
            BasicBank1.RAIN_CAL.address,
            BasicBank1.RAIN_CAL.nibbles,
        )
        if data and len(data) >= 2:
            cal = struct.unpack("<H", data[:2])[0]
            if cal > 0:
                self.calibration.rain_cal = cal

        logger.info("Calibration offsets: %s", self.calibration)
        return self.calibration

    def apply_calibration(self, reading: SensorReading) -> SensorReading:
        """Apply calibration offsets to a sensor reading.

        Per techref.txt:
        - calibrated_temp = raw_temp + temp_cal
        - calibrated_bar = raw_bar - bar_cal
        - calibrated_hum = clamp(raw_hum + hum_cal, 1, 100)
        """
        if reading.inside_temp is not None:
            reading.inside_temp += self.calibration.inside_temp
        if reading.outside_temp is not None:
            reading.outside_temp += self.calibration.outside_temp
        if reading.barometer is not None:
            reading.barometer -= self.calibration.barometer
        if reading.outside_humidity is not None:
            reading.outside_humidity = max(1, min(100,
                reading.outside_humidity + self.calibration.outside_hum))
        return reading

    def poll_loop(self) -> Optional[SensorReading]:
        """Send LOOP command and parse the response.

        Returns a calibrated SensorReading, or None on failure.
        """
        if self.station_model is None:
            raise RuntimeError("Station type not detected. Call detect_station_type() first.")

        for attempt in range(MAX_RETRIES + 1):
            if self._stop_requested:
                logger.info("LOOP poll aborted (stop requested)")
                return None
            try:
                reading = self._send_loop_once()
                if reading is not None:
                    return self.apply_calibration(reading)
                else:
                    logger.warning("LOOP attempt %d/%d: no response", attempt + 1, MAX_RETRIES + 1)
            except Exception as e:
                logger.warning("LOOP attempt %d/%d failed: %s", attempt + 1, MAX_RETRIES + 1, e)

            if attempt < MAX_RETRIES:
                self.serial.flush()

        logger.error("LOOP command failed after %d attempts", MAX_RETRIES + 1)
        return None

    def _send_loop_once(self) -> Optional[SensorReading]:
        """Single attempt to send LOOP and parse response."""
        self.serial.flush()
        cmd = build_loop_command(1)
        self.serial.send(cmd)

        if not self.serial.wait_for_ack():
            return None

        # Read SOH + data + CRC
        data_size = LOOP_DATA_SIZE[self.station_model]
        total_size = 1 + data_size + 2  # SOH + data + 2-byte CRC
        raw = self.serial.receive(total_size)

        if len(raw) < total_size:
            logger.warning("Incomplete LOOP response: %d/%d bytes", len(raw), total_size)
            return None

        return parse_loop_packet(raw, self.station_model)

    def read_station_memory(
        self, bank: int, address: int, n_nibbles: int
    ) -> Optional[bytes]:
        """Read station processor memory using WRD command.

        Returns raw nibble data as bytes, or None on failure.
        """
        for attempt in range(MAX_RETRIES + 1):
            try:
                cmd = build_wrd_command(n_nibbles, bank, address)
                logger.debug(
                    "WRD %d nibbles bank %d addr 0x%02X -> TX: %s",
                    n_nibbles, bank, address, cmd.hex(),
                )
                self.serial.send(cmd)

                if not self.serial.wait_for_ack():
                    logger.warning(
                        "WRD bank %d addr 0x%02X attempt %d: no ACK",
                        bank, address, attempt + 1,
                    )
                    continue

                # Number of bytes = ceil(n_nibbles / 2)
                n_bytes = (n_nibbles + 1) // 2
                # Always read data + 2 CRC bytes — the WeatherLink
                # sends trailing CRC regardless of revision, and leaving
                # them in the buffer corrupts subsequent reads.
                read_size = n_bytes + 2
                data = self.serial.receive(read_size)
                logger.debug("WRD RX: %s (%d bytes)", data.hex(), len(data))

                if len(data) < n_bytes:
                    logger.warning(
                        "WRD bank %d addr 0x%02X attempt %d: short read %d/%d",
                        bank, address, attempt + 1, len(data), n_bytes,
                    )
                    continue

                # Validate CRC if we got the full response
                if len(data) >= n_bytes + 2:
                    if crc_validate(data[:n_bytes + 2]):
                        logger.debug("WRD CRC OK")
                    else:
                        logger.debug("WRD CRC mismatch (non-Rev-E units may not send valid CRC)")

                return data[:n_bytes]

            except Exception as e:
                logger.warning("WRD attempt %d failed: %s", attempt + 1, e)

        return None

    def read_link_memory(
        self, bank: int, address: int, n_nibbles: int
    ) -> Optional[bytes]:
        """Read link processor memory using RRD command."""
        for attempt in range(MAX_RETRIES + 1):
            try:
                cmd = build_rrd_command(bank, address, n_nibbles)
                self.serial.send(cmd)

                if not self.serial.wait_for_ack():
                    continue

                n_bytes = (n_nibbles + 1) // 2
                read_size = n_bytes + 2  # always drain trailing CRC
                data = self.serial.receive(read_size)

                if len(data) < n_bytes:
                    continue

                return data[:n_bytes]

            except Exception as e:
                logger.warning("RRD attempt %d failed: %s", attempt + 1, e)

        return None

    def read_archive(self, address: int, n_bytes: int) -> Optional[bytes]:
        """Read archive/SRAM memory using SRD command."""
        cmd = build_srd_command(address, n_bytes)
        self.serial.send(cmd)

        if not self.serial.wait_for_ack():
            return None

        # SRD always returns data + 2-byte CRC
        data = self.serial.receive(n_bytes + 2)
        if len(data) < n_bytes + 2:
            return None

        if not crc_validate(data):
            logger.warning("SRD CRC validation failed")
            return None

        return data[:n_bytes]

    def stop_polling(self) -> bool:
        """Send STOP command to pause WeatherLink from polling station."""
        self.serial.send(build_stop_command())
        return self.serial.wait_for_ack()

    def start_polling(self) -> bool:
        """Send START command to resume WeatherLink polling."""
        self.serial.send(build_start_command())
        return self.serial.wait_for_ack()

    async def async_poll_loop(self) -> Optional[SensorReading]:
        """Async version of poll_loop."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.poll_loop)

    async def async_detect_station_type(self) -> StationModel:
        """Async version of detect_station_type."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.detect_station_type)

    async def async_read_calibration(self) -> CalibrationOffsets:
        """Async version of read_calibration."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.read_calibration)
