"""Claude AI analyst for generating hyper-local nowcasts.

Takes a collected data snapshot and produces a structured nowcast
via the Anthropic API.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import anthropic

from .nowcast_collector import CollectedData

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a mesoscale weather analyst for a personal weather station. Your role
is to refine broad numerical weather model guidance using real-time local
observations to produce accurate, hyper-local nowcasts.

HARD CONSTRAINTS:
- Never fabricate observations or station data.
- Never predict beyond what the data supports.
- Always distinguish between: "model guidance says X", "observations show Y",
  and "I am adjusting to Z because of [specific evidence]".
- Cite which data points informed each conclusion.
- Default to model guidance when local data is insufficient or contradictory.
- Express confidence per forecast element: HIGH, MEDIUM, or LOW.
- If data is contradictory or insufficient, say so explicitly.

ANALYTICAL METHOD:
1. Summarize current conditions from station observations.
2. Compare observations against model expectations — flag any divergences.
3. Analyze trends: 3-hour pressure tendency, temperature trajectory,
   dewpoint depression changes, wind direction shifts.
4. If nearby station data is available, identify spatial propagation patterns.
5. Produce timing refinements for precipitation onset/cessation,
   temperature extremes, and wind changes.
6. Assess confidence for each forecast element based on data agreement.

TIME REFERENCES:
- Express ALL times in the station's local timezone as specified in the
  request. Use 12-hour format with AM/PM (e.g., "2:30 PM", "around 10 PM").
- Never use UTC in user-facing text unless the request specifies UTC.

OUTPUT FORMAT — respond with ONLY a JSON object (no markdown, no commentary):
{
  "summary": "2-3 sentence natural language nowcast for general audience",
  "current_vs_model": "Where and how observations diverge from model guidance",
  "elements": {
    "temperature": {"forecast": "...", "confidence": "HIGH|MEDIUM|LOW"},
    "precipitation": {"forecast": "...", "confidence": "...", "timing": "..."},
    "wind": {"forecast": "...", "confidence": "..."},
    "sky": {"forecast": "...", "confidence": "..."},
    "special": null or "fog/frost/severe weather note"
  },
  "farming_impact": "Brief agriculture-relevant note (field conditions, frost risk, spray windows, etc.)",
  "data_quality": "Assessment of input data sufficiency and any gaps",
  "proposed_knowledge": null or {"category": "bias|timing|terrain|seasonal", "content": "Learned insight for future reference"}
}
"""


def _resolve_api_key(db_key: str) -> Optional[str]:
    """Check ANTHROPIC_API_KEY env var first, fall back to DB config value."""
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return env_key
    if db_key:
        return db_key
    return None


def _build_user_message(data: CollectedData, horizon_hours: int) -> str:
    """Assemble the collected data into a structured user message for Claude."""
    parts = []

    tz_label = data.station_timezone or "UTC"
    parts.append(f"=== NOWCAST REQUEST ===")
    parts.append(f"Location: {data.location.get('latitude')}, {data.location.get('longitude')}")
    parts.append(f"Station timezone: {tz_label}")
    parts.append(f"Generated: {data.collected_at}")
    parts.append(f"Forecast horizon: next {horizon_hours} hours")
    parts.append(f"Express all times in {tz_label} local time using 12-hour AM/PM format.")
    parts.append("")

    # Station observations
    parts.append("=== CURRENT STATION OBSERVATIONS ===")
    if data.station.has_data and data.station.latest:
        for key, val in data.station.latest.items():
            if val is not None:
                parts.append(f"  {key}: {val}")
    else:
        parts.append("  No station data available.")
    parts.append("")

    # 3-hour trend
    if data.station.trend_3h:
        parts.append("=== 3-HOUR TREND (sampled every ~15 min) ===")
        for reading in data.station.trend_3h:
            ts = reading.get("timestamp", "?")
            temp = reading.get("outside_temp_f", "?")
            baro = reading.get("barometer_inHg", "?")
            hum = reading.get("outside_humidity_pct", "?")
            wind = reading.get("wind_speed_mph", "?")
            wdir = reading.get("wind_direction_deg", "?")
            parts.append(f"  {ts} | Temp={temp}F Baro={baro}inHg Hum={hum}% Wind={wind}mph@{wdir}deg")
        parts.append("")

    # Model guidance
    if data.model_guidance and data.model_guidance.hourly:
        parts.append("=== MODEL GUIDANCE (HRRR/GFS via Open-Meteo) ===")
        hourly = data.model_guidance.hourly
        times = hourly.get("time", [])
        for i, t in enumerate(times[:horizon_hours]):
            vals = []
            for var in ["temperature_2m", "relative_humidity_2m", "precipitation",
                        "wind_speed_10m", "wind_direction_10m", "cloud_cover",
                        "pressure_msl"]:
                v = hourly.get(var, [])
                if i < len(v) and v[i] is not None:
                    vals.append(f"{var}={v[i]}")
            parts.append(f"  {t}: {', '.join(vals)}")
        parts.append("")

    # NWS forecast summary
    if data.nws_summary:
        parts.append("=== NWS FORECAST SUMMARY ===")
        parts.append(data.nws_summary)
        parts.append("")

    # Knowledge base
    if data.knowledge_entries:
        parts.append("=== LOCAL KNOWLEDGE BASE (verified insights about this station) ===")
        for entry in data.knowledge_entries:
            parts.append(f"  - {entry}")
        parts.append("")

    return "\n".join(parts)


