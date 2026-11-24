"""Load the HA-independent modules directly from their file paths.

Importing ``custom_components.location_timeline.timeline`` would run the package
``__init__`` which imports Home Assistant, so the modules are loaded by path and
registered under short names instead.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = {
    "lt_timeline": ROOT / "custom_components/location_timeline/timeline.py",
    "lt_geocode": ROOT / "custom_components/location_timeline/geocode.py",
    "build_google_sidecar": ROOT / "scripts/build_google_sidecar.py",
    "build_towns_db": ROOT / "scripts/build_towns_db.py",
}

for _name, _path in MODULES.items():
    if _name in sys.modules:
        continue
    _spec = importlib.util.spec_from_file_location(_name, _path)
    assert _spec is not None and _spec.loader is not None
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _module
    _spec.loader.exec_module(_module)
