from __future__ import annotations

from datetime import date

import lt_timeline as tl
import pytest

TZ = "Asia/Tokyo"
DAY = date(2026, 11, 20)
DAY_START, DAY_END = tl.day_bounds(DAY, TZ)
H = 3600
M = 60

HOME = (35.7138, 139.7773)  # Ueno Station
OFFICE = (35.6810, 139.7670)  # Tokyo Station, ~3.8 km from HOME


def offset(base: tuple[float, float], north_m: float = 0.0, east_m: float = 0.0):
    return base[0] + north_m / 111_320, base[1] + east_m / 90_400


def pt(tst: int, latlon: tuple[float, float], acc: float = 10, **extra):
    return {
        "_type": "location",
        "tst": tst,
        "lat": latlon[0],
        "lon": latlon[1],
        "acc": acc,
        **extra,
    }


def no_names(lat, lon, sem):
    return ({"Home": "自宅", "Work": "職場"}.get(sem or ""), None)


def build(points, sidecar=None, now=None, resolve=no_names):
    return tl.build_day(
        day=DAY,
        tz_name=TZ,
        raw_points=points,
        sidecar=tl.parse_sidecar(sidecar) if sidecar is not None else None,
        resolve=resolve,
        now=DAY_END + 30 * 24 * H if now is None else now,
    )


def kinds(result):
    return [s["type"] for s in result["segments"]]


def test_day_bounds_in_jst():
    assert DAY_END - DAY_START == 24 * H
    # 2026-11-20 00:00 JST == 2026-11-19 15:00 UTC
    assert DAY_START == 1795100400


def test_haversine_and_path_length():
    a = HOME
    b = offset(HOME, north_m=1000)
    assert tl.haversine_m(*a, *b) == pytest.approx(1000, rel=0.01)
    assert tl.path_length_m([[*a, 0], [*b, 1], [*a, 2]]) == pytest.approx(2000, rel=0.01)


def test_normalize_points_sorts_dedups_and_skips_invalid():
    pts = tl.normalize_points(
        [
            pt(20, HOME),
            pt(10, HOME),
            pt(10, OFFICE),
            {"tst": 30, "lat": "x", "lon": 1},
            "garbage",
            {"tst": 40, "lat": 91, "lon": 0},
        ]
    )
    assert [p["tst"] for p in pts] == [10, 20]


# ---------------------------------------------------------------- Google sidecar


def sidecar_doc(segments):
    return {
        "version": 1,
        "coverage_start": min(s["s"] for s in segments),
        "coverage_end": max(s["e"] for s in segments),
        "segments": segments,
    }


def test_google_segments_and_clip_across_midnight():
    t0 = DAY_START
    segs = [
        {
            "t": "visit",
            "s": t0 - 2 * H,
            "e": t0 + 8 * H,
            "lat": HOME[0],
            "lon": HOME[1],
            "sem": "Home",
            "lvl": 0,
            "pid": "a",
        },
        {
            "t": "activity",
            "s": t0 + 8 * H,
            "e": t0 + 9 * H,
            "mode": "in train",
            "dist": 3800.0,
            "slat": HOME[0],
            "slon": HOME[1],
            "elat": OFFICE[0],
            "elon": OFFICE[1],
        },
        {
            "t": "visit",
            "s": t0 + 9 * H,
            "e": t0 + 26 * H,
            "lat": OFFICE[0],
            "lon": OFFICE[1],
            "sem": "Work",
            "lvl": 0,
            "pid": "b",
        },
    ]
    path_pts = [
        pt(t0 + 8 * H + 20 * M, offset(HOME, 2000), source="google-timeline", gtype="path"),
        pt(t0 + 8 * H + 40 * M, offset(HOME, 4000), source="google-timeline", gtype="path"),
        pt(t0 + 8 * H + 30 * M, offset(HOME, 3000), source="google-timeline", gtype="visit"),
    ]
    r = build(path_pts, sidecar_doc(segs))
    assert kinds(r) == ["stay", "move", "stay"]
    home, move, office = r["segments"]

    assert home["start"] == DAY_START and home["start_clipped"] is True
    assert home["orig_start"] == t0 - 2 * H
    assert home["end_clipped"] is False and home["name"] == "自宅"
    assert home["source"] == "google"

    assert move["mode"] == "train" and move["mode_inferred"] is False
    assert move["distance_m"] == 3800
    assert len(move["path"]) == 4  # start + 2 path points + end
    assert move["path"][0][:2] == list(HOME) and move["path"][-1][:2] == list(OFFICE)

    assert office["end"] == DAY_END and office["end_clipped"] is True
    assert office["orig_end"] == t0 + 26 * H
    assert office["name"] == "職場"
    assert r["summary"]["distance_m"] == {"train": 3800}
    assert r["summary"]["stay_count"] == 2
    assert r["bounds"] is not None


