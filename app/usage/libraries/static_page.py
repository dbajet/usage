from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi.responses import HTMLResponse


class StaticPage:
    def __init__(self, static_dir: Path) -> None:
        self._static_dir = static_dir

    def render(self, file_name: str) -> HTMLResponse:
        html = (self._static_dir / file_name).read_text(encoding="utf-8")
        build = os.environ.get("BUILD_TIME") or self._asset_version()
        version = os.environ.get("APP_VERSION", "dev")
        result = html.replace("__BUILD__", build).replace("__VERSION__", version)
        return HTMLResponse(result, headers={"Cache-Control": "no-store"})

    def _asset_version(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self._static_dir.glob("*")):
            if path.is_file() and path.suffix in {".css", ".html", ".js", ".svg"}:
                digest.update(path.name.encode("utf-8"))
                digest.update(path.read_bytes())
        result = digest.hexdigest()[:16]
        return result
