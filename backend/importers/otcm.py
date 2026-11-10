"""Importer: OpenTrafficCamMap (USA cameras)."""

import httpx

import sys
import os

try:
    from .. import camdb
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from backend import camdb

NAME = "otcm"
URL = "https://raw.githubusercontent.com/AidanWelch/OpenTrafficCamMap/main/cameras/USA.json"
CREDIT = "OpenTrafficCamMap (MIT) / State DOT"


def run() -> int:
    """Fetch and import OTCM USA cameras. Returns count of cameras imported."""
    print(f"📡 [{NAME}] Fetching {URL} …")
    resp = httpx.get(URL, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()

    count = 0
    for cam in data:
        try:
            ext_id = str(cam.get("id", cam.get("cameraId", "")))
            if not ext_id:
                continue

            lat = cam.get("lat") or cam.get("latitude")
            lon = cam.get("lon") or cam.get("longitude") or cam.get("lng")
            if lat is None or lon is None:
                continue
            lat = float(lat)
            lon = float(lon)

            name = cam.get("name") or cam.get("description") or cam.get("title")
            cam_url = cam.get("url") or cam.get("imageUrl") or cam.get("image_url")
            if not cam_url:
                continue

            # Determine type
            cam_type = "image"
            url_lower = cam_url.lower()
            if any(ext in url_lower for ext in (".m3u8", ".mp4", ".flv", "video", "stream")):
                cam_type = "video"
            raw_type = str(cam.get("type", "")).lower()
            if "video" in raw_type or "stream" in raw_type:
                cam_type = "video"

            if camdb.insert_camera(NAME, ext_id, name, lat, lon, cam_url, cam_type, CREDIT):
                count += 1

        except (ValueError, TypeError, KeyError):
            continue

    print(f"  ✅ [{NAME}] Imported {count} cameras")
    return count
