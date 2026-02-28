"""Claude AI analyst for generating hyper-local nowcasts.

Takes a collected data snapshot and produces a structured nowcast
via the Anthropic API.
"""

import json
import logging
import os
import re
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

RADAR ANALYSIS (when radar imagery is provided):
- The image is NEXRAD composite reflectivity centered on the station.
- Reflectivity color scale: green = light rain (~15-30 dBZ),
  yellow = moderate-heavy (~35-45 dBZ), orange/red = very heavy (~45-60 dBZ),
  purple/white = severe (60+ dBZ). Blues may indicate snow.
- Analyze: precipitation coverage near station, echo movement direction
  (compare with model wind fields), approaching or departing precipitation,
  convective vs stratiform character, line segments or mesoscale structures.
- Use radar to refine precipitation timing: if echoes are 50 miles away
  moving at 30 mph, onset is approximately 1.5-2 hours out.
- If no significant echoes near the station, note radar is clear and state
  confidence in the dry forecast.
- Do NOT describe image colors/pixels — translate what you see into weather
  terms (e.g., "A band of moderate rain approaching from the southwest").

NWS ACTIVE ALERTS (when provided):
- Watches, warnings, and advisories active for the station location are
  included in the data.  Reference them explicitly:
  * WARNINGS (Extreme/Severe) indicate imminent or occurring hazard —
    ALWAYS include the threat in the "special" field with actionable guidance.
  * WATCHES (Moderate) indicate potential hazard — mention in summary and
    the relevant forecast element (precipitation, wind, etc.).
  * ADVISORIES (Minor) indicate moderate hazard — mention in the relevant
    forecast element.
