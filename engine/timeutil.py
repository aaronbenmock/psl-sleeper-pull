"""US Central time without tzdata (Windows Python has no zone database by default).

Rule: CDT (UTC-5) from the second Sunday in March 02:00 local to the first Sunday in
November 02:00 local; otherwise CST (UTC-6). This matches zoneinfo for 2007 onward.
"""
import datetime as dt

UTC = dt.timezone.utc


def _nth_sunday(year, month, n):
    d = dt.date(year, month, 1)
    first_sunday = d + dt.timedelta(days=(6 - d.weekday()) % 7)
    return first_sunday + dt.timedelta(weeks=n - 1)


def central_offset(utc_dt):
    """Return the UTC offset (hours, negative) in effect for this UTC instant."""
    y = utc_dt.year
    # DST starts 2:00 CST = 08:00 UTC on the 2nd Sunday of March
    start = dt.datetime.combine(_nth_sunday(y, 3, 2), dt.time(8, 0), tzinfo=UTC)
    # DST ends 2:00 CDT = 07:00 UTC on the 1st Sunday of November
    end = dt.datetime.combine(_nth_sunday(y, 11, 1), dt.time(7, 0), tzinfo=UTC)
    return -5 if start <= utc_dt < end else -6


def to_central(utc_dt):
    off = central_offset(utc_dt)
    tz = dt.timezone(dt.timedelta(hours=off), "CDT" if off == -5 else "CST")
    return utc_dt.astimezone(tz)


def now_utc():
    """Current UTC time. ENGINE_FAKE_NOW (ISO 8601) overrides it for local scenario tests only."""
    import os
    fake = os.environ.get("ENGINE_FAKE_NOW")
    if fake:
        return parse_iso(fake)
    return dt.datetime.now(UTC).replace(microsecond=0)


def now_central():
    return to_central(now_utc())


def in_window(local_dt, hours, days=None):
    """True if local_dt falls in one of the listed Central hours on an allowed weekday.

    GitHub starts crons late under load, so any minute of the hour counts, but the window never
    reaches the next hour: the duplicate DST cron lands exactly one hour off and must be rejected
    (except where a task lists both hours on purpose, like the Wednesday pull).
    """
    if days is not None and local_dt.weekday() not in days:
        return False
    return local_dt.hour in hours


def eastern_date(utc_dt):
    """Game-day date as the NFL sees it (US Eastern). Same DST rule, offset -4/-5."""
    off = central_offset(utc_dt) + 1
    return (utc_dt + dt.timedelta(hours=off)).date()


def iso(utc_dt):
    return utc_dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def self_test():
    """Cross-check against zoneinfo when it is available (Linux runners have tzdata)."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        return "zoneinfo unavailable, skipped"
    try:
        z = ZoneInfo("America/Chicago")
    except Exception:
        return "tzdata unavailable, skipped"
    mismatches = []
    for day in range(0, 366, 1):
        for hour in (1, 7, 8, 12, 23):
            u = dt.datetime(2026, 1, 1, hour, 30, tzinfo=UTC) + dt.timedelta(days=day)
            mine = to_central(u).utcoffset()
            ref = u.astimezone(z).utcoffset()
            if mine != ref:
                mismatches.append(u.isoformat())
    return f"{len(mismatches)} mismatches vs zoneinfo" + (f": {mismatches[:3]}" if mismatches else "")
