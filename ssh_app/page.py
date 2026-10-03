"""Read the checked-in, offline frontend bundle."""

import json
from pathlib import Path


BUNDLE = Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html"


def render_page(language="en", *, preview=False):
    if not BUNDLE.is_file():
        raise RuntimeError("Frontend bundle is missing. Run npm ci && npm run build in frontend/.")
    config = json.dumps({"language": language, "mode": "preview" if preview else "native"}, ensure_ascii=True).replace("<", "\\u003c")
    bootstrap = (
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
        "font-src data:; base-uri 'none'; form-action 'none'\">"
        "<script>window.PYTHONA_SSH=" + config + ";</script>"
    )
    # Insert before the bundled module, which may already be in the document head.
    return BUNDLE.read_text(encoding="utf-8").replace("<head>", "<head>" + bootstrap, 1)
