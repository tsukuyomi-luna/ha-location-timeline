"""Pure timeline logic: segmentation, merging, clipping and summary.

This module must not import Home Assistant; it only uses the standard library
so that it can be tested in isolation.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, time, timedelta
from enum import Enum
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

type Resolver = Callable[[float, float, str | None], tuple[str | None, str | None]]
type Segment = dict[str, Any]
type Point = dict[str, Any]

GOOGLE_SOURCE = "google-timeline"

# 推定のパラメータ
MAX_POINT_ACC_M = 200.0
STAY_RADIUS_M = 80.0
STAY_MIN_S = 5 * 60
MOVE_MIN_S = 60
MOVE_MIN_DIST_M = 50.0
MERGE_RADIUS_M = 150.0
GAP_MIN_S = 10 * 60
# 疎な記録（iOS の significant モード）: 次の点まで長く空き、その間ほとんど動いていなければ滞在
DWELL_MIN_GAP_S = 10 * 60
DWELL_MAX_SPEED_MS = 0.5
DWELL_WALK_SPEED_MS = 1.25
# 速度による移動手段の分類。上位の速度は、レッグ（隣り合う点の間）の速度を
# 所要時間で重み付けした分位点
SPEED_TOP_QUANTILE = 0.9
WALK_MAX_AVG_KMH = 6.5
WALK_MAX_TOP_KMH = 9.0
# 上位の速度か、点が持つ端末報告速度 vel の最大値がこれ以上なら乗り物
VEHICLE_MIN_KMH = 25.0

GOOGLE_MODE_MAP: Mapping[str, str] = {
    "walking": "walk",
    "running": "run",
    "cycling": "bicycle",
    "in passenger vehicle": "car",
    "in taxi": "car",
    "in bus": "bus",
    "in train": "train",
    "in subway": "subway",
    "in tram": "train",
    "flying": "plane",
    "in ferry": "vehicle",
    "motorcycling": "car",
}

MOTION_MODE_MAP: Mapping[str, str] = {
    "walking": "walk",
    "running": "run",
    "cycling": "bicycle",
    "automotive": "vehicle",
}


# --------------------------------------------------------------------------
# 基本ユーティリティ
# --------------------------------------------------------------------------


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    r = 6371008.8
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def path_length_m(path: Sequence[Sequence[float]]) -> float:
    """Length of a polyline given as [[lat, lon, ...], ...]."""
    return sum(haversine_m(a[0], a[1], b[0], b[1]) for a, b in pairwise(path))


def google_mode(activity_type: str | None) -> str:
    """Map a Google Timeline activity type to our mode vocabulary."""
    if not activity_type:
        return "unknown"
    return GOOGLE_MODE_MAP.get(activity_type.strip().lower(), "unknown")


def day_bounds(day: date, tz_name: str) -> tuple[int, int]:
    """Return [start, end) epoch seconds of a calendar day in the given time zone."""
    tz = ZoneInfo(tz_name)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return int(start.timestamp()), int(end.timestamp())


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def normalize_points(raw: Iterable[Any]) -> list[Point]:
    """Validate, sort by tst and drop duplicate timestamps.

    Invalid entries (non-dict, missing/invalid lat/lon/tst) are skipped.
    """
    by_tst: dict[int, Point] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        lat = _num(item.get("lat"))
        lon = _num(item.get("lon"))
        tst = _num(item.get("tst"))
        if lat is None or lon is None or tst is None:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        p = dict(item)
        p["lat"], p["lon"], p["tst"] = lat, lon, int(tst)
        p["acc"] = _num(item.get("acc"))
        by_tst.setdefault(p["tst"], p)
    return [by_tst[k] for k in sorted(by_tst)]


def is_google_point(p: Point) -> bool:
    return p.get("source") == GOOGLE_SOURCE


def measured_points(points: Iterable[Point], coverage_end: int | None) -> list[Point]:
    """Points used for inference: non-Google, after sidecar coverage, acc <= 200 m."""
    out = []
    for p in points:
        if is_google_point(p):
            continue
        if coverage_end is not None and p["tst"] <= coverage_end:
            continue
        acc = p.get("acc")
        if acc is not None and acc > MAX_POINT_ACC_M:
            continue
        out.append(p)
    return out


def _weight(p: Point) -> float:
    acc = p.get("acc")
    acc = 10.0 if acc is None else max(float(acc), 5.0)
    return 1.0 / (acc * acc)


def weighted_centroid(points: Sequence[Point]) -> tuple[float, float]:
    """Accuracy-weighted centroid of points."""
    wsum = lat = lon = 0.0
    for p in points:
        w = _weight(p)
        wsum += w
        lat += p["lat"] * w
        lon += p["lon"] * w
    return lat / wsum, lon / wsum


def parse_sidecar(data: Any) -> dict[str, Any] | None:
    """Validate a loaded sidecar JSON document; invalid segments are dropped."""
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        return None
    segments = []
    for seg in data["segments"]:
        if not isinstance(seg, dict) or seg.get("t") not in ("visit", "activity"):
            continue
        s, e = _num(seg.get("s")), _num(seg.get("e"))
        if s is None or e is None or e < s:
            continue
        if seg["t"] == "visit" and (_num(seg.get("lat")) is None or _num(seg.get("lon")) is None):
            continue
        segments.append({**seg, "s": int(s), "e": int(e)})
    segments.sort(key=lambda x: (x["s"], x["e"]))
    coverage_end = _num(data.get("coverage_end"))
    if coverage_end is None and segments:
        coverage_end = max(x["e"] for x in segments)
    coverage_start = _num(data.get("coverage_start"))
    if coverage_start is None and segments:
        coverage_start = segments[0]["s"]
    return {
        "coverage_start": None if coverage_start is None else int(coverage_start),
        "coverage_end": None if coverage_end is None else int(coverage_end),
        "segments": segments,
    }


def parse_places(data: Any) -> list[dict[str, Any]]:
    """Validate places_file content: [{"name", "lat", "lon", "radius"}]."""
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        lat, lon = _num(item.get("lat")), _num(item.get("lon"))
        if lat is None or lon is None:
            continue
        radius = _num(item.get("radius"))
        radius = 100.0 if radius is None else radius
        out.append({"name": item["name"], "lat": lat, "lon": lon, "radius": radius})
    return out


def nearest_named(lat: float, lon: float, places: Iterable[Mapping[str, Any]]) -> str | None:
    """Name of the nearest place whose radius contains (lat, lon)."""
    best: tuple[float, str] | None = None
    for p in places:
        d = haversine_m(lat, lon, p["lat"], p["lon"])
        if d <= p["radius"] and (best is None or d < best[0]):
            best = (d, p["name"])
    return best[1] if best else None


SEMANTIC_NAMES: Mapping[str, str] = {"Home": "自宅", "Work": "職場"}


# --------------------------------------------------------------------------
# Google (sidecar) 区間
# --------------------------------------------------------------------------


def _overlaps(s: float, e: float, start: float, end: float) -> bool:
    if s == e:
        return start <= s < end
    return s < end and e > start


def google_path(seg: Mapping[str, Any], points: Sequence[Point]) -> list[list[float]]:
    """Activity start + Google path points inside [s, e] + activity end."""
    s, e = seg["s"], seg["e"]
    path: list[list[float]] = []
    if _num(seg.get("slat")) is not None and _num(seg.get("slon")) is not None:
        path.append([seg["slat"], seg["slon"], s])
    path.extend(
        [p["lat"], p["lon"], p["tst"]]
        for p in points
        if is_google_point(p) and p.get("gtype") == "path" and s <= p["tst"] <= e
    )
    if _num(seg.get("elat")) is not None and _num(seg.get("elon")) is not None:
        path.append([seg["elat"], seg["elon"], e])
    return path


def google_segments(
    sidecar: Sequence[Mapping[str, Any]],
    points: Sequence[Point],
    day_start: int,
    day_end: int,
    resolve: Resolver,
) -> list[Segment]:
    """Convert sidecar segments overlapping the day into stay/move segments (unclipped)."""
    visits0 = []
    visits1 = []
    out: list[Segment] = []
    for seg in sidecar:
        if not _overlaps(seg["s"], seg["e"], day_start, day_end):
            continue
        if seg.get("t") == "visit":
            (visits1 if seg.get("lvl", 0) else visits0).append(seg)
        elif seg.get("t") == "activity":
            path = google_path(seg, points)
            dist = _num(seg.get("dist"))
            out.append(
                {
                    "type": "move",
                    "start": seg["s"],
                    "end": seg["e"],
                    "mode": google_mode(seg.get("mode")),
                    "distance_m": dist if dist is not None else path_length_m(path),
                    "path": path,
                    "source": "google",
                    "mode_inferred": False,
                }
            )
    for v in visits0:
        name, area = resolve(v["lat"], v["lon"], v.get("sem"))
        children = []
        for c in visits1:
            if c["s"] < v["e"] and c["e"] > v["s"]:
                cname, carea = resolve(c["lat"], c["lon"], c.get("sem"))
                children.append(
                    {
                        "start": c["s"],
                        "end": c["e"],
                        "lat": c["lat"],
                        "lon": c["lon"],
                        "name": cname,
                        "area": carea,
                    }
                )
        children.sort(key=lambda c: c["start"])
        out.append(
            {
                "type": "stay",
                "start": v["s"],
                "end": v["e"],
                "ongoing": False,
                "lat": v["lat"],
                "lon": v["lon"],
                "name": name,
                "area": area,
                "source": "google",
                "children": children,
            }
        )
    out.sort(key=lambda s: (s["start"], s["end"]))
    return out


# --------------------------------------------------------------------------
# 実測点からの推定
# --------------------------------------------------------------------------


def detect_clusters(points: Sequence[Point]) -> list[list[Point]]:
    """Split a time-ordered point list into consecutive spatial clusters.

    A point joins the current cluster while it lies within max(80 m, acc) of the
    cluster's weighted centroid (the anchor).
    """
    clusters: list[list[Point]] = []
    current: list[Point] = []
    anchor: tuple[float, float] | None = None
    for p in points:
        if anchor is not None:
            radius = max(STAY_RADIUS_M, p.get("acc") or 0.0)
            if haversine_m(anchor[0], anchor[1], p["lat"], p["lon"]) <= radius:
                current.append(p)
                anchor = weighted_centroid(current)
                continue
            clusters.append(current)
        current = [p]
        anchor = (p["lat"], p["lon"])
    if current:
        clusters.append(current)
    return clusters


class SpeedClass(Enum):
    """How a move's speed compares with walking and with vehicles."""

    WALK = "walk"
    VEHICLE = "vehicle"
    # 徒歩には速すぎるが、乗り物と断定できない（自転車やランニングもありうる）
    FAST = "fast"


