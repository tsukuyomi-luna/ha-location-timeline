#!/usr/bin/env python3
"""geolonia japanese-addresses の latest.csv から towns.sqlite を作る。

使い方: build_towns_db.py latest.csv towns.sqlite
"""

from __future__ import annotations

import argparse
import csv
import math
import sqlite3
import sys
from pathlib import Path

SCHEMA = """
CREATE TABLE towns (
    cell INTEGER NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    pref TEXT NOT NULL,
    city TEXT NOT NULL,
    town TEXT NOT NULL
);
"""
INDEX = "CREATE INDEX towns_cell ON towns(cell);"

COL_PREF = "都道府県名"
COL_CITY = "市区町村名"
COL_TOWN = "大字町丁目名"
COL_LAT = "緯度"
COL_LON = "経度"


def cell_id(lat: float, lon: float) -> int:
    return math.floor((lat + 90) * 100) * 100000 + math.floor((lon + 180) * 100)


def parse_row(row: dict[str, str]) -> tuple[int, float, float, str, str, str] | None:
    try:
        lat = float((row.get(COL_LAT) or "").strip())
        lon = float((row.get(COL_LON) or "").strip())
    except ValueError:
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    pref = (row.get(COL_PREF) or "").strip()
    city = (row.get(COL_CITY) or "").strip()
    town = (row.get(COL_TOWN) or "").strip()
    return cell_id(lat, lon), lat, lon, pref, city, town


def build(csv_path: Path, out_path: Path) -> int:
    """Build the database. Returns the number of inserted rows."""
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    count = 0
    try:
        conn.executescript(SCHEMA)
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            missing = {COL_LAT, COL_LON, COL_CITY, COL_TOWN} - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"CSV に必要な列がありません: {sorted(missing)}")
            batch = []
            for row in reader:
                parsed = parse_row(row)
                if parsed is None:
                    continue
                batch.append(parsed)
                if len(batch) >= 10000:
                    conn.executemany("INSERT INTO towns VALUES (?,?,?,?,?,?)", batch)
                    count += len(batch)
                    batch.clear()
            conn.executemany("INSERT INTO towns VALUES (?,?,?,?,?,?)", batch)
            count += len(batch)
        conn.execute(INDEX)
        conn.commit()
    finally:
        conn.close()
    tmp.replace(out_path)
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    count = build(args.csv, args.out)
    print(f"{count} rows -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
