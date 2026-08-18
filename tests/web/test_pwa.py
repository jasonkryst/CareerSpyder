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