def _time_weighted_quantile(legs: Sequence[tuple[float, float]], q: float) -> float:
    """Quantile of leg speeds, each leg weighted by its duration.

    ``legs`` holds (speed, duration) pairs with positive durations.
    """
    ordered = sorted(legs)
    target = q * sum(dt for _, dt in ordered)
    acc = 0.0
    for speed, dt in ordered:
        acc += dt
        if acc >= target:
            return speed
    return ordered[-1][0]


def classify_speed(
    move_points: Sequence[Point], path: Sequence[Sequence[float]]
) -> SpeedClass | None:
    """Classify a move by speed; None when the path has no duration.

    The device-reported ``vel`` (km/h) only marks a move as a vehicle. It never
    makes a move non-walking, so that a momentary GPS outlier cannot break a walk.
    """
    if len(path) < 2:
        return None
    duration = path[-1][2] - path[0][2]
    if duration <= 0:
        return None
    avg_kmh = path_length_m(path) / duration * 3.6
    legs = [
        (haversine_m(a[0], a[1], b[0], b[1]) / (b[2] - a[2]) * 3.6, b[2] - a[2])
        for a, b in pairwise(path)
        if b[2] > a[2]
    ]
    top_kmh = _time_weighted_quantile(legs, SPEED_TOP_QUANTILE)
    if avg_kmh < WALK_MAX_AVG_KMH and top_kmh < WALK_MAX_TOP_KMH:
        return SpeedClass.WALK
    vels = [v for p in move_points if (v := _num(p.get("vel"))) is not None]
    if top_kmh >= VEHICLE_MIN_KMH or max(vels, default=0.0) >= VEHICLE_MIN_KMH:
        return SpeedClass.VEHICLE
    return SpeedClass.FAST