def test_google_activity_without_distance_uses_path_length():
    t0 = DAY_START + 10 * H
    far = offset(HOME, 1000)
    segs = [
        {
            "t": "activity",
            "s": t0,
            "e": t0 + 15 * M,
            "mode": "walking",
            "slat": HOME[0],
            "slon": HOME[1],
            "elat": far[0],
            "elon": far[1],
        }
    ]
    r = build([], sidecar_doc(segs))
    move = next(s for s in r["segments"] if s["type"] == "move")
    assert move["mode"] == "walk"
    assert move["distance_m"] == pytest.approx(1000, abs=10)


@pytest.mark.parametrize(
    ("google", "mode"),
    [
        ("walking", "walk"),
        ("running", "run"),
        ("cycling", "bicycle"),
        ("in passenger vehicle", "car"),
        ("in taxi", "car"),
        ("in bus", "bus"),
        ("in train", "train"),
        ("in subway", "subway"),
        ("in tram", "train"),
        ("flying", "plane"),
        ("in ferry", "vehicle"),
        ("motorcycling", "car"),
        ("skiing", "unknown"),
        (None, "unknown"),
    ],
)
def test_google_mode_mapping(google, mode):
    assert tl.google_mode(google) == mode


def test_level1_visits_become_children():
    t0 = DAY_START + 10 * H
    shop = offset(OFFICE, 50)
    segs = [
        {"t": "visit", "s": t0, "e": t0 + 3 * H, "lat": OFFICE[0], "lon": OFFICE[1], "lvl": 0},
        {
            "t": "visit",
            "s": t0 + 30 * M,
            "e": t0 + H,
            "lat": shop[0],
            "lon": shop[1],
            "lvl": 1,
            "sem": "Unknown",
        },
        {"t": "visit", "s": t0 + 4 * H, "e": t0 + 5 * H, "lat": shop[0], "lon": shop[1], "lvl": 1},
    ]
    r = build([], sidecar_doc(segs))
    stays = [s for s in r["segments"] if s["type"] == "stay"]
    assert len(stays) == 1
    children = stays[0]["children"]
    assert len(children) == 1
    assert children[0]["start"] == t0 + 30 * M and children[0]["end"] == t0 + H


# ---------------------------------------------------------------- inference


def dense_commute(t0: int):
    """60 min at HOME (1/min), 20 min walk 1.5 km north, 60 min at destination."""
    pts = [pt(t0 + i * M, offset(HOME, (i % 3) * 5)) for i in range(61)]
    for i in range(1, 20):
        pts.append(pt(t0 + 60 * M + i * M, offset(HOME, 75 * i)))
    dest = offset(HOME, 1500)
    pts.extend(pt(t0 + 80 * M + i * M, offset(dest, 0, (i % 2) * 5)) for i in range(61))
    return pts, dest


def test_dense_points_stay_move_stay_with_walk_by_speed():
    t0 = DAY_START + 9 * H
    pts, dest = dense_commute(t0)
    r = build(pts)
    segs = [s for s in r["segments"] if s["type"] != "gap"]
    assert [s["type"] for s in segs] == ["stay", "move", "stay"]
    s1, mv, s2 = segs
    assert s1["source"] == "owntracks"
    # the first walking point (75 m away) may still be absorbed by the home cluster
    assert s1["start"] == t0 and t0 + 60 * M <= s1["end"] <= t0 + 61 * M
    assert mv["start"] == s1["end"] and mv["end"] == s2["start"]
    assert mv["mode"] == "walk" and mv["mode_inferred"] is True
    assert mv["distance_m"] == pytest.approx(1500, rel=0.05)
    assert mv["path"][0][:2] == [s1["lat"], s1["lon"]]
    assert mv["path"][-1][:2] == [s2["lat"], s2["lon"]]
    assert tl.haversine_m(s2["lat"], s2["lon"], *dest) < 20
    assert r["summary"]["point_count"] == len(pts)


