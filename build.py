#!/usr/bin/env python3
"""
Build script: converts the Excel workbook into ./docs/data/events.json
and geocodes event locations (with caching).

Expected workflow:
- Put the Excel file in the repo root as "events.xlsx" (or set EXCEL_PATH env var).
- Run: python build.py
- Commit + push. GitHub Actions (provided) can run this automatically.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, date, time as dtime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

USER_AGENT = os.environ.get("NOMINATIM_USER_AGENT", "events-map-builder/1.0 (contact: you@example.com)")
EXCEL_PATH = os.environ.get("EXCEL_PATH", "events.xlsx")
OUT_DIR = Path("docs/data")
CACHE_PATH = Path(".geocode_cache.json")

def _safe_str(x: Any) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return str(x).strip()

def _parse_date(x: Any) -> Optional[str]:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, (datetime, date)):
        return datetime(x.year, x.month, x.day).date().isoformat()
    # try pandas parse
    try:
        dt = pd.to_datetime(x, errors="coerce")
        if pd.isna(dt):
            return None
        return dt.date().isoformat()
    except Exception:
        return None

def _parse_time(x: Any) -> Optional[str]:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, dtime):
        return f"{x.hour:02d}:{x.minute:02d}"
    try:
        dt = pd.to_datetime(x, errors="coerce")
        if pd.isna(dt):
            return None
        return f"{dt.hour:02d}:{dt.minute:02d}"
    except Exception:
        # fallback: accept strings like "13:00:00"
        s = _safe_str(x)
        if len(s) >= 5 and s[2] == ":":
            return s[:5]
        return None

def load_cache() -> Dict[str, Dict[str, Any]]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_cache(cache: Dict[str, Dict[str, Any]]) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

def nominatim_geocode(q: str) -> Optional[Tuple[float, float, str]]:
    """
    Geocode via Nominatim.
    Returns (lat, lon, display_name) or None.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": q, "format": "jsonv2", "limit": 1, "addressdetails": 0}
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(url, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    top = data[0]
    return float(top["lat"]), float(top["lon"]), str(top.get("display_name",""))

def ensure_geocode(location: str, cache: Dict[str, Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    key = location.lower().strip()
    if not key:
        return None, None

    if key in cache and "lat" in cache[key] and "lon" in cache[key]:
        return cache[key]["lat"], cache[key]["lon"]

    # bias query to UK
    query = f"{location}, United Kingdom"
    try:
        res = nominatim_geocode(query)
    except Exception:
        res = None

    # If failed, try raw
    if res is None:
        try:
            res = nominatim_geocode(location)
        except Exception:
            res = None

    if res is None:
        cache[key] = {"lat": None, "lon": None, "ts": datetime.utcnow().isoformat() + "Z"}
        return None, None

    lat, lon, display = res
    cache[key] = {"lat": lat, "lon": lon, "display_name": display, "ts": datetime.utcnow().isoformat() + "Z"}
    # Respect Nominatim usage policy: 1 request/sec
    time.sleep(1.1)
    return lat, lon

def read_events(excel_path: str) -> List[Dict[str, Any]]:
    xls = pd.ExcelFile(excel_path)
    out: List[Dict[str, Any]] = []

    for sheet in xls.sheet_names:
        raw = pd.read_excel(excel_path, sheet_name=sheet, header=None)
        if raw.empty:
            continue

        # Find header row containing "Event date" and "Event location"
        header_row = None
        for i in range(min(10, len(raw))):
            row = [str(x).strip().lower() for x in raw.iloc[i].tolist()]
            if any("event date" in c for c in row) and any("event location" in c for c in row):
                header_row = i
                break

        if header_row is None:
            # fallback: assume first row is header
            header_row = 0

        header = [_safe_str(x) for x in raw.iloc[header_row].tolist()]
        df = raw.iloc[header_row+1:].copy()
        df.columns = header
        df = df.dropna(how="all")

        # Normalize column names
        cols = {c.strip().lower(): c for c in df.columns}
        def pick(*names: str) -> Optional[str]:
            for n in names:
                if n.lower() in cols:
                    return cols[n.lower()]
            # allow partial matches
            for key, orig in cols.items():
                for n in names:
                    if n.lower() in key:
                        return orig
            return None

        c_date = pick("Event date")
        c_loc  = pick("Event location")
        c_time = pick("Start time")
        c_type = pick("Event type")
        c_notes= pick("Notes")
        c_lead = pick("Lead rep/ staff member", "Lead rep/staff member", "Lead")

        # Build events
        for _, r in df.iterrows():
            loc = _safe_str(r.get(c_loc)) if c_loc else ""
            if not loc:
                continue
            ev = {
                "region": sheet.strip(),
                "date": _parse_date(r.get(c_date)) if c_date else None,
                "start_time": _parse_time(r.get(c_time)) if c_time else None,
                "location": loc,
                "event_type": _safe_str(r.get(c_type)) if c_type else "",
                "notes": _safe_str(r.get(c_notes)) if c_notes else "",
                "lead": _safe_str(r.get(c_lead)) if c_lead else "",
            }
            out.append(ev)

    # Deterministic IDs
    for i, e in enumerate(out, start=1):
        e["id"] = f"EVT-{i:04d}"
    return out

def main() -> None:
    excel_path = EXCEL_PATH
    if not Path(excel_path).exists():
        raise SystemExit(f"Excel file not found: {excel_path}. Put it in the repo root or set EXCEL_PATH.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    events = read_events(excel_path)
    cache = load_cache()

    # Geocode unique locations
    unique = {}
    for e in events:
        k = e["location"].lower().strip()
        unique[k] = e["location"]

    for k, loc in unique.items():
        lat, lon = ensure_geocode(loc, cache)
        # store back into events
        for e in events:
            if e["location"].lower().strip() == k:
                e["lat"] = lat
                e["lon"] = lon
                e["location_key"] = k

    save_cache(cache)

    payload = {
        "meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "source_excel": excel_path,
            "event_count": len(events),
            "unique_locations": len(unique),
        },
        "events": events,
    }

    (OUT_DIR / "events.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_DIR/'events.json'} with {len(events)} events.")

if __name__ == "__main__":
    main()