def infer_mode(move_points: Sequence[Point], path: Sequence[Sequence[float]]) -> str:
    """Infer the travel mode from motion activities checked against speed.

    Walking votes count only when the speed is walk-like. Without remaining
    votes, the speed class decides.
    """
    speed = classify_speed(move_points, path)
    walk_rejected = speed is not None and speed is not SpeedClass.WALK
    votes: Counter[str] = Counter()
    walking_dropped = False
    for p in move_points:
        acts = p.get("motionactivities")
        if not isinstance(acts, list):
            continue
        for a in acts:
            mode = MOTION_MODE_MAP.get(a) if isinstance(a, str) else None
            if mode == "walk" and walk_rejected:
                walking_dropped = True
            elif mode:
                votes[mode] += 1
    if votes:
        return votes.most_common(1)[0][0]

    match speed:
        case SpeedClass.WALK:
            return "walk"
        case SpeedClass.VEHICLE:
            return "vehicle"
        case SpeedClass.FAST if walking_dropped:
            # 端末は動作を記録していたのに、running も cycling も報告していない
            return "vehicle"
        case _:
            return "unknown"


def dwell_end(cluster: Sequence[Point], nxt: Point) -> int | None:
    """End time of a stay implied by a long, almost motionless gap before the next point.

    In sparse recordings a stay may be a single point followed, much later, by a
    point some hundred metres away (the device only reports once it has moved).
    Returns None when the gap does not look like a stay.
    """
    last = cluster[-1]
    gap = nxt["tst"] - last["tst"]
    if gap < DWELL_MIN_GAP_S:
        return None
    lat, lon = weighted_centroid(cluster)
    dist = haversine_m(lat, lon, nxt["lat"], nxt["lon"])
    if dist / gap >= DWELL_MAX_SPEED_MS:
        return None
    return int(nxt["tst"] - min(gap, dist / DWELL_WALK_SPEED_MS))


