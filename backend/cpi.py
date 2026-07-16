"""CPI inflation series — fetched from the BLS public API, stored in Supabase.

Uses BLS series CUUR0000SA0 (CPI-U, all items, not seasonally adjusted — the
conventional headline inflation series). The keyless v1 API allows 25 requests
per day and 10 years per request; we need roughly one request per month, and
holdings older than the stored window fall back to the earliest stored month.

Set BLS_API_KEY in .env to use the registered v2 API (500 req/day, 20 years).
Fallback if BLS is ever unavailable: FRED series CPIAUCNS (needs FRED_API_KEY).
"""

from datetime import date, timedelta
import os

import requests

SERIES_ID = "CUUR0000SA0"
_YEARS_BACK = 10


def _fetch_bls(start_year: int, end_year: int) -> list[dict]:
    """Return [{"month": "YYYY-MM-01", "value": float}] from the BLS API."""
    api_key = os.getenv("BLS_API_KEY")
    version = "v2" if api_key else "v1"
    payload: dict = {
        "seriesid": [SERIES_ID],
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    if api_key:
        payload["registrationkey"] = api_key

    resp = requests.post(
        f"https://api.bls.gov/publicAPI/{version}/timeseries/data/",
        json=payload, timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API error: {body.get('message')}")

    rows = []
    for series in body["Results"]["series"]:
        for item in series.get("data", []):
            period = item.get("period", "")
            if not period.startswith("M") or period == "M13":  # M13 = annual average
                continue
            try:
                value = float(item["value"])  # unpublished months come back as "-"
            except (ValueError, TypeError):
                continue
            rows.append({
                "month": f"{item['year']}-{period[1:]}-01",
                "value": value,
            })
    return rows


def ensure_cpi(db) -> dict[str, float]:
    """Return the stored CPI series as {"YYYY-MM-01": value}, refreshing from
    BLS first if the newest stored month is more than ~35 days old."""
    stored = db.table("cpi_monthly").select("month,value").eq("series_id", SERIES_ID) \
        .order("month", desc=True).limit(1).execute()
    newest = date.fromisoformat(stored.data[0]["month"]) if stored.data else None

    if newest is None or date.today() - newest > timedelta(days=35):
        start_year = newest.year if newest else date.today().year - _YEARS_BACK
        rows = _fetch_bls(start_year, date.today().year)
        if rows:
            db.table("cpi_monthly").upsert(
                [{"series_id": SERIES_ID, **r} for r in rows],
                on_conflict="series_id,month",
            ).execute()

    all_rows = db.table("cpi_monthly").select("month,value").eq("series_id", SERIES_ID) \
        .order("month").execute()
    return {r["month"]: float(r["value"]) for r in all_rows.data}


def cpi_at(series: dict[str, float], on: date) -> float | None:
    """CPI value for the month containing `on`, falling back to the nearest
    earlier month, then the earliest stored month."""
    if not series:
        return None
    key = f"{on.year}-{on.month:02d}-01"
    if key in series:
        return series[key]
    earlier = [m for m in series if m <= key]
    if earlier:
        return series[max(earlier)]
    return series[min(series)]
