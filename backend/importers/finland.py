"""Importer: Finnish traffic cameras from Fintraffic / digitraffic.fi."""

import httpx

import sys
import os

try:
    from .. import camdb
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from backend import camdb

NAME = "finland"
URL = "https://tie.digitraffic.fi/api/weathercam/v1/stations"
CREDIT = "Fintraffic / digitraffic.fi (CC BY 4.0)"


def run() -> int:
    """Fetch and import Finnish weather cameras. Returns count imported."""
    print(f"📡 [{NAME}] Fetching {URL} …")

    headers = {
        "Accept": "application/json",
        "Digitraffic-User": "8search/1.0",
    }
    resp = httpx.get(URL, timeout=30.0, headers=headers, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()

    stations = data.get("features", data) if isinstance(data, dict) else data
    count = 0

    for station in stations:
        try:
            props = station.get("properties", {})
            geometry = station.get("geometry", {})
            coords = geometry.get("coordinates", [])

            if len(coords) < 2:
                continue

            lon = float(coords[0])
            lat = float(coords[1])

            station_name = props.get("name") or props.get("names", {}).get("en", "")

            # Each station has presets (individual camera images)
            presets = props.get("presets", [])
            if not presets:
                continue

            for preset in presets:
                preset_id = preset.get("id", "")
                if not preset_id:
                    continue

                image_url = preset.get("imageUrl", "")
                if not image_url:
                    continue

                preset_name = preset.get("presentationName") or station_name
                ext_id = str(preset_id)

                if camdb.insert_camera(NAME, ext_id, preset_name, lat, lon, image_url, "image", CREDIT):
                    count += 1

        except (ValueError, TypeError, KeyError):
            continue

    print(f"  ✅ [{NAME}] Imported {count} cameras")
    return count
