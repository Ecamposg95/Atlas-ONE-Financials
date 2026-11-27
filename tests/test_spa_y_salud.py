"""El catch-all de la SPA no sirve archivos de fuera de frontend/dist, y /api/health/deep responde 503 sin base."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as main


def _cliente_spa(tmp_path, monkeypatch) -> TestClient:
    dist = tmp_path / "app" / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    (dist / "favicon.svg").write_text("<svg/>")
    (tmp_path / "app" / "secreto.txt").write_text("no-debe-salir")
    (tmp_path / "secreto.txt").write_text("no-debe-salir")
    monkeypatch.setattr(main, "FRONTEND_DIST", dist)
    app = FastAPI()
    main._mount_frontend(app)
    return TestClient(app)


def test_la_spa_sirve_sus_archivos_y_el_index(tmp_path, monkeypatch):
    c = _cliente_spa(tmp_path, monkeypatch)
    assert c.get("/favicon.svg").text == "<svg/>"
    assert c.get("/").text == "<html>spa</html>"
    assert c.get("/cualquier/ruta/del/cliente").text == "<html>spa</html>"


def test_la_spa_no_sirve_archivos_fuera_de_dist(tmp_path, monkeypatch):
    c = _cliente_spa(tmp_path, monkeypatch)
    # Uvicorn y Starlette entregan la ruta ya decodificada: %2e%2e%2f y ..%2f llegan como ../
    for ruta in ("/..%2f..%2fsecreto.txt", "/%2e%2e%2f%2e%2e%2fsecreto.txt", "/..%2f..%2f..%2fsecreto.txt",
                 "/..%2f..%2f..%2f..%2f..%2f..%2fetc%2fpasswd", "/assets/..%2f..%2f..%2fsecreto.txt"):
        r = c.get(ruta)
        assert "no-debe-salir" not in r.text, ruta
        assert "root:" not in r.text, ruta


def test_health_deep_sin_base_es_503(client, monkeypatch):
    class _SinBase:
        def connect(self):
            raise RuntimeError("sin base")

    monkeypatch.setattr(main, "engine", _SinBase())
    r = client.get("/api/health/deep")
    assert r.status_code == 503
    assert r.json()["database"] == "error" and r.json()["status"] == "degraded"
