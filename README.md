# Reballot Events Map (static site)

## What this is
A GitHub Pages site that shows:
- A UK map with a dot per event location (hover to see events there).
- Region tabs that filter the list of events.

The website itself is independent/static, but it **updates automatically whenever the Excel spreadsheet is updated in the repo**.

## How the auto-update works
1. You keep `events.xlsx` in the repo root.
2. When you update the spreadsheet and push to `main`, GitHub Actions runs `build.py`.
3. `build.py`:
   - Reads every sheet (each sheet = a region)
   - Geocodes event locations (cached in `.geocode_cache.json`)
   - Writes `docs/data/events.json`
4. GitHub Pages serves `docs/` so the site updates on the next refresh.

## Setup (copy/paste steps)
1. Create a new GitHub repo (public is easiest for Pages).
2. Copy everything from this folder into the repo.
3. Rename your spreadsheet to **events.xlsx** and put it in the repo root.
4. Commit + push to `main`.
5. In GitHub:
   - Settings → Pages
   - Build and deployment → Source: **Deploy from a branch**
   - Branch: **main** / Folder: **/docs**
6. Wait for the Actions workflow to run (tab: Actions).
7. Open the Pages URL.

## Important note about geocoding
Geocoding uses OpenStreetMap Nominatim.
- The workflow sets a User-Agent; you should replace the email in `.github/workflows/deploy.yml` with one you control.
- Geocoding is cached. If a location name changes, delete the corresponding entry in `.geocode_cache.json` and re-run.

## Data format
The site reads `docs/data/events.json` which includes:
- meta.generated_at (UTC)
- events[]: region, date, start_time, location, event_type, notes, lead, lat, lon
