#!/usr/bin/env python3
from __future__ import annotations
import json, os, time
from datetime import datetime, date
from pathlib import Path
import pandas as pd
import requests

USER_AGENT = os.environ.get(
    "NOMINATIM_USER_AGENT",
    "ballot-events-map/1.0 (contact: ndalmon@bma.org.uk)"
)

EXCEL_PATH = "events.xlsx"
OUT_PATH = Path("data/events.json")
CACHE_PATH = Path(".geocode_cache.json")

def safe(x):
    return "" if x is None or (isinstance(x,float) and pd.isna(x)) else str(x).strip()

def parse_date(x):
    if x is None or (isinstance(x,float) and pd.isna(x)): return None
    dt = pd.to_datetime(x, errors="coerce", dayfirst=True)
    return None if pd.isna(dt) else dt.date().isoformat()

def geocode(q):
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": q, "format":"jsonv2", "limit":1},
        headers={"User-Agent": USER_AGENT},
        timeout=30
    )
    r.raise_for_status()
    j = r.json()
    if not j: return None, None
    return float(j[0]["lat"]), float(j[0]["lon"])

def main():
    if not Path(EXCEL_PATH).exists():
        raise SystemExit("events.xlsx not found")

    xls = pd.ExcelFile(EXCEL_PATH)
    events = []

    for sheet in xls.sheet_names:
        raw = pd.read_excel(EXCEL_PATH, sheet_name=sheet, header=None)
        if raw.empty:
            continue

        header_row = 0
        for i in range(min(15, len(raw))):
            row = [str(x).lower() for x in raw.iloc[i].tolist()]
            if "event" in " ".join(row) and "location" in " ".join(row):
                header_row = i
                break

        df = raw.iloc[header_row+1:].copy()
        df.columns = [safe(x) for x in raw.iloc[header_row]]
        df = df.dropna(how="all")

        cols = {c.lower(): c for c in df.columns}
        def pick(*names):
            for n in names:
                for k,v in cols.items():
                    if n.lower() in k:
                        return v
            return None

        c_date = pick("event date")
        c_loc  = pick("event location")
        c_type = pick("event type")
        c_notes= pick("notes")
        c_lead = pick("lead")
        c_lat  = pick("lat")
        c_lon  = pick("lon")

        for _,r in df.iterrows():
            loc = safe(r.get(c_loc))
            if not loc:
                continue

            lat = r.get(c_lat) if c_lat else None
            lon = r.get(c_lon) if c_lon else None
            lat = None if pd.isna(lat) else float(lat)
            lon = None if pd.isna(lon) else float(lon)

            events.append({
                "region": sheet.strip(),
                "date": parse_date(r.get(c_date)),
                "location": loc,
                "event_type": safe(r.get(c_type)),
                "notes": safe(r.get(c_notes)),
                "lead": safe(r.get(c_lead)),
                "lat": lat,
                "lon": lon,
                "location_key": loc.lower().strip()
            })

    cache = {}
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text())

    for e in events:
        if e["lat"] is None or e["lon"] is None:
            key = e["location_key"]
            if key in cache:
                e["lat"], e["lon"] = cache[key]
            else:
                lat, lon = geocode(f"{e['location']}, United Kingdom")
                cache[key] = (lat, lon)
                e["lat"], e["lon"] = lat, lon
                time.sleep(1)

    CACHE_PATH.write_text(json.dumps(cache, indent=2))

    payload = {
        "meta": {
            "generated_at": datetime.utcnow().isoformat()+"Z",
            "event_count": len(events)
        },
        "events": events
    }

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {OUT_PATH}")

if __name__ == "__main__":
    main()