def test_sparse_points_same_place_is_stay_and_jump_is_move():
    t0 = DAY_START + 8 * H
    pts = [
        pt(t0, HOME),
        pt(t0 + 2 * H, offset(HOME, 30)),
        pt(t0 + 2 * H + 9 * M, OFFICE),
        pt(t0 + 6 * H, offset(OFFICE, 0, 20)),
    ]
    r = build(pts)
    segs = [s for s in r["segments"] if s["type"] != "gap"]
    assert [s["type"] for s in segs] == ["stay", "move", "stay"]
    assert segs[0]["start"] == t0 and segs[0]["end"] == t0 + 2 * H
    move = segs[1]
    assert len(move["path"]) == 2
    assert move["start"] == t0 + 2 * H and move["end"] == t0 + 2 * H + 9 * M
    assert move["mode"] == "vehicle"  # ~25 km/h
    assert segs[2]["end"] == t0 + 6 * H


def test_short_cluster_is_part_of_move():
    t0 = DAY_START + 9 * H
    pts, _ = dense_commute(t0)
    # 3 minutes waiting at a traffic light in the middle of the walk
    light = offset(HOME, 750)
    pts = [p for p in pts if not (t0 + 69 * M <= p["tst"] <= t0 + 71 * M)]
    pts.extend(pt(t0 + 69 * M + i * 30, light) for i in range(7))
    r = build(pts)
    segs = [s for s in r["segments"] if s["type"] != "gap"]
    assert [s["type"] for s in segs] == ["stay", "move", "stay"]


def test_bad_accuracy_and_google_points_are_ignored_for_inference():
    t0 = DAY_START + 9 * H
    pts = [
        pt(t0, HOME),
        pt(t0 + 10 * M, OFFICE, acc=500),
        pt(t0 + 15 * M, OFFICE, source="google-timeline", gtype="path"),
        pt(t0 + 30 * M, HOME),
    ]
    r = build(pts)
    segs = [s for s in r["segments"] if s["type"] != "gap"]
    assert [s["type"] for s in segs] == ["stay"]
    assert segs[0]["start"] == t0 and segs[0]["end"] == t0 + 30 * M
    # raw points still include everything
    assert r["summary"]["point_count"] == 4


def test_trivial_move_is_dropped_and_stays_join():
    t0 = DAY_START + 9 * H
    # stay, then a point 90 m away 30 s later, then back near the first place
    pts = [pt(t0 + i * M, HOME) for i in range(10)]
    pts.append(pt(t0 + 9 * M + 30, offset(HOME, 90)))
    pts.extend(pt(t0 + 10 * M + i * M, offset(HOME, 30)) for i in range(10))
    r = build(pts)
    segs = [s for s in r["segments"] if s["type"] != "gap"]
    assert [s["type"] for s in segs] == ["stay"]
    assert segs[0]["start"] == t0 and segs[0]["end"] == t0 + 19 * M


def test_ongoing_stay_today_from_single_latest_point():
    t0 = DAY_START + 9 * H
    pts, _ = dense_commute(t0)
    last = pts[-1]["tst"]
    pts.append(pt(last + 20 * M, OFFICE))  # one fresh point at a new place
    now = last + 25 * M
    r = build(pts, now=now)
    segs = r["segments"]
    assert segs[-1]["type"] == "stay"
    assert segs[-1]["ongoing"] is True
    assert segs[-1]["end"] == last + 20 * M  # not extended to now
    assert segs[-2]["type"] == "move"
    assert all(s["type"] != "gap" or s["end"] <= now for s in segs)