def _make_stay(
    cluster: Sequence[Point], resolve: Resolver, ongoing: bool, end: int | None = None
) -> Segment:
    lat, lon = weighted_centroid(cluster)
    name, area = resolve(lat, lon, None)
    return {
        "type": "stay",
        "start": cluster[0]["tst"],
        "end": cluster[-1]["tst"] if end is None else end,
        "ongoing": ongoing,
        "lat": lat,
        "lon": lon,
        "name": name,
        "area": area,
        "source": "owntracks",
        "children": [],
    }


def _make_move(
    start: int,
    end: int,
    mid: Sequence[Point],
    head: Segment | None,
    tail: Segment | None,
) -> Segment:
    path: list[list[float]] = []
    if head is not None:
        path.append([head["lat"], head["lon"], start])
    path.extend([p["lat"], p["lon"], p["tst"]] for p in mid)
    if tail is not None:
        path.append([tail["lat"], tail["lon"], end])
    return {
        "type": "move",
        "start": start,
        "end": end,
        "mode": infer_mode(mid, path),
        "distance_m": path_length_m(path),
        "path": path,
        "source": "owntracks",
        "mode_inferred": True,
    }


def _is_trivial_move(move: Segment) -> bool:
    return move["end"] - move["start"] < MOVE_MIN_S or move["distance_m"] < MOVE_MIN_DIST_M


