#!/usr/bin/env python3
"""Davis Weather Station data logger daemon.

Owns the serial connection, polls the station, writes to the database,
and exposes an IPC server so the web application can query status and
send hardware commands without touching the serial port.

Start:  python logger_main.py
Stop:   Ctrl-C or SIGTERM
"""

import asyncio
import json
import logging
import os
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure the backend package is importable when running from the backend/ dir
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings
from app.models.database import init_database, SessionLocal, engine
from app.models.station_config import StationConfigModel
from app.protocol.link_driver import LinkDriver, CalibrationOffsets
from app.protocol.serial_port import list_serial_ports
from app.protocol.constants import STATION_NAMES
from app.services.poller import Poller
from app.services.archive_sync import async_sync_archive
from app.ipc.server import IPCServer
from app.ipc import protocol as ipc

logger = logging.getLogger("davis.logger")

# --------------- Logger Daemon ---------------


class LoggerDaemon:
    """Main logger daemon — serial owner, poller, IPC server."""

    def __init__(self) -> None:
        self.driver: Optional[LinkDriver] = None
        self.poller: Optional[Poller] = None
        self.poller_task: Optional[asyncio.Task] = None
        self.ipc_server: Optional[IPCServer] = None
        self.state_file = Path(settings.db_path).parent / ".logger_state.json"

    # ---- public entry point ----

    async def run(self) -> None:
        """Initialise and run until SIGTERM / SIGINT."""
        init_database()

        self.ipc_server = IPCServer(settings.ipc_port)
        self._register_handlers()
        await self.ipc_server.start()

        if self._is_setup_complete():
            port, baud = self._get_serial_config()
            try:
                await self._connect(port, baud)
            except Exception as exc:
                logger.error("Auto-connect failed: %s", exc)
        else:
            logger.info("Setup not complete — waiting for connect command via IPC")

        # Wait for shutdown signal
        stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()
        if sys.platform != "win32":
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, stop_event.set)
        else:
            # Windows: signal handlers work differently
            signal.signal(signal.SIGINT, lambda *_: stop_event.set())
            signal.signal(signal.SIGTERM, lambda *_: stop_event.set())

        logger.info("Logger daemon ready (IPC port %d)", settings.ipc_port)
        await stop_event.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        logger.info("Shutting down logger daemon...")
        # Hard deadline: if cleanup hangs (executor threads, IPC), force exit
        threading.Timer(10.0, lambda: (
            logger.warning("Shutdown deadline exceeded — forcing exit"),
            os._exit(0),
        )).start()
        await self._teardown_driver()
        if self.ipc_server:
            await self.ipc_server.stop()
        logger.info("Logger daemon stopped")

    # ---- serial lifecycle ----

    async def _connect(self, port: str, baud: int) -> None:
        """Open serial, detect station, sync archive, start poller."""
        logger.info("Connecting to %s at %d baud...", port, baud)
        self.driver = LinkDriver(port=port, baud_rate=baud, timeout=settings.serial_timeout)
        self.driver.open()

        station = await self.driver.async_detect_station_type()
        logger.info("Station: %s", STATION_NAMES.get(station, "Unknown"))
        await self.driver.async_read_calibration()

        # Archive sync in background (shares _io_lock with poller)
        asyncio.create_task(self._bg_archive_sync())

        self.poller = Poller(self.driver, poll_interval=settings.poll_interval_sec)
        self.poller.set_broadcast_callback(self.ipc_server.broadcast_to_subscribers)

        # Restore rain state from a previous run
        self._restore_rain_state()

        self.poller_task = asyncio.create_task(self.poller.run())
        logger.info("Poller started (%ds interval)", settings.poll_interval_sec)

    async def _teardown_driver(self) -> None:
        if self.poller:
            self._save_rain_state()
            self.poller.stop()
        if self.poller_task:
            self.poller_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self.poller_task), timeout=6.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
        if self.driver:
            try:
                self.driver.close()
            except Exception:
                pass
        self.driver = None
        self.poller = None
        self.poller_task = None

    async def _bg_archive_sync(self) -> None:
        try:
            n = await async_sync_archive(self.driver)
            logger.info("Archive sync: %d new records", n)
        except Exception as exc:
            logger.warning("Archive sync failed: %s", exc)

    # ---- rain state persistence ----

    def _save_rain_state(self) -> None:
        if self.poller is None:
            return
        state = {
            "last_rain_total": self.poller._last_rain_total,
            "last_rain_tip_time": (
                self.poller._last_rain_tip_time.isoformat()
                if self.poller._last_rain_tip_time else None
            ),
            "rain_rate_in_per_hr": self.poller._rain_rate_in_per_hr,
        }
        try:
            self.state_file.write_text(json.dumps(state))
            logger.info("Rain state saved to %s", self.state_file)
        except Exception as exc:
            logger.warning("Failed to save rain state: %s", exc)

    def _restore_rain_state(self) -> None:
        if self.poller is None or not self.state_file.exists():
            return
        try:
            state = json.loads(self.state_file.read_text())
            self.poller._last_rain_total = state.get("last_rain_total")
            tip = state.get("last_rain_tip_time")
            if tip:
                self.poller._last_rain_tip_time = datetime.fromisoformat(tip)
            self.poller._rain_rate_in_per_hr = state.get("rain_rate_in_per_hr", 0.0)
            logger.info("Restored rain state from %s", self.state_file)
        except Exception as exc:
            logger.warning("Failed to restore rain state: %s", exc)

    # ---- config helpers ----

    @staticmethod
    def _is_setup_complete() -> bool:
        db = SessionLocal()
        try:
            row = db.query(StationConfigModel).filter_by(key="setup_complete").first()
            return row is not None and row.value == "true"
        finally:
            db.close()

    @staticmethod
    def _get_serial_config() -> tuple[str, int]:
        db = SessionLocal()
        try:
            from app.api.config import get_effective_config
            cfg = get_effective_config(db)
            return str(cfg.get("serial_port", settings.serial_port)), int(cfg.get("baud_rate", settings.baud_rate))
        finally:
            db.close()

    # ---- IPC handler registration ----

    def _register_handlers(self) -> None:
        h = self.ipc_server.register_handler
        h(ipc.CMD_STATUS, self._h_status)
        h(ipc.CMD_PROBE, self._h_probe)
        h(ipc.CMD_AUTO_DETECT, self._h_auto_detect)
        h(ipc.CMD_CONNECT, self._h_connect)
        h(ipc.CMD_RECONNECT, self._h_reconnect)
        h(ipc.CMD_READ_STATION_TIME, self._h_read_station_time)
        h(ipc.CMD_SYNC_STATION_TIME, self._h_sync_station_time)
        h(ipc.CMD_READ_CONFIG, self._h_read_config)
        h(ipc.CMD_WRITE_CONFIG, self._h_write_config)
        h(ipc.CMD_CLEAR_RAIN_DAILY, self._h_clear_rain_daily)
        h(ipc.CMD_CLEAR_RAIN_YEARLY, self._h_clear_rain_yearly)
        h(ipc.CMD_FORCE_ARCHIVE, self._h_force_archive)

    # ---- IPC handlers ----

    async def _h_status(self, _msg: dict) -> dict[str, Any]:
        connected = self.driver.connected if self.driver else False
        model = self.driver.station_model if self.driver else None
        stats = self.poller.stats if self.poller else {}
        return {
            "connected": connected,
            "type_code": model.value if model else -1,
            "type_name": STATION_NAMES.get(model, "Unknown") if model else "Not connected",
            "link_revision": ("E" if self.driver.is_rev_e else "D") if self.driver else "unknown",
            "poll_interval": self.poller.poll_interval if self.poller else 0,
            **stats,
        }

    async def _h_probe(self, msg: dict) -> dict[str, Any]:
        port, baud = msg["port"], msg["baud"]

        # If we're already connected to this port, return current info
        if (self.driver and self.driver.connected
                and self.driver.serial and self.driver.serial.port == port):
            return {
                "success": True,
                "station_type": STATION_NAMES.get(self.driver.station_model, "Unknown"),
                "station_code": self.driver.station_model.value if self.driver.station_model else None,
            }

        tmp = LinkDriver(port=port, baud_rate=baud, timeout=3.0)
        tmp.open()
        try:
            station = await tmp.async_detect_station_type()
            return {
                "success": True,
                "station_type": STATION_NAMES.get(station, "Unknown"),
                "station_code": station.value,
            }
        finally:
            tmp.close()

    async def _h_auto_detect(self, _msg: dict) -> dict[str, Any]:
        # Already connected? Return immediately
        if self.driver and self.driver.connected and self.driver.station_model:
            return {
                "found": True,
                "port": self.driver.serial.port,
                "baud_rate": self.driver.serial.baud_rate,
                "station_type": STATION_NAMES.get(self.driver.station_model, "Unknown"),
                "station_code": self.driver.station_model.value,
                "attempts": [],
            }

        ports = list_serial_ports()
        attempts: list[dict] = []
        for port in ports:
            for baud in (2400, 1200):
                try:
                    tmp = LinkDriver(port=port, baud_rate=baud, timeout=3.0)
                    tmp.open()
                    try:
                        station = await tmp.async_detect_station_type()
                        attempts.append({"port": port, "baud": baud, "result": "found"})
                        return {
                            "found": True,
                            "port": port,
                            "baud_rate": baud,
                            "station_type": STATION_NAMES.get(station, "Unknown"),
                            "station_code": station.value,
                            "attempts": attempts,
                        }
                    finally:
                        tmp.close()
                except Exception as exc:
                    attempts.append({"port": port, "baud": baud, "error": str(exc)})

        return {"found": False, "attempts": attempts}

    async def _h_connect(self, msg: dict) -> dict[str, Any]:
        await self._teardown_driver()
        await self._connect(msg["port"], msg["baud"])
        return {
            "success": True,
            "station_type": STATION_NAMES.get(self.driver.station_model, "Unknown"),
        }

    async def _h_reconnect(self, _msg: dict) -> dict[str, Any]:
        port, baud = self._get_serial_config()
        await self._teardown_driver()
        await self._connect(port, baud)
        return {
            "success": True,
            "station_type": STATION_NAMES.get(self.driver.station_model, "Unknown"),
        }

    async def _h_read_station_time(self, _msg: dict) -> Any:
        if not self.driver or not self.driver.connected:
            raise RuntimeError("Not connected")
        result = await self.driver.async_read_station_time()
        if result is None:
            logger.warning("read_station_time returned None")
        return result

    async def _h_sync_station_time(self, _msg: dict) -> dict[str, Any]:
        if not self.driver or not self.driver.connected:
            raise RuntimeError("Not connected")
        now = datetime.now()
        ok = await self.driver.async_write_station_time(now)
        return {"success": ok, "synced_to": now.strftime("%H:%M:%S %m/%d/%Y")}

    async def _h_read_config(self, _msg: dict) -> dict[str, Any]:
        if not self.driver or not self.driver.connected:
            raise RuntimeError("Not connected")
        archive_period = await self.driver.async_read_archive_period()
        sample_period = await self.driver.async_read_sample_period()
        cal = self.driver.calibration
        return {
            "archive_period": archive_period,
            "sample_period": sample_period,
            "calibration": {
                "inside_temp": cal.inside_temp,
                "outside_temp": cal.outside_temp,
                "barometer": cal.barometer,
                "outside_humidity": cal.outside_hum,
                "rain_cal": cal.rain_cal,
            },
        }

    async def _h_write_config(self, msg: dict) -> dict[str, Any]:
        if not self.driver or not self.driver.connected:
            raise RuntimeError("Not connected")
        results: dict[str, str] = {}

        if msg.get("archive_period") is not None:
            ok = await self.driver.async_set_archive_period(msg["archive_period"])
            results["archive_period"] = "ok" if ok else "failed"

        if msg.get("sample_period") is not None:
            ok = await self.driver.async_set_sample_period(msg["sample_period"])
            results["sample_period"] = "ok" if ok else "failed"

        if msg.get("calibration") is not None:
            cal = msg["calibration"]
            offsets = CalibrationOffsets(
                inside_temp=cal["inside_temp"],
                outside_temp=cal["outside_temp"],
                barometer=cal["barometer"],
                outside_hum=cal["outside_humidity"],
                rain_cal=cal["rain_cal"],
            )
            ok = await self.driver.async_write_calibration(offsets)
            results["calibration"] = "ok" if ok else "failed"

        return {"results": results}

    async def _h_clear_rain_daily(self, _msg: dict) -> dict[str, Any]:
        if not self.driver or not self.driver.connected:
            raise RuntimeError("Not connected")
        ok = await self.driver.async_clear_rain_daily()
        return {"success": ok}

    async def _h_clear_rain_yearly(self, _msg: dict) -> dict[str, Any]:
        if not self.driver or not self.driver.connected:
            raise RuntimeError("Not connected")
        ok = await self.driver.async_clear_rain_yearly()
        return {"success": ok}

    async def _h_force_archive(self, _msg: dict) -> dict[str, Any]:
        if not self.driver or not self.driver.connected:
            raise RuntimeError("Not connected")
        ok = await self.driver.async_force_archive()
        return {"success": ok}


# --------------- Entry point ---------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:     %(name)s - %(message)s",
    )
    daemon = LoggerDaemon()
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
