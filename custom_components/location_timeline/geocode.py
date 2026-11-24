"""Reverse geocoding against a local town (町丁目) sqlite database.

Standard library only; must not import Home Assistant. All methods are
synchronous and thread-safe (a new read-only connection per query).
"""

from __future__ import annotations

import math
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

MAX_DISTANCE_M = 1500.0
CACHE_SIZE = 4096

SCHEMA = """
CREATE TABLE IF NOT EXISTS towns (
    cell INTEGER NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    pref TEXT NOT NULL,
    city TEXT NOT NULL,
    town TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS towns_cell ON towns(cell);
"""


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def cell_xy(lat: float, lon: float) -> tuple[int, int]:
    return math.floor((lat + 90) * 100), math.floor((lon + 180) * 100)


def cell_id(lat: float, lon: float) -> int:
    """0.01 degree grid cell id."""
    y, x = cell_xy(lat, lon)
    return y * 100000 + x


def area_name(result: dict[str, Any] | None) -> str | None:
    """Display name for a lookup result: city + town (prefecture omitted)."""
    if not result:
        return None
    name = f"{result['city']}{result['town']}"
    return name or None


class TownGeocoder:
    """Nearest-town lookup backed by a sqlite database built by build_towns_db.py."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple[float, float], dict[str, Any] | None] = OrderedDict()

    @property
    def available(self) -> bool:
        return self._path.is_file()

    def lookup(self, lat: float, lon: float) -> dict[str, Any] | None:
        """Return {"pref","city","town","distance_m"} of the nearest town, or None."""
        key = (round(lat, 4), round(lon, 4))
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        result = self._query(lat, lon)
        with self._lock:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return result

    def _query(self, lat: float, lon: float) -> dict[str, Any] | None:
        if not self.available:
            return None
        try:
            conn = sqlite3.connect(f"{self._path.resolve().as_uri()}?mode=ro", uri=True)
        except sqlite3.Error:
            return None
        try:
            for radius in (1, 2):
                rows = conn.execute(
                    f"SELECT lat, lon, pref, city, town FROM towns WHERE cell IN "
                    f"({','.join('?' * ((2 * radius + 1) ** 2))})",
                    _neighbour_cells(lat, lon, radius),
                ).fetchall()
                if rows:
                    break
        except sqlite3.Error:
            return None
        finally:
            conn.close()
        if not rows:
            return None
        best = min(rows, key=lambda r: haversine_m(lat, lon, r[0], r[1]))
        dist = haversine_m(lat, lon, best[0], best[1])
        if dist > MAX_DISTANCE_M:
            return None
        return {"pref": best[2], "city": best[3], "town": best[4], "distance_m": round(dist, 1)}


def _neighbour_cells(lat: float, lon: float, radius: int) -> list[int]:
    y, x = cell_xy(lat, lon)
    return [
        (y + dy) * 100000 + (x + dx)
        for dy in range(-radius, radius + 1)
        for dx in range(-radius, radius + 1)
    ]
