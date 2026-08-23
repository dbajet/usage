from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from usage.libraries.static_page import StaticPage


def helper_instance(static_dir: Path) -> StaticPage:
    return StaticPage(static_dir)


def helper_populate(static_dir: Path) -> None:
    (static_dir / "index.html").write_text("<p>__BUILD__ __VERSION__</p>", encoding="utf-8")
    (static_dir / "app.js").write_text("console.log(1);", encoding="utf-8")
    (static_dir / "notes.txt").write_text("ignored", encoding="utf-8")
    (static_dir / "sub").mkdir()


def test___init__(tmp_path: Path) -> None:
    tested = helper_instance(tmp_path)
    assert tested._static_dir == tmp_path


def test_render(tmp_path: Path) -> None:
    helper_populate(tmp_path)
    tested = helper_instance(tmp_path)

    # with the build environment variables set
    environment = {"BUILD_TIME": "2026-08-18T00:00:00Z", "APP_VERSION": "1.2.3"}
    with patch.dict(os.environ, environment, clear=True):
        result = tested.render("index.html")
    expected = b"<p>2026-08-18T00:00:00Z 1.2.3</p>"
    assert result.body == expected
    exp_media_type = "text/html"
    assert result.media_type == exp_media_type
    exp_status_code = 200
    assert result.status_code == exp_status_code
    exp_cache_control = "no-store"
    assert result.headers["cache-control"] == exp_cache_control

    # without the build environment variables
    with patch.dict(os.environ, {}, clear=True):
        result = tested.render("index.html")
    expected = b"<p>ce28fe77ce705797 dev</p>"
    assert result.body == expected
    exp_media_type = "text/html"
    assert result.media_type == exp_media_type
    exp_status_code = 200
    assert result.status_code == exp_status_code
    exp_cache_control = "no-store"
    assert result.headers["cache-control"] == exp_cache_control

    # with an explicit media type (the service worker)
    environment = {"BUILD_TIME": "2026-08-18T00:00:00Z", "APP_VERSION": "1.2.3"}
    with patch.dict(os.environ, environment, clear=True):
        result = tested.render("app.js", "application/javascript")
    expected = b"console.log(1);"
    assert result.body == expected
    exp_media_type = "application/javascript"
    assert result.media_type == exp_media_type
    exp_status_code = 200
    assert result.status_code == exp_status_code
    exp_cache_control = "no-store"
    assert result.headers["cache-control"] == exp_cache_control


def test__asset_version(tmp_path: Path) -> None:
    helper_populate(tmp_path)
    tested = helper_instance(tmp_path)
    result = tested._asset_version()
    expected = "ce28fe77ce705797"
    assert result == expected
