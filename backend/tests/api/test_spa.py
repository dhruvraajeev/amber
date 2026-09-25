"""The built UI served from the API's own origin."""

import pytest
from fastapi.testclient import TestClient

from amber.api.app import create_app


@pytest.fixture
def spa(tmp_path):
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("run()")
    with TestClient(create_app(spa_dir=tmp_path)) as c:
        yield c


@pytest.mark.parametrize("path", ["/", "/compare", "/share/abc123"])
def test_page_paths_get_the_app_so_a_refresh_is_not_a_404(spa, path):
    r = spa.get(path)
    assert r.status_code == 200
    assert r.text == "<div id=root></div>"


def test_files_are_served_and_missing_files_stay_404(spa):
    assert spa.get("/assets/app.js").text == "run()"
    assert spa.get("/assets/old.js").status_code == 404


def test_api_and_health_still_answer_as_json(spa):
    assert spa.get("/healthz").json() == {"sha": "dev"}
    assert spa.get("/api/nope").json() == {"error": "not_found", "detail": "Not Found"}
    assert spa.post("/api/nope").status_code == 404
    assert spa.get("/api/simulate").json()["error"] == "method_not_allowed"  # POST-only route


def test_without_a_build_there_is_no_ui(tmp_path):
    with TestClient(create_app(spa_dir=tmp_path)) as c:
        assert c.get("/compare").status_code == 404
