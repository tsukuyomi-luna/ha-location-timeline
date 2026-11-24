from __future__ import annotations

import json

import build_google_sidecar as sc
import pytest


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("geo:35.123456,139.123456", (35.123456, 139.123456)),
        ("35.123°, 139.123°", (35.123, 139.123)),
        ("-33.8688°, 151.2093°", (-33.8688, 151.2093)),
        ("geo:-1.5,-70", (-1.5, -70.0)),
    ],
)
def test_parse_geo(text, expected):
    assert sc.parse_geo(text) == pytest.approx(expected)


@pytest.mark.parametrize("bad", ["", "geo:", "abc", "geo:95,10", "1,2,3", None, 12, ["35", "139"]])
def test_parse_geo_rejects(bad):
    assert sc.parse_geo(bad) is None


TIMELINE = [
    {
        "startTime": "2026-04-06T19:57:20.628+09:00",
        "endTime": "2026-04-07T08:00:00.000+09:00",
        "visit": {
            "hierarchyLevel": "0",
            "probability": "0.86",
            "topCandidate": {
                "semanticType": "Home",
                "placeID": "ChIJhome",
                "placeLocation": "geo:35.713800,139.777300",
                "probability": "0.9",
            },
        },
    },
    {
        "startTime": "2026-04-06T21:00:00.000+09:00",
        "endTime": "2026-04-06T22:00:00.000+09:00",
        "visit": {
            "hierarchyLevel": "1",
            "topCandidate": {"semanticType": "Unknown", "placeLocation": "35.7139°, 139.7774°"},
        },
    },
    {
        "startTime": "2026-04-07T08:00:00.000+09:00",
        "endTime": "2026-04-07T08:40:00.000+09:00",
        "activity": {
            "start": "geo:35.713800,139.777300",
            "end": "geo:35.681000,139.767000",
            "distanceMeters": "3800.5",
            "probability": "0.7",
            "topCandidate": {"type": "in train", "probability": "0.6"},
        },
    },
    {
        "startTime": "2026-04-06T10:57:20.628Z",
        "endTime": "2026-04-06T12:57:20.628Z",
        "timelinePath": [
            {"point": "geo:35.7138,139.7773", "durationMinutesOffsetFromStartTime": "55"}
        ],
    },
    # garbage that must be skipped
    "string",
    {"startTime": 1, "endTime": 2, "visit": {}},
    {
        "startTime": "2026-04-07T09:00:00+09:00",
        "endTime": "2026-04-07T08:00:00+09:00",
        "visit": {"topCandidate": {"placeLocation": "geo:1,2"}},
    },
    {
        "startTime": "2026-04-07T09:00:00+09:00",
        "endTime": "2026-04-07T10:00:00+09:00",
        "visit": {"topCandidate": {"placeLocation": 42}},
    },
    {
        "startTime": "2026-04-07T09:00:00+09:00",
        "endTime": "2026-04-07T10:00:00+09:00",
        "visit": "nope",
    },
    {"startTime": "not a time", "endTime": "2026-04-07T10:00:00+09:00", "activity": {}},
]


def test_convert_timeline():
    out = sc.convert(TIMELINE)
    segs = out["segments"]
    assert [s["t"] for s in segs] == ["visit", "visit", "activity"]
    home, child, act = segs
    assert home == {
        "t": "visit",
        "s": 1775473040,
        "e": 1775516400,
        "lat": 35.7138,
        "lon": 139.7773,
        "sem": "Home",
        "lvl": 0,
        "pid": "ChIJhome",
    }
    assert child["lvl"] == 1 and child["lat"] == pytest.approx(35.7139) and child["pid"] is None
    assert act["mode"] == "in train" and act["dist"] == 3800.5
    assert (act["slat"], act["slon"]) == (35.7138, 139.7773)
    assert (act["elat"], act["elon"]) == (35.681, 139.767)
    assert out["version"] == 1
    assert out["coverage_start"] == home["s"]
    assert out["coverage_end"] == act["e"]
    assert [s["s"] for s in segs] == sorted(s["s"] for s in segs)


def test_convert_non_list_input():
    out = sc.convert({"semanticSegments": []})
    assert out["segments"] == [] and out["coverage_end"] is None


def test_main_writes_file(tmp_path):
    src = tmp_path / "Timeline.json"
    dst = tmp_path / "out.json"
    src.write_text(json.dumps(TIMELINE), encoding="utf-8")
    assert sc.main([str(src), str(dst)]) == 0
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert len(data["segments"]) == 3