def test_last_short_cluster_on_past_day_is_not_stay():
    t0 = DAY_START + 9 * H
    pts, _ = dense_commute(t0)
    last = pts[-1]["tst"]
    pts.append(pt(last + 20 * M, OFFICE))
    r = build(pts)  # now is far in the future -> not today
    real = [s for s in r["segments"] if s["type"] != "gap"]
    assert real[-1]["type"] == "move"
    assert all(not s.get("ongoing") for s in real)


# ---------------------------------------------------------------- mode inference


def test_mode_from_motion_activities_majority():
    p = [
        pt(0, HOME, motionactivities=["automotive"]),
        pt(60, HOME, motionactivities=["automotive", "stationary"]),
        pt(120, HOME, motionactivities=["walking"]),
        pt(180, HOME, motionactivities=["unknown"]),
    ]
    assert tl.infer_mode(p, [[*HOME, 0], [*OFFICE, 180]]) == "vehicle"


def north(m: float) -> list[float]:
    return list(offset(HOME, m))


def test_mode_from_speed():
    walk = [[*north(0), 0], [*north(400), 300], [*north(800), 600]]  # 4.8 km/h
    car = [[*north(0), 0], [*north(5000), 300], [*north(10000), 600]]  # 60 km/h
    middle = [[*north(0), 0], [*north(1000), 300], [*north(2000), 600]]  # 12 km/h
    assert tl.infer_mode([], walk) == "walk"
    assert tl.infer_mode([], car) == "vehicle"
    assert tl.infer_mode([], middle) == "unknown"
    assert tl.infer_mode([], [[*north(0), 0]]) == "unknown"


def sparse_bus_ride(t0: int):
    """10 min at HOME, a sparse ~21 min bus ride south with a stop, 30 min at the destination.

    Legs (seconds, km/h): walk to the bus stop, then the ride with a short stop.
    """
    legs = [(240, 4.5), (300, 9.0), (20, 3.6), (300, 14.0), (300, 8.0), (120, 7.5)]
    pts = [pt(t0 + i * M, offset(HOME, (i % 2) * 5)) for i in range(11)]
    t, south_m = pts[-1]["tst"], 0.0
    route = []
    for dt, kmh in legs:
        t += dt
        south_m += kmh / 3.6 * dt
        route.append((t, offset(HOME, -south_m)))
    *ride, (arrival, dest) = route
    extras = [
        {"motionactivities": ["walking"], "vel": 5},
        {"vel": 3},
        {"motionactivities": ["stationary"], "vel": 0},
        {"vel": 18},
        {},
    ]
    pts.extend(pt(tst, latlon, **extra) for (tst, latlon), extra in zip(ride, extras, strict=True))
    pts.extend(pt(arrival + i * M, offset(dest, 0, (i % 2) * 5)) for i in range(31))
    return pts


def test_sparse_bus_ride_with_one_walking_vote_is_vehicle():
    r = build(sparse_bus_ride(DAY_START + 9 * H))
    segs = [s for s in r["segments"] if s["type"] != "gap"]
    assert [s["type"] for s in segs] == ["stay", "move", "stay"]
    move = segs[1]
    avg_kmh = move["distance_m"] / (move["end"] - move["start"]) * 3.6
    assert 8 < avg_kmh < 9
    assert move["mode"] == "vehicle"


def test_walk_with_walking_votes_and_traffic_light_stays_walk():
    t0 = DAY_START + 9 * H
    pts, _ = dense_commute(t0)
    light = offset(HOME, 750)
    pts = [p for p in pts if not (t0 + 69 * M <= p["tst"] <= t0 + 71 * M)]
    pts.extend(pt(t0 + 69 * M + i * 30, light) for i in range(7))
    for p in pts:
        if t0 + 61 * M <= p["tst"] < t0 + 80 * M and p["tst"] % (3 * M) == 0:
            p["motionactivities"] = ["walking"]
    r = build(pts)
    segs = [s for s in r["segments"] if s["type"] != "gap"]
    assert [s["type"] for s in segs] == ["stay", "move", "stay"]
    assert segs[1]["mode"] == "walk"


