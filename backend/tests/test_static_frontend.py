from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as main_module


def _build_app_with_dist_dir(monkeypatch: pytest.MonkeyPatch, dist_dir: Path):
    monkeypatch.setattr(main_module, "FRONTEND_DIST_DIR", dist_dir)
    return main_module.create_app()


def test_serves_index_html_when_a_production_build_exists(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path, memory_settings
) -> None:
    dist_dir = tmp_path / "fake-dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>fake jarvis build</body></html>")

    app = _build_app_with_dist_dir(monkeypatch, dist_dir)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "fake jarvis build" in response.text


def test_does_not_mount_static_files_when_no_build_exists(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path, memory_settings
) -> None:
    missing_dist_dir = tmp_path / "no-such-dist"

    app = _build_app_with_dist_dir(monkeypatch, missing_dist_dir)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 404


def test_unmatched_api_path_still_returns_a_genuine_404_even_with_static_mount(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path, memory_settings
) -> None:
    # Regression check: mounting StaticFiles at "/" must never shadow the
    # API's own 404 for a path under /api/ that matches no real route —
    # StaticFiles returns 405 (not 404) for a non-GET/HEAD method on an
    # unmatched path, which would otherwise leak through.
    dist_dir = tmp_path / "fake-dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html></html>")

    app = _build_app_with_dist_dir(monkeypatch, dist_dir)
    with TestClient(app) as client:
        response = client.post("/api/this-endpoint-does-not-exist")

    assert response.status_code == 404


def test_unknown_frontend_path_falls_back_to_index_html_not_a_bare_404(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path, memory_settings
) -> None:
    """A genuine SPA fallback (Phase 6 diagnostic pass, D75-series): this
    frontend has exactly one real client route, so any other path reaching
    the backend must still get the real app shell (200, index.html) —
    never a bare framework 404 — so the SPA's own NotFoundDiagnostic can
    mount and render truthfully instead of the browser showing an
    unstyled error page."""
    dist_dir = tmp_path / "fake-dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>fake jarvis build</body></html>")

    app = _build_app_with_dist_dir(monkeypatch, dist_dir)
    with TestClient(app) as client:
        response = client.get("/this/path/does/not/exist")

    assert response.status_code == 200
    assert "fake jarvis build" in response.text


def test_spa_fallback_serves_a_real_root_level_static_file_verbatim(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path, memory_settings
) -> None:
    dist_dir = tmp_path / "fake-dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>fake jarvis build</body></html>")
    (dist_dir / "favicon.svg").write_text("<svg>fake favicon</svg>")

    app = _build_app_with_dist_dir(monkeypatch, dist_dir)
    with TestClient(app) as client:
        response = client.get("/favicon.svg")

    assert response.status_code == 200
    assert "fake favicon" in response.text


def test_spa_fallback_never_leaks_files_outside_the_dist_directory(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path, memory_settings
) -> None:
    dist_dir = tmp_path / "fake-dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>fake jarvis build</body></html>")
    secret = tmp_path / "secret.txt"
    secret.write_text("outside the dist directory")

    app = _build_app_with_dist_dir(monkeypatch, dist_dir)
    with TestClient(app) as client:
        response = client.get("/../secret.txt")

    assert response.status_code == 200
    assert "outside the dist directory" not in response.text
    assert "fake jarvis build" in response.text


def test_real_api_routes_still_work_when_static_mount_is_active(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path, memory_settings
) -> None:
    dist_dir = tmp_path / "fake-dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html></html>")

    app = _build_app_with_dist_dir(monkeypatch, dist_dir)
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_frontend_dist_dir_resolves_from_source_tree_when_not_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(main_module.sys, "frozen", raising=False)

    resolved = main_module._resolve_frontend_dist_dir()

    assert resolved == Path(main_module.__file__).resolve().parents[2] / "frontend" / "dist"


def test_frontend_dist_dir_resolves_from_meipass_when_frozen_onefile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    meipass_dir = tmp_path / "_MEIxxxxxx"
    meipass_dir.mkdir()
    monkeypatch.setattr(main_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main_module.sys, "_MEIPASS", str(meipass_dir), raising=False)

    resolved = main_module._resolve_frontend_dist_dir()

    assert resolved == meipass_dir / "frontend-dist"


def test_frontend_dist_dir_falls_back_to_executable_dir_when_frozen_without_meipass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_executable = tmp_path / "Jarvis Backend.bin"
    fake_executable.touch()
    monkeypatch.setattr(main_module.sys, "frozen", True, raising=False)
    monkeypatch.delattr(main_module.sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(main_module.sys, "executable", str(fake_executable))

    resolved = main_module._resolve_frontend_dist_dir()

    assert resolved == fake_executable.resolve().parent / "frontend-dist"
