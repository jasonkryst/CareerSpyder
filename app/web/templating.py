"""Shared Jinja2Templates instance.

Uses an absolute path derived from this module's own location so template
resolution does not depend on the process's current working directory (which
would otherwise break when the package is installed/run from a location
other than the source checkout).
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
