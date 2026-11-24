"""Constants for the location_timeline integration."""

from typing import Final

DOMAIN: Final = "location_timeline"

CONF_RECORDER_URL: Final = "recorder_url"
CONF_USER: Final = "user"
CONF_DEVICE: Final = "device"
CONF_SEGMENTS_FILE: Final = "segments_file"
CONF_TOWNS_DB: Final = "towns_db"
CONF_PLACES_FILE: Final = "places_file"
CONF_SIDEBAR_TITLE: Final = "sidebar_title"
CONF_SIDEBAR_ICON: Final = "sidebar_icon"
CONF_REQUIRE_ADMIN: Final = "require_admin"

DEFAULT_SIDEBAR_TITLE: Final = "タイムライン"
DEFAULT_SIDEBAR_ICON: Final = "mdi:map-clock"
DEFAULT_REQUIRE_ADMIN: Final = True

STATIC_URL: Final = "/location_timeline_static"
PANEL_URL_PATH: Final = "location-timeline"
WEBCOMPONENT_NAME: Final = "location-timeline-panel"
PANEL_JS: Final = "location-timeline-panel.js"

# Recorder から取得する範囲（対象日の前後の余裕、秒）
FETCH_BEFORE_S: Final = 36 * 3600
FETCH_AFTER_S: Final = 6 * 3600
RECORDER_TIMEOUT_S: Final = 20