MIDDLE_SPEED_PATH = [[*north(0), 0], [*north(1000), 300], [*north(2000), 600]]  # 12 km/h
WALK_PATH = [[*north(0), 0], [*north(400), 300], [*north(800), 600]]  # 4.8 km/h


def test_walking_majority_loses_to_automotive_when_speed_is_not_walk():
    p = [
        pt(100, HOME, motionactivities=["walking"]),
        pt(200, HOME, motionactivities=["walking"]),
        pt(300, HOME, motionactivities=["walking"]),
        pt(400, HOME, motionactivities=["automotive"]),
    ]
    assert tl.infer_mode(p, MIDDLE_SPEED_PATH) == "vehicle"
    assert tl.infer_mode(p, WALK_PATH) == "walk"


def test_middle_speed_without_motion_votes_is_unknown():
    p = [pt(100, HOME), pt(300, HOME, motionactivities=["stationary"])]
    assert tl.infer_mode(p, MIDDLE_SPEED_PATH) == "unknown"


def test_short_leg_does_not_skew_time_weighted_top_speed():
    # 5 min legs at 4.8 km/h and one 15 s leg at 20 km/h (unweighted p90 would be ~12 km/h)
    path, t, m = [[*north(0), 0]], 0, 0.0
    for dt, kmh in [(300, 4.8), (300, 4.8), (15, 20.0), (300, 4.8), (300, 4.8), (300, 4.8)]:
        t += dt
        m += kmh / 3.6 * dt
        path.append([*north(m), t])
    assert tl.classify_speed([], path) is tl.SpeedClass.WALK
    assert tl.infer_mode([], path) == "walk"


def test_reported_velocity_marks_vehicle_but_never_breaks_walk():
    fast = [pt(100, HOME, vel=12), pt(300, HOME, vel=30)]
    assert tl.classify_speed(fast, MIDDLE_SPEED_PATH) is tl.SpeedClass.VEHICLE
    assert tl.infer_mode(fast, MIDDLE_SPEED_PATH) == "vehicle"
    assert tl.infer_mode(fast, WALK_PATH) == "walk"
    assert tl.infer_mode([pt(100, HOME, vel="30")], MIDDLE_SPEED_PATH) == "unknown"


# ---------------------------------------------------------------- merge & gaps


def test_switchover_day_merges_google_visit_and_measured_stay():
    t0 = DAY_START
    segs = [
        {
            "t": "activity",
            "s": t0 + 7 * H,
            "e": t0 + 8 * H,
            "mode": "walking",
            "dist": 900.0,
            "slat": OFFICE[0],
            "slon": OFFICE[1],
            "elat": HOME[0],
            "elon": HOME[1],
        },
        {
            "t": "visit",
            "s": t0 + 8 * H,
            "e": t0 + 9 * H,
            "lat": HOME[0],
            "lon": HOME[1],
            "sem": "Home",
            "lvl": 0,
        },
    ]
    pts = [pt(t0 + 9 * H + 30 * M, offset(HOME, 40)), pt(t0 + 11 * H, offset(HOME, 20))]
    r = build(pts, sidecar_doc(segs))
    real = [s for s in r["segments"] if s["type"] != "gap"]
    assert [s["type"] for s in real] == ["move", "stay"]
    stay = real[1]
    assert stay["start"] == t0 + 8 * H and stay["end"] == t0 + 11 * H
    assert stay["source"] == "owntracks"
    assert stay["name"] == "自宅"


def test_merge_does_not_cross_moves_or_far_places():
    a = {
        "type": "stay",
        "start": 0,
        "end": 10,
        "lat": HOME[0],
        "lon": HOME[1],
        "ongoing": False,
        "name": None,
        "area": None,
        "source": "google",
        "children": [],
    }
    b = {**a, "start": 20, "end": 30, "lat": OFFICE[0], "lon": OFFICE[1]}
    mv = {"type": "move", "start": 10, "end": 20}
    c = {**a, "start": 20, "end": 30}
    assert len(tl.merge_stays([a, b])) == 2
    assert len(tl.merge_stays([a, mv, c])) == 3
    assert len(tl.merge_stays([a, c])) == 1


