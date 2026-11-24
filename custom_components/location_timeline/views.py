"""HTTP API views for the location timeline panel."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.http import KEY_HASS

from .const import FETCH_AFTER_S, FETCH_BEFORE_S, RECORDER_TIMEOUT_S
from .geocode import TownGeocoder, area_name
from .timeline import (
    SEMANTIC_NAMES,
    build_day,
    day_bounds,
    nearest_named,
    parse_places,
    parse_sidecar,
)

_LOGGER = logging.getLogger(__name__)


class JsonFileCache[T]:
    """Loads a JSON file and re-parses it when its mtime changes. Blocking; use executor."""

    def __init__(self, path: Path | None, parse: Callable[[Any], T], empty: T) -> None:
        self._path = path
        self._parse = parse
        self._empty = empty
        self._lock = threading.Lock()
        self._mtime: float | None = None
        self._value: T = empty

    def get(self) -> T:
        if self._path is None:
            return self._empty
        with self._lock:
            try:
                mtime = self._path.stat().st_mtime
            except OSError:
                self._mtime = None
                self._value = self._empty
                return self._empty
            if mtime != self._mtime:
                try:
                    with self._path.open(encoding="utf-8") as f:
                        self._value = self._parse(json.load(f))
                except (OSError, ValueError) as err:
                    _LOGGER.warning("Failed to load %s: %s", self._path, err)
                    self._value = self._empty
                self._mtime = mtime
            return self._value


class TimelineData:
    """Shared state for the views."""

    def __init__(
        self,
        *,
        recorder_url: str,
        user: str,
        device: str,
        segments_file: Path | None,
        towns_db: Path | None,
        places_file: Path | None,
        require_admin: bool,
    ) -> None:
        self.recorder_url = recorder_url.rstrip("/")
        self.user = user
        self.device = device
        self.require_admin = require_admin
        self.sidecar = JsonFileCache(segments_file, parse_sidecar, None)
        self.places = JsonFileCache(places_file, parse_places, [])
        self.geocoder = TownGeocoder(towns_db) if towns_db is not None else None


def _forbidden(view: HomeAssistantView, request: web.Request, data: TimelineData):
    if data.require_admin and not request["hass_user"].is_admin:
        return view.json_message("Admin access required", HTTPStatus.FORBIDDEN)
    return None


def _zones(hass: HomeAssistant) -> list[dict[str, Any]]:
    zones = []
    for state in hass.states.async_all("zone"):
        attrs = state.attributes
        if attrs.get("passive"):
            continue
        lat, lon, radius = attrs.get("latitude"), attrs.get("longitude"), attrs.get("radius")
        if not all(isinstance(v, int | float) for v in (lat, lon, radius)):
            continue
        zones.append(
            {
                "name": attrs.get("friendly_name") or state.name,
                "lat": float(lat),
                "lon": float(lon),
                "radius": float(radius),
            }
        )
    return zones


def make_resolver(
    zones: list[dict[str, Any]],
    places: list[dict[str, Any]],
    geocoder: TownGeocoder | None,
) -> Callable[[float, float, str | None], tuple[str | None, str | None]]:
    """Name resolution: HA zone -> places_file -> semantic type; area from geocoder."""

    def resolve(lat: float, lon: float, sem: str | None) -> tuple[str | None, str | None]:
        name = nearest_named(lat, lon, zones) or nearest_named(lat, lon, places)
        if name is None and sem is not None:
            name = SEMANTIC_NAMES.get(sem)
        area = area_name(geocoder.lookup(lat, lon)) if geocoder is not None else None
        return name, area

    return resolve


def _fmt_utc(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%S")


class DayView(HomeAssistantView):
    """GET /api/location_timeline/day?date=YYYY-MM-DD"""

    url = "/api/location_timeline/day"
    name = "api:location_timeline:day"
    requires_auth = True

    def __init__(self, data: TimelineData) -> None:
        self._data = data

    async def get(self, request: web.Request) -> web.Response:
        if (resp := _forbidden(self, request, self._data)) is not None:
            return resp
        hass: HomeAssistant = request.app[KEY_HASS]
        tz_name = hass.config.time_zone
        tz = ZoneInfo(tz_name)
        raw_date = request.query.get("date")
        if raw_date is None:
            day = datetime.now(tz).date()
        else:
            try:
                day = date.fromisoformat(raw_date)
            except ValueError:
                return self.json_message("Invalid date", HTTPStatus.BAD_REQUEST)

        day_start, day_end = day_bounds(day, tz_name)
        try:
            points = await self._fetch_points(
                hass, day_start - FETCH_BEFORE_S, day_end + FETCH_AFTER_S
            )
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.warning("OwnTracks Recorder request failed: %s", err)
            return self.json(
                {"error": f"OwnTracks Recorder request failed: {err!s}"},
                HTTPStatus.BAD_GATEWAY,
            )

        data = self._data
        sidecar = await hass.async_add_executor_job(data.sidecar.get)
        places = await hass.async_add_executor_job(data.places.get)
        resolve = make_resolver(_zones(hass), places, data.geocoder)
        now = int(datetime.now(UTC).timestamp())
        result = await hass.async_add_executor_job(
            lambda: build_day(
                day=day,
                tz_name=tz_name,
                raw_points=points,
                sidecar=sidecar,
                resolve=resolve,
                now=now,
            )
        )
        return self.json(result)

    async def _fetch_points(self, hass: HomeAssistant, start: int, end: int) -> list[Any]:
        session = async_get_clientsession(hass)
        params = {
            "user": self._data.user,
            "device": self._data.device,
            "from": _fmt_utc(start),
            "to": _fmt_utc(end),
        }
        async with session.get(
            f"{self._data.recorder_url}/api/0/locations",
            params=params,
            timeout=aiohttp.ClientTimeout(total=RECORDER_TIMEOUT_S),
        ) as resp:
            resp.raise_for_status()
            body = await resp.json(content_type=None)
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise ValueError("unexpected response shape")
        return body["data"]


class RangeView(HomeAssistantView):
    """GET /api/location_timeline/range -> {"first": date|null, "last": date}"""

    url = "/api/location_timeline/range"
    name = "api:location_timeline:range"
    requires_auth = True

    def __init__(self, data: TimelineData) -> None:
        self._data = data

    async def get(self, request: web.Request) -> web.Response:
        if (resp := _forbidden(self, request, self._data)) is not None:
            return resp
        hass: HomeAssistant = request.app[KEY_HASS]
        tz = ZoneInfo(hass.config.time_zone)
        sidecar = await hass.async_add_executor_job(self._data.sidecar.get)
        first = None
        if sidecar and sidecar.get("coverage_start") is not None:
            first = datetime.fromtimestamp(sidecar["coverage_start"], tz).date().isoformat()
        return self.json({"first": first, "last": datetime.now(tz).date().isoformat()})
