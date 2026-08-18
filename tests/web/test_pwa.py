import struct
from pathlib import Path

ICON_DIR = Path(__file__).parent.parent.parent / "app" / "web" / "static" / "icons"

EXPECTED_ICONS = {
    "icon-192.png": 192,
    "icon-512.png": 512,
    "icon-512-maskable.png": 512,
    "apple-touch-icon-180.png": 180,
    "favicon-32.png": 32,
}


def _png_dimensions(path: Path) -> tuple[int, int]:
    with open(path, "rb") as f:
        header = f.read(24)
    return struct.unpack(">II", header[16:24])


def test_pwa_icons_are_served_at_correct_sizes(client):
    for filename, size in EXPECTED_ICONS.items():
        resp = client.get(f"/static/icons/{filename}")
        assert resp.status_code == 200, filename
        assert resp.headers["content-type"] == "image/png", filename

        width, height = _png_dimensions(ICON_DIR / filename)
        assert (width, height) == (size, size), filename


def test_manifest_json_has_expected_fields(client):
    resp = client.get("/static/manifest.json")

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "CareerSpyder"
    assert data["short_name"] == "CareerSpyder"
    assert data["start_url"] == "/"
    assert data["scope"] == "/"
    assert data["display"] == "standalone"
    assert data["theme_color"] == "#b3101f"

    icon_srcs = {icon["src"] for icon in data["icons"]}
    assert "/static/icons/icon-192.png" in icon_srcs
    assert "/static/icons/icon-512.png" in icon_srcs
    assert "/static/icons/icon-512-maskable.png" in icon_srcs

    maskable = next(i for i in data["icons"] if i["src"] == "/static/icons/icon-512-maskable.png")
    assert maskable["purpose"] == "maskable"


def test_offline_page_is_self_contained(client):
    resp = client.get("/static/offline.html")

    assert resp.status_code == 200
    assert "You're offline" in resp.text
    assert "<style>" in resp.text
    assert '/static/style.css' not in resp.text
    assert "location.reload()" in resp.text


def test_service_worker_route_has_correct_headers_and_scope_content(client):
    resp = client.get("/sw.js")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript")
    assert resp.headers["service-worker-allowed"] == "/"
    assert resp.headers["cache-control"] == "no-cache"
    assert "OFFLINE_URL" in resp.text
    assert "/static/offline.html" in resp.text
    assert 'event.request.mode === "navigate"' in resp.text