- Cross-reference alert timing with your radar and model analysis.
- When a warning is active, correlate local station observations and nearby
  station data to provide hyper-local situational awareness (e.g., "Barometer
  dropping rapidly consistent with approaching storm cited in warning").

SPECIAL CONDITIONS:
- The "special" field is for conditions that ARE occurring or imminent.
  Set it to null when no special conditions exist. Do NOT discuss why a
  condition is absent — only report what IS happening.
- When NWS warnings are active, the "special" field MUST include the threat
  with specific local correlation evidence and actionable guidance.
- FROST: Only mention when forecast air temp is 36°F or below.
  Never mention frost when temps are above 40°F.
- FOG: Only mention when visibility reduction is expected or occurring.
- HEAT: Only mention when heat index exceeds 100°F.
- WIND CHILL: Only mention when air temp is below 40°F AND wind > 5 mph.

TIME REFERENCES:
- Express ALL times in the station's local timezone as specified in the
  request. Use 12-hour format with AM/PM (e.g., "2:30 PM", "around 10 PM").
- Never use UTC in user-facing text unless the request specifies UTC.

OUTPUT FORMAT — respond with ONLY a JSON object (no markdown, no commentary):
{
  "summary": "2-3 sentence natural language nowcast for general audience",
  "current_vs_model": "Where and how observations diverge from model guidance",
  "radar_analysis": null or "Brief description of what radar shows and timing implications",
  "elements": {
    "temperature": {"forecast": "...", "confidence": "HIGH|MEDIUM|LOW"},
    "precipitation": {"forecast": "...", "confidence": "...", "timing": "..."},
    "wind": {"forecast": "...", "confidence": "..."},
    "sky": {"forecast": "...", "confidence": "..."},
    "special": null or "active/imminent special condition (fog, frost, severe weather) — null if none"
  },
  "farming_impact": "Brief agriculture-relevant note (field conditions, frost risk, spray windows, etc.)",
  "data_quality": "Assessment of input data sufficiency and any gaps",
  "proposed_knowledge": null or {"category": "bias|timing|terrain|seasonal", "content": "Learned insight for future reference"},
  "spray_advisory": null or {
    "summary": "Overall spray conditions assessment for the next several hours",
    "recommendations": [
      {
        "schedule_id": 123,
        "product_name": "...",
        "go": true or false,
        "detail": "Specific recommendation with timing, e.g. 'Wind drops below 8 mph by 2 PM — spray window 2-5 PM looks good. Rain not expected until after 10 PM, giving 8+ hours rain-free.'"
      }
    ]
  }
}

SPRAY APPLICATION ADVISORY (when spray schedules are provided):
- Evaluate each scheduled spray against forecast conditions for its planned window.
- For each product, check ALL constraints: wind (including gusts), temperature range,
  rain-free hours after application, and humidity if applicable.
- Be specific about timing: "Wind at 12 mph now but forecast to drop to 6 mph by 2 PM"
  is much more useful than "wind is marginal."
- If the planned window is not ideal, suggest the best alternative window within 24 hours.
- Consider the rain-free requirement carefully — a product needing 4h rain-free at 3 PM
  with rain forecast at 6 PM is a NO-GO even if all other conditions are met.
- If no spray schedules are provided, set spray_advisory to null.
- When spray outcome history is provided, use it to calibrate your recommendations:
  * Note patterns where a product was effective despite marginal conditions.
  * Flag conditions that consistently led to poor outcomes.
  * Reference specific outcome counts: "This product has been effective in
    similar conditions 4 of 5 times at this station."
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

    # NWS active alerts
    if data.nws_alerts:
        parts.append("=== NWS ACTIVE ALERTS (watches/warnings/advisories for this location) ===")
        for alert in data.nws_alerts:
            parts.append(f"  [{alert['severity'].upper()}] {alert['event']}")
            parts.append(f"    Headline: {alert['headline']}")
            parts.append(f"    Urgency: {alert['urgency']} | Certainty: {alert['certainty']}")
            parts.append(f"    Onset: {alert['onset']} | Expires: {alert['expires']}")
            if alert.get("instruction"):
                parts.append(f"    Action: {alert['instruction'][:300]}")
        parts.append("")

    # Knowledge base
    if data.knowledge_entries:
        parts.append("=== LOCAL KNOWLEDGE BASE (verified insights about this station) ===")
        for entry in data.knowledge_entries:
            parts.append(f"  - {entry}")
        parts.append("")

    # Spray schedules
    if data.spray_schedules:
        parts.append("=== UPCOMING SPRAY SCHEDULES (evaluate each against forecast) ===")
        for sched in data.spray_schedules:
            c = sched["constraints"]
            parts.append(
                f"  Schedule #{sched['schedule_id']}: {sched['product_name']} ({sched['category']})"
            )
            parts.append(
                f"    Planned: {sched['planned_date']} {sched['planned_start']}-{sched['planned_end']}"
            )
            parts.append(
                f"    Constraints: wind <{c['max_wind_mph']} mph, "
                f"temp {c['min_temp_f']}-{c['max_temp_f']}F, "
                f"rain-free {c['rain_free_hours']}h"
                + (f", humidity {c['min_humidity_pct']}-{c['max_humidity_pct']}%"
                   if c.get('min_humidity_pct') is not None else "")
            )
            if sched.get("notes"):
                parts.append(f"    Notes: {sched['notes']}")
        parts.append("")

    # Spray outcome history
    if data.spray_outcomes:
        parts.append("=== SPRAY OUTCOME HISTORY (farmer-reported effectiveness) ===")
        # Aggregate by product for a compact summary.
        by_product: dict[str, list[dict]] = {}
        for o in data.spray_outcomes:
            by_product.setdefault(o["product_name"], []).append(o)
        for product_name, outcomes in by_product.items():
            total = len(outcomes)
            avg_eff = sum(o["effectiveness"] for o in outcomes) / total
            successes = sum(1 for o in outcomes if o["effectiveness"] >= 4)
            drift_count = sum(1 for o in outcomes if o.get("drift_observed"))
            parts.append(f"  {product_name}: {total} applications logged")
            parts.append(
                f"    Avg effectiveness: {avg_eff:.1f}/5, "
                f"Success rate: {round(successes / total * 100)}%"
            )
            winds = [o["actual_wind_mph"] for o in outcomes if o.get("actual_wind_mph") is not None]
            if winds:
                parts.append(f"    Effective at wind up to {max(winds):.0f} mph ({len(winds)} outcomes)")
            if drift_count:
                parts.append(f"    Drift observed in {drift_count}/{total} applications")
            notes = [o["notes"] for o in outcomes if o.get("notes")]
            if notes:
                parts.append(f"    Recent notes: {notes[0][:100]}")
        parts.append("")

    # Nearby station observations
    if data.nearby_stations and data.nearby_stations.stations:
        parts.append("=== NEARBY STATION OBSERVATIONS (spatial context) ===")
        for obs in data.nearby_stations.stations:
            header = (
                f"  {obs.station_id} ({obs.station_name}) "
                f"— {obs.distance_miles:.1f} mi {obs.bearing_cardinal}, {obs.source}"
            )
            fields = []
            if obs.temp_f is not None:
                fields.append(f"Temp={obs.temp_f:.1f}F")
            if obs.dew_point_f is not None:
                fields.append(f"Dewpt={obs.dew_point_f:.1f}F")
            if obs.humidity_pct is not None:
                fields.append(f"Hum={obs.humidity_pct}%")
            if obs.wind_speed_mph is not None:
                wind = f"Wind={obs.wind_speed_mph:.0f}mph"
                if obs.wind_dir_deg is not None:
                    wind += f"@{obs.wind_dir_deg}deg"
                fields.append(wind)
            if obs.wind_gust_mph is not None:
                fields.append(f"Gust={obs.wind_gust_mph:.0f}mph")
            if obs.pressure_inhg is not None:
                fields.append(f"Baro={obs.pressure_inhg:.2f}inHg")
            if obs.precip_in is not None:
                fields.append(f"Precip={obs.precip_in:.2f}in")
            if obs.sky_cover:
                fields.append(f"Sky={obs.sky_cover}")
            parts.append(header)
            if fields:
                parts.append(f"    {', '.join(fields)}")
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
    radar_analysis: Optional[str] = None
    spray_advisory: Optional[dict[str, Any]] = None
    truncated: bool = False
    parse_failed: bool = False


def _build_user_content(
    data: CollectedData, horizon_hours: int,
) -> str | list[dict]:
    """Build user message content, with optional radar image blocks.

    Returns a plain string when no radar images are available (no overhead),
    or a list of multimodal content blocks (text + images) when radar is present.
    """
    text_message = _build_user_message(data, horizon_hours)

    if not data.radar_images:
        return text_message

    blocks: list[dict] = [{"type": "text", "text": text_message}]

    for img in data.radar_images:
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img.png_base64,
            },
        })
        bbox = img.bbox
        miles_ns = (bbox[3] - bbox[1]) * 69
        blocks.append({
            "type": "text",
            "text": (
                f"Above: {img.label} centered on station location. "
                f"Covers {bbox[1]:.2f}N to {bbox[3]:.2f}N, "
                f"{abs(bbox[0]):.2f}W to {abs(bbox[2]):.2f}W "
                f"(~{miles_ns:.0f} miles N-S). Station is at center."
            ),
        })

    return blocks


