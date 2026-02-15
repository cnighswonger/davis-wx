"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    # Serial port
    serial_port: str = "/dev/ttyUSB0"
    baud_rate: int = 19200
    serial_timeout: float = 2.0

    # Polling
    poll_interval_sec: int = 10

    # Location (required for astronomy/forecast)
    latitude: float = 0.0
    longitude: float = 0.0
    elevation_ft: float = 0.0

    # Database
    database_url: str = "sqlite:///davis_wx.db"

    # Units
    units_temp: str = "F"  # F or C
    units_pressure: str = "inHg"  # inHg, hPa, or mb
    units_wind: str = "mph"  # mph, kph, or knots
    units_rain: str = "in"  # in or mm

    # METAR
    metar_enabled: bool = False
    metar_station_id: str = "XXXX"

    # NWS
    nws_enabled: bool = False

    # UI
    theme: str = "dark"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_prefix": "DAVIS_", "env_file": ".env"}


settings = Settings()
