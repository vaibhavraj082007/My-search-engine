"""Importer: New Zealand traffic cameras from NZTA."""

import httpx

import sys
import os

try:
    from .. import camdb
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from backend import camdb

NAME = "newzealand"
URL = "https://www.journeys.nzta.govt.nz/assets/traffic/cameras/camera-list.json"
CREDIT = "NZTA / nzta.govt.nz"


def run() -> int:
    """Fetch and import New Zealand traffic cameras. Returns count imported."""
    print(f"📡 [{NAME}] Fetching {URL} …")

    headers = {
        "User-Agent": "8search/1.0",
        "Accept": "application/json",
    }
    resp = httpx.get(URL, timeout=30.0, headers=headers, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()

    cameras = data if isinstance(data, list) else data.get("cameras", data.get("features", []))
    count = 0

    for cam in cameras:
        try:
            # Handle GeoJSON features or flat objects
            if "properties" in cam and "geometry" in cam:
                props = cam["properties"]
                coords = cam["geometry"].get("coordinates", [])
                lon = float(coords[0]) if len(coords) > 0 else None
                lat = float(coords[1]) if len(coords) > 1 else None
            else:
                props = cam
                lat = cam.get("lat") or cam.get("latitude")
                lon = cam.get("lon") or cam.get("lng") or cam.get("longitude")

            if lat is None or lon is None:
                continue
            lat = float(lat)
            lon = float(lon)

            ext_id = str(
                props.get("id")
                or props.get("cameraId")
                or props.get("camera_id")
                or ""
            )
            if not ext_id:
                continue

            name = props.get("name") or props.get("description") or props.get("title", "")
            image_url = (
                props.get("imageUrl")
                or props.get("image_url")
                or props.get("url")
                or props.get("stillUrl")
                or ""
            )

            if not image_url:
                continue

            # Make sure URL is absolute
            if image_url.startswith("//"):
                image_url = "https:" + image_url
            elif not image_url.startswith("http"):
                image_url = "https://www.journeys.nzta.govt.nz" + image_url

            cam_type = "image"
            if any(ext in image_url.lower() for ext in (".m3u8", ".mp4", "stream")):
                cam_type = "video"

            if camdb.insert_camera(NAME, ext_id, name, lat, lon, image_url, cam_type, CREDIT):
                count += 1

        except (ValueError, TypeError, KeyError):
            continue

    print(f"  ✅ [{NAME}] Imported {count} cameras")
    return count
