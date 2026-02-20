/**
 * Timezone utilities for display and Highcharts integration.
 *
 * Stores the user's preferred timezone in localStorage.
 * Default is "auto" which uses the device's local timezone.
 */
import Highcharts from "highcharts";

// Monkey-patch Highcharts Time.prototype.dateTimeFormat to guard against
// non-finite timestamps. Highcharts internally generates non-finite tick
// values during axis calculation and passes them to Intl.DateTimeFormat.format(),
// which throws RangeError on some platforms (notably Windows desktop browsers).
// Fallback to formatting epoch 0 so downstream split/parse stays valid.
const HCTime = (Highcharts as unknown as { Time: { prototype: Record<string, unknown> } }).Time.prototype;
const origDtf = HCTime.dateTimeFormat as (...args: unknown[]) => string;
HCTime.dateTimeFormat = function (
  options: unknown,
  timestamp: number,
  locale?: string,
): string {
  if (!Number.isFinite(timestamp)) {
    return origDtf.call(this, options, 0, locale);
  }
  return origDtf.call(this, options, timestamp, locale);
};

const STORAGE_KEY = "davis-wx-timezone";

export function getTimezone(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || "auto";
  } catch {
    return "auto";
  }
}

export function setTimezone(tz: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, tz);
  } catch {
    // localStorage may be unavailable
  }
}

/** Resolve "auto" to the actual IANA timezone string. */
export function resolveTimezone(): string {
  const stored = getTimezone();
  if (stored === "auto") {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  }
  return stored;
}

/** Returns a Highcharts `time` config for the user's selected timezone. */
export function getHighchartsTimeConfig(): Highcharts.TimeOptions {
  return { timezone: resolveTimezone() };
}

/** Build a list of timezone options for the Settings dropdown. */
export function getTimezoneOptions(): string[] {
  try {
    // Modern browsers support Intl.supportedValuesOf
    if (typeof Intl !== "undefined" && "supportedValuesOf" in Intl) {
      return (Intl as unknown as { supportedValuesOf: (key: string) => string[] })
        .supportedValuesOf("timeZone");
    }
  } catch {
    // fallback
  }
  // Minimal fallback list
  return [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Australia/Sydney",
    "UTC",
  ];
}
