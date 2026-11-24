from __future__ import annotations

import csv
import threading

import build_towns_db
import lt_geocode as gc
import pytest

HEADER = [
    "都道府県コード",
    "都道府県名",
    "都道府県名カナ",
    "都道府県名ローマ字",
    "市区町村コード",
    "市区町村名",
    "市区町村名カナ",
    "市区町村名ローマ字",
    "大字町丁目名",
    "大字町丁目名カナ",
    "大字町丁目名ローマ字",
    "小字・通称名",
    "緯度",
    "経度",
]


def row(pref, city, town, lat, lon):
    r = dict.fromkeys(HEADER, "")
    r.update(
        {"都道府県名": pref, "市区町村名": city, "大字町丁目名": town, "緯度": lat, "経度": lon}
    )
    return [r[h] for h in HEADER]


@pytest.fixture
def db(tmp_path):
    csv_path = tmp_path / "latest.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(HEADER)
        w.writerow(row("東京都", "台東区", "上野七丁目", "35.7138", "139.7773"))
        w.writerow(row("東京都", "台東区", "上野公園", "35.7123", "139.7793"))
        w.writerow(row("東京都", "千代田区", "丸の内一丁目", "35.6812", "139.7671"))
        w.writerow(row("東京都", "どこか", "空欄", "", ""))
        w.writerow(row("神奈川県", "横浜市西区", "高島二丁目", "35.4650", "139.6220"))
    out = tmp_path / "towns.sqlite"
    assert build_towns_db.build(csv_path, out) == 4
    return out


def test_cell_id_formula():
    assert gc.cell_id(35.7139, 139.7778) == 12571 * 100000 + 31977
    assert gc.cell_id(35.7139, 139.7778) == build_towns_db.cell_id(35.7139, 139.7778)


def test_nearest_lookup(db):
    g = gc.TownGeocoder(db)
    r = g.lookup(35.7137, 139.7771)
    assert r is not None
    assert (r["pref"], r["city"], r["town"]) == ("東京都", "台東区", "上野七丁目")
    assert r["distance_m"] < 50
    assert gc.area_name(r) == "台東区上野七丁目"
    # cached result is identical
    assert g.lookup(35.71371, 139.77711) is r


def test_lookup_expands_to_two_cells(db):
    g = gc.TownGeocoder(db)
    # ~1.2 km east of 丸の内一丁目: crosses more than one 0.01° cell boundary
    r = g.lookup(35.6812, 139.7671 + 0.0133)
    assert r is not None and r["town"] == "丸の内一丁目"
    assert 1000 < r["distance_m"] < 1500


def test_lookup_beyond_limit_is_none(db):
    g = gc.TownGeocoder(db)
    assert g.lookup(35.6812, 139.7671 + 0.02) is None  # ~1.8 km
    assert g.lookup(43.0, 141.3) is None


def test_missing_db_returns_none(tmp_path):
    g = gc.TownGeocoder(tmp_path / "nope.sqlite")
    assert g.lookup(35.7138, 139.7773) is None
    assert gc.area_name(None) is None


def test_thread_safe_lookups(db):
    g = gc.TownGeocoder(db)
    results = []

    def work(i):
        results.append(g.lookup(35.7138 + i * 1e-5, 139.7773))

    threads = [threading.Thread(target=work, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 16 and all(r and r["town"] == "上野七丁目" for r in results)
