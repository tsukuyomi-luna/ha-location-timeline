"""Location timeline: a Google Maps Timeline-like sidebar panel backed by OwnTracks Recorder."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_DEVICE,
    CONF_PLACES_FILE,
    CONF_RECORDER_URL,
    CONF_REQUIRE_ADMIN,
    CONF_SEGMENTS_FILE,
    CONF_SIDEBAR_ICON,
    CONF_SIDEBAR_TITLE,
    CONF_TOWNS_DB,
    CONF_USER,
    DEFAULT_REQUIRE_ADMIN,
    DEFAULT_SIDEBAR_ICON,
    DEFAULT_SIDEBAR_TITLE,
    DOMAIN,
    PANEL_JS,
    PANEL_URL_PATH,
    STATIC_URL,
    WEBCOMPONENT_NAME,
)
from .views import DayView, RangeView, TimelineData

_LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_RECORDER_URL): cv.url,
                vol.Required(CONF_USER): cv.string,
                vol.Required(CONF_DEVICE): cv.string,
                vol.Optional(CONF_SEGMENTS_FILE): cv.string,
                vol.Optional(CONF_TOWNS_DB): cv.string,
                vol.Optional(CONF_PLACES_FILE): cv.string,
                vol.Optional(CONF_SIDEBAR_TITLE, default=DEFAULT_SIDEBAR_TITLE): cv.string,
                vol.Optional(CONF_SIDEBAR_ICON, default=DEFAULT_SIDEBAR_ICON): cv.icon,
                vol.Optional(CONF_REQUIRE_ADMIN, default=DEFAULT_REQUIRE_ADMIN): cv.boolean,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


def _resolve_path(hass: HomeAssistant, value: str | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else Path(hass.config.path(value))


def _read_version() -> str:
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text("utf-8"))
    mtime = int((FRONTEND_DIR / PANEL_JS).stat().st_mtime)
    return f"{manifest['version']}-{mtime}"


def _warn_missing(paths: dict[str, Path | None]) -> None:
    for key, path in paths.items():
        if path is not None and not path.is_file():
            _LOGGER.warning("%s not found: %s", key, path)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    conf = config.get(DOMAIN)
    if conf is None:
        return True

    files = {
        CONF_SEGMENTS_FILE: _resolve_path(hass, conf.get(CONF_SEGMENTS_FILE)),
        CONF_TOWNS_DB: _resolve_path(hass, conf.get(CONF_TOWNS_DB)),
        CONF_PLACES_FILE: _resolve_path(hass, conf.get(CONF_PLACES_FILE)),
    }
    await hass.async_add_executor_job(_warn_missing, files)
    version = await hass.async_add_executor_job(_read_version)

    data = TimelineData(
        recorder_url=conf[CONF_RECORDER_URL],
        user=conf[CONF_USER],
        device=conf[CONF_DEVICE],
        segments_file=files[CONF_SEGMENTS_FILE],
        towns_db=files[CONF_TOWNS_DB],
        places_file=files[CONF_PLACES_FILE],
        require_admin=conf[CONF_REQUIRE_ADMIN],
    )
    hass.data[DOMAIN] = data

    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), False)]
    )
    hass.http.register_view(DayView(data))
    hass.http.register_view(RangeView(data))

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=WEBCOMPONENT_NAME,
        frontend_url_path=PANEL_URL_PATH,
        module_url=f"{STATIC_URL}/{PANEL_JS}?v={version}",
        sidebar_title=conf[CONF_SIDEBAR_TITLE],
        sidebar_icon=conf[CONF_SIDEBAR_ICON],
        require_admin=conf[CONF_REQUIRE_ADMIN],
        config={"static_base": STATIC_URL, "version": version},
    )
    return True
