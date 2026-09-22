import re
from importlib.metadata import version
from pathlib import Path

import pytest

_TEMPLATES = Path(__file__).parents[2] / "app" / "web" / "templates"
_STATIC_REF = re.compile(r'(?:src|href)="(/static/[^"?]+\.(?:js|css)(?:\?[^"]*)?)"')


@pytest.mark.parametrize("path", ["/static/style.css", "/static/theme.js", "/static/icons/favicon-32.png"])
def test_static_assets_are_cacheable_for_a_week(client, path):
    resp = client.get(path)

    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "public, max-age=604800"


@pytest.mark.parametrize("path", ["/static/manifest.json", "/static/offline.html"])
def test_unversioned_static_files_must_revalidate(client, path):
    # manifest.json and offline.html are fetched by fixed URL (the browser /
    # service worker), so they can't be cache-busted with ?v= and must revalidate.
    resp = client.get(path)

    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-cache"


def test_every_template_static_js_and_css_reference_is_versioned():
    # A long max-age is only safe if a deploy changes the URL (issue #167).
    unversioned = [
        f"{tpl.name}: {ref}"
        for tpl in _TEMPLATES.glob("*.html")
        for ref in _STATIC_REF.findall(tpl.read_text(encoding="utf-8"))
        if not ref.endswith("?v={{ app_version }}")
    ]
    assert unversioned == []


def test_rendered_page_carries_the_app_version_on_static_assets(client):
    resp = client.get("/")

    assert f'/static/style.css?v={version("careerspyder")}"' in resp.text