def infer_segments(points: Sequence[Point], resolve: Resolver, is_today: bool) -> list[Segment]:
    """Infer stay/move segments from measured points (unclipped)."""
    if not points:
        return []
    clusters = detect_clusters(points)
    ends = [
        dwell_end(c, clusters[i + 1][0]) if i + 1 < len(clusters) else None
        for i, c in enumerate(clusters)
    ]
    flags = [
        (e if e is not None else c[-1]["tst"]) - c[0]["tst"] >= STAY_MIN_S
        for c, e in zip(clusters, ends, strict=True)
    ]
    if is_today:
        # 最新点を含む最後のクラスタは短くても滞在中とみなす
        flags[-1] = True

    out: list[Segment] = []
    prev_stay: Segment | None = None
    pending: list[Point] = []
    for i, (cluster, is_stay) in enumerate(zip(clusters, flags, strict=True)):
        if not is_stay:
            pending.extend(cluster)
            continue
        stay = _make_stay(
            cluster, resolve, ongoing=is_today and i == len(clusters) - 1, end=ends[i]
        )
        if prev_stay is not None:
            move = _make_move(prev_stay["end"], stay["start"], pending, prev_stay, stay)
            if not _is_trivial_move(move):
                out.append(move)
        elif len(pending) >= 1:
            move = _make_move(pending[0]["tst"], stay["start"], pending, None, stay)
            if not _is_trivial_move(move):
                out.append(move)
        out.append(stay)
        prev_stay = stay
        pending = []
    if pending:
        if prev_stay is not None:
            move = _make_move(prev_stay["end"], pending[-1]["tst"], pending, prev_stay, None)
        else:
            move = _make_move(pending[0]["tst"], pending[-1]["tst"], pending, None, None)
        if not _is_trivial_move(move):
            out.append(move)
    return out


# --------------------------------------------------------------------------
# 結合・クリップ・gap・要約
# --------------------------------------------------------------------------


def merge_stays(segments: Sequence[Segment]) -> list[Segment]:
    """Merge consecutive stays at the same place (<= 150 m) with no move between them."""
    out: list[Segment] = []
    for seg in sorted(segments, key=lambda s: (s["start"], s["end"])):
        prev = out[-1] if out else None
        if (
            prev is not None
            and seg["type"] == "stay"
            and prev["type"] == "stay"
            and haversine_m(prev["lat"], prev["lon"], seg["lat"], seg["lon"]) <= MERGE_RADIUS_M
        ):
            merged = dict(prev)
            merged["start"] = min(prev["start"], seg["start"])
            merged["end"] = max(prev["end"], seg["end"])
            merged["ongoing"] = seg["ongoing"]
            merged["source"] = seg["source"]
            merged["name"] = prev["name"] or seg["name"]
            merged["area"] = prev["area"] or seg["area"]
            merged["children"] = [*prev["children"], *seg["children"]]
            out[-1] = merged
            continue
        out.append(dict(seg))
    return out


def clip_segments(segments: Sequence[Segment], day_start: int, day_end: int) -> list[Segment]:
    """Keep segments overlapping [day_start, day_end) and clip their times."""
    out = []
    for seg in segments:
        s, e = seg["start"], seg["end"]
        if not _overlaps(s, e, day_start, day_end):
            continue
        c = dict(seg)
        c["orig_start"], c["orig_end"] = s, e
        c["start_clipped"] = s < day_start
        c["end_clipped"] = e > day_end
        c["start"] = max(s, day_start)
        c["end"] = min(e, day_end)
        if c["type"] == "stay":
            c["children"] = [
                {**ch, "start": max(ch["start"], day_start), "end": min(ch["end"], day_end)}
                for ch in seg.get("children", [])
                if _overlaps(ch["start"], ch["end"], day_start, day_end)
            ]
        out.append(c)
    return out


