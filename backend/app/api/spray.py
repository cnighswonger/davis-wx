"""CRUD + evaluation endpoints for spray advisor."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.database import get_db
from ..models.sensor_reading import SensorReadingModel
from ..models.station_config import StationConfigModel
from ..models.spray import SprayProduct, SpraySchedule
from ..services.spray_engine import (
    ProductConstraints,
    SprayEvaluation,
    evaluate_conditions,
    evaluate_current,
    fetch_hourly_forecast,
    find_optimal_window,
    seed_presets,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spray", tags=["spray"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class ProductCreate(BaseModel):
    name: str
    category: str = "custom"
    rain_free_hours: float = 2.0
    max_wind_mph: float = 10.0
    min_temp_f: float = 45.0
    max_temp_f: float = 85.0
    min_humidity_pct: Optional[float] = None
    max_humidity_pct: Optional[float] = None
    notes: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    rain_free_hours: Optional[float] = None
    max_wind_mph: Optional[float] = None
    min_temp_f: Optional[float] = None
    max_temp_f: Optional[float] = None
    min_humidity_pct: Optional[float] = None
    max_humidity_pct: Optional[float] = None
    notes: Optional[str] = None


class ScheduleCreate(BaseModel):
    product_id: int
    planned_date: str  # "2026-03-15"
    planned_start: str  # "08:00"
    planned_end: str  # "12:00"
    notes: Optional[str] = None


class ScheduleUpdate(BaseModel):
    planned_date: Optional[str] = None
    planned_start: Optional[str] = None
    planned_end: Optional[str] = None
    notes: Optional[str] = None


class StatusUpdate(BaseModel):
    status: str  # "completed" or "cancelled"


class QuickCheckRequest(BaseModel):
    product_id: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _product_to_dict(p: SprayProduct) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "category": p.category,
        "is_preset": bool(p.is_preset),
        "rain_free_hours": p.rain_free_hours,
        "max_wind_mph": p.max_wind_mph,
        "min_temp_f": p.min_temp_f,
        "max_temp_f": p.max_temp_f,
        "min_humidity_pct": p.min_humidity_pct,
        "max_humidity_pct": p.max_humidity_pct,
        "notes": p.notes,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _schedule_to_dict(s: SpraySchedule, product_name: str = "") -> dict:
    evaluation = None
    if s.evaluation:
        try:
            evaluation = json.loads(s.evaluation)
        except (json.JSONDecodeError, TypeError):
            pass
    ai_commentary = None
    if s.ai_commentary:
        try:
            ai_commentary = json.loads(s.ai_commentary)
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "id": s.id,
        "product_id": s.product_id,
        "product_name": product_name,
        "planned_date": s.planned_date,
        "planned_start": s.planned_start,
        "planned_end": s.planned_end,
        "status": s.status,
        "evaluation": evaluation,
        "ai_commentary": ai_commentary,
        "notes": s.notes,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _product_constraints(p: SprayProduct) -> ProductConstraints:
    return ProductConstraints(
        rain_free_hours=p.rain_free_hours,
        max_wind_mph=p.max_wind_mph,
        min_temp_f=p.min_temp_f,
        max_temp_f=p.max_temp_f,
        min_humidity_pct=p.min_humidity_pct,
        max_humidity_pct=p.max_humidity_pct,
    )


def _evaluation_to_dict(ev) -> dict:
    return {
        "go": ev.go,
        "constraints": [
            {
                "name": c.name,
                "passed": c.passed,
                "current_value": c.current_value,
                "threshold": c.threshold,
                "detail": c.detail,
            }
            for c in ev.constraints
        ],
        "overall_detail": ev.overall_detail,
        "optimal_window": ev.optimal_window,
        "confidence": ev.confidence,
    }


def _get_location(db: Session) -> tuple[float, float, str]:
    """Read lat/lon/timezone from station config."""
    rows = (
        db.query(StationConfigModel)
        .filter(StationConfigModel.key.in_(["latitude", "longitude", "station_timezone"]))
        .all()
    )
    cfg = {r.key: r.value for r in rows}
    try:
        lat = float(cfg.get("latitude", "0"))
    except ValueError:
        lat = 0.0
    try:
        lon = float(cfg.get("longitude", "0"))
    except ValueError:
        lon = 0.0
    tz = cfg.get("station_timezone", "")
    return lat, lon, tz


def _parse_schedule_datetime(
    planned_date: str, planned_time: str, station_tz: str,
) -> datetime:
    """Parse date + time strings into a UTC datetime."""
    from zoneinfo import ZoneInfo

    naive = datetime.fromisoformat(f"{planned_date}T{planned_time}:00")
    if station_tz:
        try:
            tz = ZoneInfo(station_tz)
            local = naive.replace(tzinfo=tz)
            return local.astimezone(timezone.utc)
        except (KeyError, Exception):
            pass
    return naive.replace(tzinfo=timezone.utc)


def _get_latest_obs(db: Session) -> dict:
    """Get latest sensor reading as a flat dict for current conditions."""
    r = (
        db.query(SensorReadingModel)
        .order_by(SensorReadingModel.timestamp.desc())
        .first()
    )
    if r is None:
        return {}

    # Today's max wind from station readings (actual gust proxy).
    now = datetime.now().astimezone()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    wind_hi = db.query(func.max(SensorReadingModel.wind_speed)).filter(
        SensorReadingModel.timestamp >= midnight,
    ).scalar()

    return {
        "outside_temp_f": r.outside_temp / 10.0 if r.outside_temp is not None else None,
        "outside_humidity_pct": r.outside_humidity,
        "wind_speed_mph": r.wind_speed,
        "wind_gust_mph": wind_hi,
        "rain_rate_in_hr": r.rain_rate / 100.0 if r.rain_rate is not None else None,
        "rain_daily_in": r.rain_total / 100.0 if r.rain_total is not None else None,
    }


# ---------------------------------------------------------------------------
# Products CRUD
# ---------------------------------------------------------------------------

@router.get("/products")
def list_products(db: Session = Depends(get_db)):
    """List all spray products. Seeds presets on first call if table is empty."""
    count = db.query(SprayProduct).count()
    if count == 0:
        seed_presets(db)
    products = (
        db.query(SprayProduct)
        .order_by(SprayProduct.is_preset.desc(), SprayProduct.name)
        .all()
    )
    return [_product_to_dict(p) for p in products]


@router.post("/products")
def create_product(body: ProductCreate, db: Session = Depends(get_db)):
    """Create a custom spray product."""
    product = SprayProduct(
        name=body.name,
        category=body.category,
        is_preset=0,
        rain_free_hours=body.rain_free_hours,
        max_wind_mph=body.max_wind_mph,
        min_temp_f=body.min_temp_f,
        max_temp_f=body.max_temp_f,
        min_humidity_pct=body.min_humidity_pct,
        max_humidity_pct=body.max_humidity_pct,
        notes=body.notes,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return _product_to_dict(product)


@router.put("/products/{product_id}")
def update_product(
    product_id: int, body: ProductUpdate, db: Session = Depends(get_db),
):
    """Update a spray product."""
    product = db.query(SprayProduct).filter_by(id=product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    for field_name, val in body.model_dump(exclude_unset=True).items():
        setattr(product, field_name, val)
    db.commit()
    db.refresh(product)
    return _product_to_dict(product)


@router.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    """Delete a spray product."""
    product = db.query(SprayProduct).filter_by(id=product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    # Also delete related schedules.
    db.query(SpraySchedule).filter_by(product_id=product_id).delete()
    db.delete(product)
    db.commit()
    return {"ok": True}


@router.post("/products/reset-presets")
def reset_presets(db: Session = Depends(get_db)):
    """Delete existing presets and re-seed defaults."""
    db.query(SprayProduct).filter(SprayProduct.is_preset == 1).delete()
    db.commit()
    seed_presets(db)
    products = (
        db.query(SprayProduct)
        .order_by(SprayProduct.is_preset.desc(), SprayProduct.name)
        .all()
    )
    return [_product_to_dict(p) for p in products]


# ---------------------------------------------------------------------------
# Schedules CRUD
# ---------------------------------------------------------------------------

@router.get("/schedules")
def list_schedules(db: Session = Depends(get_db)):
    """List spray schedules with product names, newest first."""
    rows = (
        db.query(SpraySchedule, SprayProduct.name)
        .join(SprayProduct, SpraySchedule.product_id == SprayProduct.id)
        .order_by(SpraySchedule.planned_date.desc(), SpraySchedule.planned_start.desc())
        .limit(50)
        .all()
    )
    return [_schedule_to_dict(s, name) for s, name in rows]


@router.post("/schedules")
async def create_schedule(body: ScheduleCreate, db: Session = Depends(get_db)):
    """Create a spray schedule and auto-evaluate against forecast."""
    product = db.query(SprayProduct).filter_by(id=body.product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    schedule = SpraySchedule(
        product_id=body.product_id,
        planned_date=body.planned_date,
        planned_start=body.planned_start,
        planned_end=body.planned_end,
        notes=body.notes,
    )
    db.add(schedule)
    db.flush()

    # Auto-evaluate.
    lat, lon, tz = _get_location(db)
    if lat != 0.0 or lon != 0.0:
        try:
            hourly = await fetch_hourly_forecast(lat, lon)
            start_dt = _parse_schedule_datetime(body.planned_date, body.planned_start, tz)
            end_dt = _parse_schedule_datetime(body.planned_date, body.planned_end, tz)
            ev = evaluate_conditions(
                _product_constraints(product), hourly, start_dt, end_dt,
            )
            schedule.evaluation = json.dumps(_evaluation_to_dict(ev))
            schedule.status = "go" if ev.go else "no_go"
        except Exception as exc:
            logger.warning("Auto-evaluation failed: %s", exc)

    db.commit()
    db.refresh(schedule)
    return _schedule_to_dict(schedule, product.name)


@router.put("/schedules/{schedule_id}")
def update_schedule(
    schedule_id: int, body: ScheduleUpdate, db: Session = Depends(get_db),
):
    """Update a spray schedule."""
    schedule = db.query(SpraySchedule).filter_by(id=schedule_id).first()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    for field_name, val in body.model_dump(exclude_unset=True).items():
        setattr(schedule, field_name, val)
    db.commit()
    db.refresh(schedule)
    product = db.query(SprayProduct).filter_by(id=schedule.product_id).first()
    return _schedule_to_dict(schedule, product.name if product else "")


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """Delete a spray schedule."""
    schedule = db.query(SpraySchedule).filter_by(id=schedule_id).first()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    db.delete(schedule)
    db.commit()
    return {"ok": True}


@router.put("/schedules/{schedule_id}/status")
def update_schedule_status(
    schedule_id: int, body: StatusUpdate, db: Session = Depends(get_db),
):
    """Mark a schedule as completed or cancelled."""
    if body.status not in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail="Status must be 'completed' or 'cancelled'")
    schedule = db.query(SpraySchedule).filter_by(id=schedule_id).first()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    schedule.status = body.status
    db.commit()
    product = db.query(SprayProduct).filter_by(id=schedule.product_id).first()
    return _schedule_to_dict(schedule, product.name if product else "")


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@router.post("/evaluate")
async def quick_check(body: QuickCheckRequest, db: Session = Depends(get_db)):
    """Evaluate a product against current conditions + forecast (Quick Check)."""
    product = db.query(SprayProduct).filter_by(id=body.product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    lat, lon, tz = _get_location(db)
    constraints = _product_constraints(product)

    # Current conditions check (station actuals for wind/temp/humidity).
    obs = _get_latest_obs(db)
    current_eval = evaluate_current(constraints, obs)

    # Forecast for rain-free window and optimal window.
    optimal_window = None
    rain_check = None
    if lat != 0.0 or lon != 0.0:
        hourly = await fetch_hourly_forecast(lat, lon)
        if hourly:
            optimal_window = find_optimal_window(
                constraints, hourly, search_hours=24, station_tz=tz,
            )
            # Use forecast only for rain-free check (needs future data).
            now = datetime.now(timezone.utc)
            forecast_eval = evaluate_conditions(
                constraints, hourly, now, now + timedelta(hours=2),
            )
            # Extract just the rain_free constraint from forecast.
            for c in forecast_eval.constraints:
                if c.name == "rain_free":
                    rain_check = c
                    break

    # Build merged result: station actuals for wind/temp/humidity,
    # forecast for rain-free (which needs future data).
    if rain_check is not None:
        # Replace the current eval's rain check with the forecast-based one.
        merged_checks = [
            rain_check if c.name == "rain_free" else c
            for c in current_eval.constraints
        ]
    else:
        merged_checks = list(current_eval.constraints)

    all_passed = all(c.passed for c in merged_checks)
    failed = [c for c in merged_checks if not c.passed]
    if all_passed:
        overall = "All constraints met — conditions are favorable for spraying."
    else:
        names = ", ".join(c.name for c in failed)
        overall = f"Multiple constraints not met: {names}." if len(failed) > 1 else f"Constraint not met: {names}."

    result = SprayEvaluation(
        go=all_passed,
        constraints=merged_checks,
        overall_detail=overall,
        confidence="HIGH" if all_passed else ("MEDIUM" if len(failed) == 1 else "LOW"),
    )
    result_dict = _evaluation_to_dict(result)
    result_dict["optimal_window"] = optimal_window
    return result_dict


@router.post("/schedules/{schedule_id}/evaluate")
async def evaluate_schedule(schedule_id: int, db: Session = Depends(get_db)):
    """Re-evaluate a specific schedule against current forecast."""
    schedule = db.query(SpraySchedule).filter_by(id=schedule_id).first()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    product = db.query(SprayProduct).filter_by(id=schedule.product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    lat, lon, tz = _get_location(db)
    if lat == 0.0 and lon == 0.0:
        raise HTTPException(status_code=400, detail="Station location not configured")

    hourly = await fetch_hourly_forecast(lat, lon)
    start_dt = _parse_schedule_datetime(schedule.planned_date, schedule.planned_start, tz)
    end_dt = _parse_schedule_datetime(schedule.planned_date, schedule.planned_end, tz)
    ev = evaluate_conditions(_product_constraints(product), hourly, start_dt, end_dt)

    # Find optimal window too.
    window = find_optimal_window(
        _product_constraints(product), hourly, search_hours=24, station_tz=tz,
    )

    schedule.evaluation = json.dumps(_evaluation_to_dict(ev))
    schedule.status = "go" if ev.go else "no_go"
    db.commit()

    result = _evaluation_to_dict(ev)
    result["optimal_window"] = window
    return result


# ---------------------------------------------------------------------------
# Current conditions summary
# ---------------------------------------------------------------------------

@router.get("/conditions")
async def get_spray_conditions(db: Session = Depends(get_db)):
    """Return spray-relevant current conditions summary."""
    obs = _get_latest_obs(db)
    lat, lon, tz = _get_location(db)

    # Pull forecast data for next-rain and current-hour gust.
    next_rain_hours = None
    forecast_gust_mph = None
    if lat != 0.0 or lon != 0.0:
        hourly = await fetch_hourly_forecast(lat, lon)
        precips = hourly.get("precipitation", [])
        for i, p in enumerate(precips):
            if p is not None and p > 0:
                next_rain_hours = i
                break
        # Current-hour forecast gust (index 0 = this hour).
        gusts = hourly.get("wind_gusts_10m", [])
        if gusts:
            forecast_gust_mph = gusts[0]

    wind = obs.get("wind_speed_mph")
    station_gust = obs.get("wind_gust_mph")  # today's max wind from station
    temp = obs.get("outside_temp_f")
    humidity = obs.get("outside_humidity_pct")
    rain_rate = obs.get("rain_rate_in_hr")
    rain_daily = obs.get("rain_daily_in")

    # Best gust value: prefer station actual, fall back to forecast.
    gust = station_gust if station_gust is not None else forecast_gust_mph

    # Use the worse of current wind and gust for the overall check.
    wind_candidates = [w for w in [wind, gust] if w is not None]
    worst_wind = max(wind_candidates) if wind_candidates else None

    # Overall check: no active rain, no recent rain, rain not imminent,
    # wind/gust < 10, temp 40-90.
    overall_ok = True
    if rain_rate is not None and rain_rate > 0:
        overall_ok = False
    if rain_daily is not None and rain_daily > 0:
        overall_ok = False
    if next_rain_hours is not None and next_rain_hours < 2:
        overall_ok = False
    if worst_wind is not None and worst_wind > 10:
        overall_ok = False
    if temp is not None and (temp < 40 or temp > 90):
        overall_ok = False

    return {
        "wind_speed_mph": wind,
        "wind_gust_mph": gust,
        "temperature_f": temp,
        "humidity_pct": humidity,
        "rain_rate": rain_rate,
        "rain_daily": rain_daily,
        "next_rain_hours": next_rain_hours,
        "overall_spray_ok": overall_ok,
    }
