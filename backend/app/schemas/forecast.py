"""Pydantic schemas for forecast API."""

from pydantic import BaseModel


class LocalForecast(BaseModel):
    source: str = "zambretti"
    text: str
    confidence: float
    updated: str


class NWSPeriod(BaseModel):
    name: str
    temperature: int | None = None
    wind: str | None = None
    precipitation_pct: int | None = None
    text: str


class NWSForecast(BaseModel):
    source: str = "nws"
    periods: list[NWSPeriod]
    updated: str


class ForecastResponse(BaseModel):
    local: LocalForecast | None = None
    nws: NWSForecast | None = None