async def generate_nowcast(
    data: CollectedData,
    model: str,
    api_key_from_db: str,
    horizon_hours: int = 2,
    max_tokens: int = 2500,
) -> Optional[AnalystResult]:
    """Call Claude API to generate a nowcast from collected data.

    Args:
        data: Collected data snapshot from all sources.
        model: Claude model ID (e.g., "claude-haiku-4-5-20251001").
        api_key_from_db: API key from database config (env var checked first).
        horizon_hours: Forecast window in hours.
        max_tokens: Maximum output tokens for the API call.

    Returns:
        AnalystResult on success, None if API unavailable or key missing.
    """
    api_key = _resolve_api_key(api_key_from_db)
    if not api_key:
        logger.warning("Nowcast skipped: no Anthropic API key configured")
        return None

    user_content = _build_user_content(data, horizon_hours)

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
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

    truncated = response.stop_reason == "max_tokens"
    if truncated:
        logger.warning("Nowcast response truncated at max_tokens=%d (%d output tokens)", max_tokens, output_tokens)

    # Parse JSON from response — Claude may wrap in markdown code fences,
    # include trailing commas, or add commentary after the JSON object.
    json_text = raw_text.strip()

    # Strip code fences if present.
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", json_text, re.DOTALL)
    if fence_match:
        json_text = fence_match.group(1).strip()

    # Find the start of the JSON object.
    brace_start = json_text.find("{")
    if brace_start != -1:
        json_text = json_text[brace_start:]

    # Fix trailing commas (common LLM JSON error).
    json_text = re.sub(r",\s*}", "}", json_text)
    json_text = re.sub(r",\s*]", "]", json_text)

    # Use raw_decode to parse just the first JSON object, ignoring any
    # trailing commentary Claude may have added after the JSON.
    try:
        decoder = json.JSONDecoder()
        parsed, _ = decoder.raw_decode(json_text)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Nowcast JSON parse failed: %s | raw[:300]: %s", exc, raw_text[:300])
        # Return a minimal result flagged as failed so the service can retry.
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
            truncated=truncated,
            parse_failed=True,
        )

    # Extract proposed knowledge entry if present.
    proposed_knowledge = parsed.get("proposed_knowledge")
    if isinstance(proposed_knowledge, dict):
        if not (proposed_knowledge.get("category") and proposed_knowledge.get("content")):
            proposed_knowledge = None

    # Extract spray advisory if present.
    spray_advisory = parsed.get("spray_advisory")
    if spray_advisory is not None and not isinstance(spray_advisory, dict):
        spray_advisory = None

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
        radar_analysis=parsed.get("radar_analysis"),
        spray_advisory=spray_advisory,
        truncated=truncated,
    )
