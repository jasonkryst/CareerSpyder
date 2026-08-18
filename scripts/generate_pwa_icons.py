"""One-off script: generate PWA icon PNGs from CareerSpyder's header brand
mark (the magnifying-glass SVG in app/web/templates/base.html). Not part of
the app or test suite -- run manually and re-run if the mark or accent
color ever changes; the output PNGs are checked into git.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

ACCENT = "#b3101f"

MARK_SVG = """<svg viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="9" cy="9" r="5"></circle>
  <line x1="13" y1="13" x2="20" y2="20"></line>
  <polyline points="9,4 10.2,1.8 8.8,0.3"></polyline>
  <polyline points="5.5,5.5 2.6,4.5 0.8,6.3"></polyline>
  <polyline points="5.5,12.5 2.6,13.3 0.8,11.4"></polyline>
  <polyline points="9,14 10.2,16.3 8.8,17.8"></polyline>
</svg>"""

# (filename, canvas size in px, mark size as a fraction of canvas)
# Maskable gets a smaller fraction so the mark survives Android's
# adaptive-icon safe-zone cropping (only the inner ~80% is guaranteed visible).
ICONS = [
    ("icon-192.png", 192, 0.62),
    ("icon-512.png", 512, 0.62),
    ("icon-512-maskable.png", 512, 0.42),
    ("apple-touch-icon-180.png", 180, 0.62),
    ("favicon-32.png", 32, 0.72),
]

OUTPUT_DIR = Path(__file__).parent.parent / "app" / "web" / "static" / "icons"


def render(html_content: str, size: int, out_path: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": size, "height": size})
        page.set_content(html_content)
        page.screenshot(path=str(out_path))
        browser.close()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, size, mark_fraction in ICONS:
        mark_size = round(size * mark_fraction)
        html_content = f"""<!doctype html>
<html><head><style>
  html, body {{ margin: 0; padding: 0; }}
  .canvas {{
    width: {size}px; height: {size}px;
    background: {ACCENT};
    display: flex; align-items: center; justify-content: center;
  }}
  svg {{ width: {mark_size}px; height: {mark_size}px; }}
</style></head>
<body>
  <div class="canvas">{MARK_SVG}</div>
</body></html>"""
        out_path = OUTPUT_DIR / filename
        render(html_content, size, out_path)
        print(f"wrote {out_path} ({size}x{size}, mark {mark_size}px)")


if __name__ == "__main__":
    main()