@dataclass
class AnalystResult:
    """Parsed result from Claude's nowcast analysis."""
    summary: str
    current_vs_model: str
    elements: dict[str, Any]
    farming_impact: Optional[str]
    data_quality: str
    proposed_knowledge: Optional[dict[str, str]]
    raw_response: str
    input_tokens: int
    output_tokens: int


async def generate_nowcast(
    data: CollectedData,
    model: str,
    api_key_from_db: str,
    horizon_hours: int = 2,
) -> Optional[AnalystResult]:
    """Call Claude API to generate a nowcast from collected data.

    Args:
        data: Collected data snapshot from all sources.
        model: Claude model ID (e.g., "claude-haiku-4-5-20251001").
        api_key_from_db: API key from database config (env var checked first).
        horizon_hours: Forecast window in hours.

    Returns:
        AnalystResult on success, None if API unavailable or key missing.
    """
    api_key = _resolve_api_key(api_key_from_db)
    if not api_key:
        logger.warning("Nowcast skipped: no Anthropic API key configured")
        return None

    user_message = _build_user_message(data, horizon_hours)

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=model,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.AuthenticationError:
        logger.error("Nowcast failed: invalid Anthropic API key")
        return None
    except Exception as exc:
        logger.error("Nowcast Claude API call failed: %s", exc)
        return None

    raw_text = response.content[0].text if response.content else ""
    input_tokens = response.usage.input_tokens if response.usage else 0
    output_tokens = response.usage.output_tokens if response.usage else 0

    # Parse JSON from response (Claude may wrap in markdown code block).
    json_text = raw_text.strip()
    if json_text.startswith("```"):
        # Strip markdown code fences.
        lines = json_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        json_text = "\n".join(lines)

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        logger.error("Nowcast response was not valid JSON: %s", raw_text[:200])
        # Store raw response as a minimal result so it's not lost.
        return AnalystResult(
            summary=raw_text[:500],
            current_vs_model="",
            elements={},
            farming_impact=None,
            data_quality="Response parsing failed",
            proposed_knowledge=None,
            raw_response=raw_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    # Extract proposed knowledge entry if present.
    proposed_knowledge = parsed.get("proposed_knowledge")
    if isinstance(proposed_knowledge, dict):
        if not (proposed_knowledge.get("category") and proposed_knowledge.get("content")):
            proposed_knowledge = None

    return AnalystResult(
        summary=parsed.get("summary", ""),
        current_vs_model=parsed.get("current_vs_model", ""),
        elements=parsed.get("elements", {}),
        farming_impact=parsed.get("farming_impact"),
        data_quality=parsed.get("data_quality", ""),
        proposed_knowledge=proposed_knowledge,
        raw_response=raw_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
