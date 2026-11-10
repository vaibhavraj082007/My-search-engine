"""Importer: Hong Kong traffic cameras from data.gov.hk."""

import httpx

import sys
import os

try:
    from .. import camdb
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from backend import camdb

NAME = "hongkong"
URL = "https://resource.data.one.gov.hk/td/trafficsnapshots.json"
IMAGE_BASE = "https://tdcctv.data.one.gov.hk/"
CREDIT = "Hong Kong Transport Department / data.gov.hk"


def run() -> int:
    """Fetch and import Hong Kong traffic cameras. Returns count imported."""
    print(f"📡 [{NAME}] Fetching {URL} …")

    headers = {
        "User-Agent": "8search/1.0",
        "Accept": "application/json",
    }
    resp = httpx.get(URL, timeout=30.0, headers=headers, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()

    # The HK API returns a list of camera snapshots
    cameras = data if isinstance(data, list) else data.get("cameras", data.get("features", []))
    count = 0

    for cam in cameras:
        try:
            ext_id = str(cam.get("key", cam.get("id", cam.get("cameraId", ""))))
            if not ext_id:
                continue

            lat = cam.get("latitude") or cam.get("lat")
            lon = cam.get("longitude") or cam.get("lon") or cam.get("lng")
            if lat is None or lon is None:
                continue
            lat = float(lat)
            lon = float(lon)

            name = cam.get("description") or cam.get("name") or cam.get("district", "")

            # Build image URL
            image_url = cam.get("url") or cam.get("imageUrl") or cam.get("image", "")
            if not image_url:
                # Construct from key: {IMAGE_BASE}{key}.JPG
                image_url = f"{IMAGE_BASE}{ext_id}.JPG"

            if not image_url.startswith("http"):
                if image_url.startswith("//"):
                    image_url = "https:" + image_url
                else:
                    image_url = IMAGE_BASE + image_url

            region = cam.get("region", "")
            if region and name:
                name = f"{name} ({region})"

            if camdb.insert_camera(NAME, ext_id, name, lat, lon, image_url, "image", CREDIT):
                count += 1

        except (ValueError, TypeError, KeyError):
            continue

    print(f"  ✅ [{NAME}] Imported {count} cameras")
    return count