def test_gaps_inserted_at_head_tail_and_between():
    t0 = DAY_START
    pts = [pt(t0 + 10 * H + i * M, HOME) for i in range(31)]
    pts += [pt(t0 + 14 * H + i * M, OFFICE) for i in range(31)]
    r = build(pts)
    assert kinds(r) == ["gap", "stay", "move", "stay", "gap"]
    assert r["segments"][0] == {"type": "gap", "start": DAY_START, "end": t0 + 10 * H}
    assert r["segments"][-1]["end"] == DAY_END


def test_gaps_never_in_future():
    t0 = DAY_START
    pts = [pt(t0 + 10 * H + i * M, HOME) for i in range(31)]
    now = t0 + 12 * H
    segs = tl.insert_gaps(
        [{"type": "move", "start": t0 + 10 * H, "end": t0 + 10 * H + 30 * M}],
        DAY_START,
        DAY_END,
        now,
    )
    assert segs[-1] == {"type": "gap", "start": t0 + 10 * H + 30 * M, "end": now}
    # an ongoing stay today: no trailing gap
    r = build(pts, now=now)
    assert r["segments"][-1]["type"] == "stay" and r["segments"][-1]["ongoing"] is True


def test_empty_day():
    r = build([])
    assert kinds(r) == ["gap"]
    assert r["bounds"] is None
    assert r["summary"] == {"distance_m": {}, "move_seconds": 0, "stay_count": 0, "point_count": 0}


def test_resolver_called_with_semantic_type():
    calls = []

    def resolve(lat, lon, sem):
        calls.append(sem)
        return ("Z", "台東区上野七丁目")

    t0 = DAY_START + 10 * H
    segs = [{"t": "visit", "s": t0, "e": t0 + H, "lat": HOME[0], "lon": HOME[1], "sem": "Home"}]
    r = build([], sidecar_doc(segs), resolve=resolve)
    assert calls == ["Home"]
    stay = next(s for s in r["segments"] if s["type"] == "stay")
    assert stay["name"] == "Z" and stay["area"] == "台東区上野七丁目"


def test_nearest_named_and_parse_places():
    places = tl.parse_places(
        [
            {"name": "A", "lat": HOME[0], "lon": HOME[1], "radius": 100},
            {"name": "B", "lat": offset(HOME, 50)[0], "lon": HOME[1]},
            {"name": 1, "lat": 0, "lon": 0},
            "x",
        ]
    )
    assert [p["name"] for p in places] == ["A", "B"]
    assert tl.nearest_named(*offset(HOME, 40), places) == "B"
    assert tl.nearest_named(*OFFICE, places) is None


def test_parse_sidecar_rejects_garbage():
    assert tl.parse_sidecar([]) is None
    doc = tl.parse_sidecar({"segments": [{"t": "visit", "s": 1, "e": 0}, {"t": "x"}, 3]})
    assert doc == {"coverage_start": None, "coverage_end": None, "segments": []}


def test_sparse_single_point_followed_by_long_gap_is_stay():
    # significant モード: 自宅で1点、2時間後に 400m 先で1点、その後オフィスに長く滞在
    t0 = DAY_START + 8 * H
    away = offset(HOME, north_m=400)
    points = [
        pt(t0, HOME),
        pt(t0 + 2 * H, away),
        pt(t0 + 2 * H + 20 * M, OFFICE),
        pt(t0 + 4 * H, OFFICE),
    ]
    result = build(points)
    stays = [s for s in result["segments"] if s["type"] == "stay"]
    assert len(stays) == 2
    # 自宅の滞在は次の点の直前（徒歩で 400m ぶん手前）まで続く
    assert t0 + 2 * H - 10 * M < stays[0]["end"] < t0 + 2 * H
    assert kinds(result).count("move") == 1


def test_fast_gap_is_not_dwell():
    t0 = DAY_START + 8 * H
    cluster = [pt(t0, HOME)]
    assert tl.dwell_end(cluster, pt(t0 + 15 * M, OFFICE)) is None
    assert tl.dwell_end(cluster, pt(t0 + 5 * M, offset(HOME, north_m=100))) is None
