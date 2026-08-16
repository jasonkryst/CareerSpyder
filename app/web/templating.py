"""Shared Jinja2Templates instance.

Uses an absolute path derived from this module's own location so template
resolution does not depend on the process's current working directory (which
would otherwise break when the package is installed/run from a location
other than the source checkout).
"""

from importlib.metadata import version
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.web.query_params import query_url, sort_url

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["app_name"] = "CareerSpyder"
templates.env.globals["app_version"] = version("careerspyder")
templates.env.globals["query_url"] = query_url
templates.env.globals["sort_url"] = sort_url
