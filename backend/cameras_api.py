"""Cameras API – query cameras by bounding box and get stats."""

from fastapi import APIRouter, Query

from . import camdb

router = APIRouter()


@router.get("/api/cameras")
def cameras(
    north: float = Query(..., ge=-90, le=90),
    south: float = Query(..., ge=-90, le=90),
    east: float = Query(..., ge=-180, le=180),
    west: float = Query(..., ge=-180, le=180),
):
    results = camdb.get_cameras_in_bounds(north, south, east, west)
    return results


@router.get("/api/stats")
def stats():
    return camdb.get_stats()
