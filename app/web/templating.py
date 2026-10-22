"""Shared Jinja2Templates instance.

Uses an absolute path derived from this module's own location so template
resolution does not depend on the process's current working directory (which
would otherwise break when the package is installed/run from a location
other than the source checkout).
"""

import os
from importlib.metadata import version
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.web.query_params import query_url, sort_url
from app.web.timeago import timeago as _timeago_fn
from app.web.whats_new import whats_new_html as _whats_new_html

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["timeago"] = _timeago_fn
_app_version = version("careerspyder")
templates.env.globals["app_name"] = "CareerSpyder"
templates.env.globals["app_version"] = _app_version
templates.env.globals["query_url"] = query_url
templates.env.globals["sort_url"] = sort_url
# Read from CHANGELOG.md once at import time (see whats_new.py) rather than
# per-request -- the content is static for the lifetime of the process.
templates.env.globals["whats_new_html"] = _whats_new_html(_app_version)
# A callable, not a value set once at import: os.environ.get() runs at
# render time so tests can toggle GA_MEASUREMENT_ID per-test via monkeypatch.
templates.env.globals["ga_measurement_id"] = lambda: os.environ.get("GA_MEASUREMENT_ID", "")
