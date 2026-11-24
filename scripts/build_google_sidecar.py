#!/usr/bin/env python3
"""Google Timeline.json (端末エクスポート形式) から sidecar JSON を作る。

使い方: build_google_sidecar.py Timeline.json OUT.json

入力は信頼できないデータとして扱い、想定外の型の要素はスキップする。
timelinePath 要素は出力しない（点は OwnTracks Recorder 側にある）。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_NUM = r"[-+]?\d+(?:\.\d+)?"
_GEO_RE = re.compile(rf"^\s*(?:geo:)?\s*({_NUM})\s*°?\s*,\s*({_NUM})\s*°?\s*$")


def parse_geo(value: Any) -> tuple[float, float] | None:
    """Parse "geo:35.1,139.1" or "35.1°, 139.1°" into (lat, lon)."""
    if not isinstance(value, str):
        return None
    m = _GEO_RE.match(value)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def parse_time(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return int(dt.timestamp())


def parse_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        f = float(value)
    elif isinstance(value, str):
        try:
            f = float(value)
        except ValueError:
            return None
    else:
        return None
    return f if math.isfinite(f) else None


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def convert_visit(s: int, e: int, visit: dict[str, Any]) -> dict[str, Any] | None:
    top = visit.get("topCandidate")
    if not isinstance(top, dict):
        return None
    loc = parse_geo(top.get("placeLocation"))
    if loc is None:
        return None
    level = parse_float(visit.get("hierarchyLevel"))
    seg: dict[str, Any] = {
        "t": "visit",
        "s": s,
        "e": e,
        "lat": loc[0],
        "lon": loc[1],
        "sem": _str_or_none(top.get("semanticType")),
        "lvl": int(level) if level is not None else 0,
        "pid": _str_or_none(top.get("placeID")),
    }
    return seg


def convert_activity(s: int, e: int, act: dict[str, Any]) -> dict[str, Any]:
    top = act.get("topCandidate")
    mode = _str_or_none(top.get("type")) if isinstance(top, dict) else None
    start = parse_geo(act.get("start"))
    end = parse_geo(act.get("end"))
    seg: dict[str, Any] = {
        "t": "activity",
        "s": s,
        "e": e,
        "mode": mode or "unknown",
        "dist": parse_float(act.get("distanceMeters")),
    }
    if start:
        seg["slat"], seg["slon"] = start
    if end:
        seg["elat"], seg["elon"] = end
    return seg


def convert(data: Any) -> dict[str, Any]:
    """Convert parsed Timeline.json content into the sidecar structure."""
    segments: list[dict[str, Any]] = []
    items = data if isinstance(data, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        s = parse_time(item.get("startTime"))
        e = parse_time(item.get("endTime"))
        if s is None or e is None or e < s:
            continue
        visit = item.get("visit")
        activity = item.get("activity")
        seg = None
        if isinstance(visit, dict):
            seg = convert_visit(s, e, visit)
        elif isinstance(activity, dict):
            seg = convert_activity(s, e, activity)
        if seg is not None:
            segments.append(seg)
    segments.sort(key=lambda x: (x["s"], x.get("lvl", 0), x["e"]))
    return {
        "version": 1,
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "coverage_start": min((x["s"] for x in segments), default=None),
        "coverage_end": max((x["e"] for x in segments), default=None),
        "segments": segments,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("timeline", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    with args.timeline.open(encoding="utf-8") as f:
        data = json.load(f)
    result = convert(data)
    tmp = args.out.with_suffix(args.out.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(args.out)
    print(f"{len(result['segments'])} segments -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