def insert_gaps(
    segments: Sequence[Segment], day_start: int, day_end: int, now: int
) -> list[Segment]:
    """Insert gap segments for holes of >= 10 minutes (never in the future)."""
    limit = min(day_end, now)
    out: list[Segment] = []
    cursor = day_start
    for seg in segments:
        gap_end = min(seg["start"], limit)
        if gap_end - cursor >= GAP_MIN_S:
            out.append({"type": "gap", "start": cursor, "end": gap_end})
        out.append(seg)
        cursor = max(cursor, seg["end"])
    last = segments[-1] if segments else None
    ongoing = last is not None and last["type"] == "stay" and last.get("ongoing")
    if not ongoing and limit - cursor >= GAP_MIN_S:
        out.append({"type": "gap", "start": cursor, "end": limit})
    return out


def summarize(segments: Sequence[Segment], point_count: int) -> dict[str, Any]:
    distance: dict[str, float] = {}
    move_seconds = 0
    stay_count = 0
    for seg in segments:
        if seg["type"] == "move":
            distance[seg["mode"]] = distance.get(seg["mode"], 0) + seg["distance_m"]
            move_seconds += seg["end"] - seg["start"]
        elif seg["type"] == "stay":
            stay_count += 1
    return {
        "distance_m": {k: round(v) for k, v in distance.items()},
        "move_seconds": move_seconds,
        "stay_count": stay_count,
        "point_count": point_count,
    }


def compute_bounds(
    segments: Sequence[Segment], points: Sequence[Sequence[float]]
) -> list[list[float]] | None:
    coords: list[tuple[float, float]] = []
    for seg in segments:
        if seg["type"] == "stay":
            coords.append((seg["lat"], seg["lon"]))
        elif seg["type"] == "move":
            coords.extend((p[0], p[1]) for p in seg["path"])
    coords.extend((p[0], p[1]) for p in points)
    if not coords:
        return None
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def _finalize(seg: Segment) -> Segment:
    if seg["type"] == "move":
        seg["distance_m"] = round(seg["distance_m"])
    return seg


def build_day(
    *,
    day: date,
    tz_name: str,
    raw_points: Iterable[Any],
    sidecar: Mapping[str, Any] | None,
    resolve: Resolver,
    now: int,
) -> dict[str, Any]:
    """Build the JSON-serialisable timeline for one calendar day."""
    day_start, day_end = day_bounds(day, tz_name)
    points = normalize_points(raw_points)
    sidecar_segments = list(sidecar.get("segments", [])) if sidecar else []
    coverage_end = sidecar.get("coverage_end") if sidecar else None

    segs = google_segments(sidecar_segments, points, day_start, day_end, resolve)
    is_today = day_start <= now < day_end
    segs.extend(infer_segments(measured_points(points, coverage_end), resolve, is_today))
    segs = merge_stays(segs)
    segs = [_finalize(s) for s in clip_segments(segs, day_start, day_end)]
    segs = insert_gaps(segs, day_start, day_end, now)

    day_points = [
        [p["lat"], p["lon"], p["tst"], p.get("acc")]
        for p in points
        if day_start <= p["tst"] < day_end
    ]
    return {
        "date": day.isoformat(),
        "tz": tz_name,
        "day_start": day_start,
        "day_end": day_end,
        "now": now,
        "segments": segs,
        "points": day_points,
        "summary": summarize(segs, len(day_points)),
        "bounds": compute_bounds(segs, day_points),
    }
