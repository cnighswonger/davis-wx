"""Nowcast verification engine — compares predictions against actual observations.

After a nowcast's valid_until time passes, this module extracts numeric
predictions from Claude's forecast text, finds the nearest sensor reading,
scores accuracy, and stores results in the nowcast_verification table.
Significant misses auto-generate knowledge entries for the learning loop.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models.nowcast import NowcastHistory, NowcastVerification, NowcastKnowledge
from ..models.sensor_reading import SensorReadingModel

logger = logging.getLogger(__name__)

# How far back to look for unverified nowcasts (hours).
MAX_LOOKBACK_HOURS = 48

# Window around valid_until to search for a sensor reading (minutes).
SENSOR_WINDOW_MINUTES = 15

# Score threshold below which a knowledge entry is auto-created.
MISS_THRESHOLD = 0.3


# ---------------------------------------------------------------------------
# Regex extractors
# ---------------------------------------------------------------------------

def _extract_temperature(text: str) -> Optional[float]:
    """Extract a temperature value (degrees F) from forecast text.

    Handles: "High near 72F", "around 65-70°F", "72 degrees", "Low 40s",
    "temperatures in the upper 60s".
    """
    # Range pattern: "65-70F" or "65–70°F"
    m = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*[°]?\s*F', text, re.IGNORECASE)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2.0

    # Single value: "72F", "72°F", "72 degrees"
    m = re.search(r'(\d+)\s*[°]?\s*(?:F|degrees)', text, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # "Low 40s", "upper 60s", "mid 50s"
    m = re.search(r'(low|mid|upper|high)\s+(\d+)s', text, re.IGNORECASE)
    if m:
        base = float(m.group(2))
        qualifier = m.group(1).lower()
        if qualifier in ("low",):
            return base + 2
        elif qualifier in ("mid",):
            return base + 5
        else:  # upper, high
            return base + 8

    # Bare number near "temp" context (last resort)
    m = re.search(r'(\d{2,3})\s*[°]?\s*F', text)
    if m:
        return float(m.group(1))

    return None


def _extract_wind_speed(text: str) -> Optional[float]:
    """Extract wind speed (mph) from forecast text.

    Handles: "S 10-15 mph", "10 mph gusting to 20", "Winds 5-10 mph".
    """
    # Range: "10-15 mph" or "10–15 mph"
    m = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*mph', text, re.IGNORECASE)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2.0

    # Single value: "10 mph"
    m = re.search(r'(\d+)\s*mph', text, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # "calm" or "light and variable"
    if re.search(r'\bcalm\b|\blight and variable\b', text, re.IGNORECASE):
        return 0.0

    return None


def _predict_precipitation(text: str) -> bool:
    """Return True if the forecast text predicts precipitation."""
    precip_words = r'\b(rain|snow|precip|shower|drizzle|storm|sleet|freezing rain|thunderstorm|ice)\b'
    if not re.search(precip_words, text, re.IGNORECASE):
        return False

    # Negative phrasing: "no rain", "rain not expected", "dry"
    if re.search(r'\bno\s+(rain|precip|snow|shower)', text, re.IGNORECASE):
        return False
    if re.search(r'\bdry\b', text, re.IGNORECASE):
        return False

    return True


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def _score_temperature(predicted: float, actual: float) -> float:
    """Score temperature prediction. 1.0 = perfect, 0.0 = 10F+ off."""
    return max(0.0, 1.0 - abs(predicted - actual) / 10.0)


def _score_wind(predicted: float, actual: float) -> float:
    """Score wind speed prediction. 1.0 = perfect, 0.0 = 15mph+ off."""
    return max(0.0, 1.0 - abs(predicted - actual) / 15.0)


def _score_precipitation(predicted_rain: bool, actual_rain_rate: float) -> float:
    """Score precipitation prediction. Binary: 1.0 correct, 0.0 wrong."""
    actual_raining = actual_rain_rate > 0.0
    return 1.0 if predicted_rain == actual_raining else 0.0


# ---------------------------------------------------------------------------
# Sensor lookup
# ---------------------------------------------------------------------------

def _find_nearest_reading(
    db: Session, target_time: datetime, window_minutes: int = SENSOR_WINDOW_MINUTES,
) -> Optional[SensorReadingModel]:
    """Find the sensor reading closest to target_time within a window."""
    start = target_time - timedelta(minutes=window_minutes)
    end = target_time + timedelta(minutes=window_minutes)

    readings = (
        db.query(SensorReadingModel)
        .filter(
            SensorReadingModel.timestamp >= start,
            SensorReadingModel.timestamp <= end,
        )
        .order_by(SensorReadingModel.timestamp.asc())
        .all()
    )

    if not readings:
        return None

    # Pick the one closest to target_time.
    best = min(readings, key=lambda r: abs((r.timestamp - target_time).total_seconds()))
    return best


# ---------------------------------------------------------------------------
# Single nowcast verification
# ---------------------------------------------------------------------------

def _verify_one(
    db: Session,
    nowcast: NowcastHistory,
    auto_accept_hours: int,
) -> None:
    """Verify a single expired nowcast against actual sensor readings."""
    now = datetime.now(timezone.utc)

    # Find nearest sensor reading to valid_until.
    reading = _find_nearest_reading(db, nowcast.valid_until)
    if reading is None:
        # No sensor data — record that we tried.
        db.add(NowcastVerification(
            nowcast_id=nowcast.id,
            verified_at=now,
            element="system",
            predicted="",
            actual="",
            accuracy_score=None,
            notes="No sensor data available within verification window",
        ))
        return

    # Parse the elements from stored details JSON.
    try:
        elements = json.loads(nowcast.details)
    except (json.JSONDecodeError, TypeError):
        elements = {}

    scores: list[tuple[str, float]] = []

    # --- Temperature ---
    temp_el = elements.get("temperature")
    if isinstance(temp_el, dict) and temp_el.get("forecast"):
        predicted_temp = _extract_temperature(temp_el["forecast"])
        actual_temp = reading.outside_temp / 10.0 if reading.outside_temp is not None else None

        if predicted_temp is not None and actual_temp is not None:
            score = _score_temperature(predicted_temp, actual_temp)
            diff = predicted_temp - actual_temp
            db.add(NowcastVerification(
                nowcast_id=nowcast.id,
                verified_at=now,
                element="temperature",
                predicted=temp_el["forecast"],
                actual=f"{actual_temp:.1f}F",
                accuracy_score=score,
                notes=f"Predicted {predicted_temp:.0f}F, actual {actual_temp:.1f}F, diff {diff:+.1f}F",
            ))
            scores.append(("temperature", score))

    # --- Wind ---
    wind_el = elements.get("wind")
    if isinstance(wind_el, dict) and wind_el.get("forecast"):
        predicted_wind = _extract_wind_speed(wind_el["forecast"])
        actual_wind = float(reading.wind_speed) if reading.wind_speed is not None else None

        if predicted_wind is not None and actual_wind is not None:
            score = _score_wind(predicted_wind, actual_wind)
            diff = predicted_wind - actual_wind
            db.add(NowcastVerification(
                nowcast_id=nowcast.id,
                verified_at=now,
                element="wind",
                predicted=wind_el["forecast"],
                actual=f"{actual_wind:.0f} mph",
                accuracy_score=score,
                notes=f"Predicted {predicted_wind:.0f} mph, actual {actual_wind:.0f} mph, diff {diff:+.0f} mph",
            ))
            scores.append(("wind", score))

    # --- Precipitation ---
    precip_el = elements.get("precipitation")
    if isinstance(precip_el, dict) and precip_el.get("forecast"):
        predicted_rain = _predict_precipitation(precip_el["forecast"])
        actual_rain_rate = reading.rain_rate / 100.0 if reading.rain_rate is not None else 0.0

        score = _score_precipitation(predicted_rain, actual_rain_rate)
        actual_str = f"{actual_rain_rate:.2f} in/hr" if actual_rain_rate > 0 else "no rain"
        predicted_str = "rain predicted" if predicted_rain else "dry predicted"
        db.add(NowcastVerification(
            nowcast_id=nowcast.id,
            verified_at=now,
            element="precipitation",
            predicted=precip_el["forecast"],
            actual=actual_str,
            accuracy_score=score,
            notes=f"{predicted_str}, actual: {actual_str}",
        ))
        scores.append(("precipitation", score))

    # --- Sky (qualitative — no score) ---
    sky_el = elements.get("sky")
    if isinstance(sky_el, dict) and sky_el.get("forecast"):
        db.add(NowcastVerification(
            nowcast_id=nowcast.id,
            verified_at=now,
            element="sky",
            predicted=sky_el["forecast"],
            actual="(qualitative — not scored)",
            accuracy_score=None,
            notes=None,
        ))

    # --- Generate knowledge from significant misses ---
    for element, score in scores:
        if score < MISS_THRESHOLD:
            _create_miss_knowledge(db, nowcast, element, score, auto_accept_hours)


def _create_miss_knowledge(
    db: Session,
    nowcast: NowcastHistory,
    element: str,
    score: float,
    auto_accept_hours: int,
) -> None:
    """Create a knowledge entry from a significant prediction miss."""
    now = datetime.now(timezone.utc)
    time_str = nowcast.valid_until.strftime("%Y-%m-%d %H:%M UTC")

    auto_accept_at = None
    if auto_accept_hours > 0:
        auto_accept_at = now + timedelta(hours=auto_accept_hours)

    content = (
        f"{element.title()} prediction scored {score:.2f} for nowcast "
        f"ending {time_str}. Review this element's calibration — "
        f"the model may have a systematic bias for {element} at this location."
    )

    db.add(NowcastKnowledge(
        source="verification",
        category="bias",
        content=content,
        status="pending",
        auto_accept_at=auto_accept_at,
    ))
    logger.info("Knowledge entry created from verification miss: %s (score=%.2f)", element, score)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def verify_expired_nowcasts(db: Session, auto_accept_hours: int) -> int:
    """Verify all eligible expired nowcasts. Returns count verified.

    A nowcast is eligible when:
    - valid_until < now (forecast window has expired)
    - No NowcastVerification rows exist for that nowcast_id
    - Created within the last MAX_LOOKBACK_HOURS
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MAX_LOOKBACK_HOURS)

    # Find unverified, expired nowcasts.
    from sqlalchemy import exists

    verified_subq = (
        db.query(NowcastVerification.nowcast_id)
        .filter(NowcastVerification.nowcast_id == NowcastHistory.id)
        .exists()
    )

    eligible = (
        db.query(NowcastHistory)
        .filter(
            NowcastHistory.valid_until < now,
            NowcastHistory.created_at >= cutoff,
            ~verified_subq,
        )
        .order_by(NowcastHistory.valid_until.asc())
        .limit(10)  # Process at most 10 per tick to avoid long DB locks
        .all()
    )

    if not eligible:
        return 0

    count = 0
    for nowcast in eligible:
        try:
            _verify_one(db, nowcast, auto_accept_hours)
            count += 1
        except Exception:
            logger.exception("Failed to verify nowcast #%d", nowcast.id)

    db.commit()
    return count
