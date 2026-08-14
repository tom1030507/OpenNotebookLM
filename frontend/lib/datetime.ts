/**
 * Timestamps arrive from the API as ISO 8601 strings.
 *
 * The backend stores them naive and in UTC, and now labels them on the way out.
 * Rows written before that fix can still reach the client bare —
 * `2026-08-13T16:29:50` — and ECMAScript parses a designator-less *date-time* as
 * local time, unlike a designator-less *date*, which it parses as UTC. Handing
 * such a value straight to `new Date(...)` therefore skews it by the viewer's
 * UTC offset: a conversation created seconds ago reads as "about 8 hours ago"
 * for a viewer in UTC+8, and falls into the wrong date-group header.
 *
 * Every timestamp the client parses goes through here so that assumption lives
 * in one place.
 */

/** `Z`, or a numeric offset such as `+08:00`, `-0500` or `+08`. */
const TIMEZONE_DESIGNATOR = /(?:Z|[+-]\d{2}(?::?\d{2})?)$/i;

/** An ISO date-time: a date, then a time, whatever separates them. */
const HAS_TIME_PART = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/;

/**
 * Parses a timestamp emitted by the API, reading a designator-less value as UTC.
 *
 * Values that already say which zone they are in are left exactly as they are,
 * so a `Z` or an offset is still honoured.
 */
export function parseApiTimestamp(value: string): Date {
  const trimmed = value.trim();

  if (!HAS_TIME_PART.test(trimmed) || TIMEZONE_DESIGNATOR.test(trimmed)) {
    // A date with no time is already UTC by specification, and anything
    // carrying a designator needs no help. Anything unparseable stays
    // unparseable rather than being silently reshaped.
    return new Date(trimmed);
  }

  return new Date(`${trimmed.replace(' ', 'T')}Z`);
}
