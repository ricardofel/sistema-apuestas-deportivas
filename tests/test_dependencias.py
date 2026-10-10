from datetime import timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.dependencies import (
    NOMBRE_COOKIE_TOKEN,
    get_db,
    get_usuario_actual,
    get_usuario_opcional,
    requiere_admin,
)
from app.core.security import crear_token_acceso
from app.db.enums import RolUsuario
from app.modules.usuarios import service


@pytest.fixture()
def cliente(db):
    app_prueba = FastAPI()

    @app_prueba.get("/actual")
    def actual(usuario=Depends(get_usuario_actual)):
        return {"email": usuario.email}

    @app_prueba.get("/opcional")
    def opcional(usuario=Depends(get_usuario_opcional)):
        return {"email": usuario.email if usuario else None}

    @app_prueba.get("/admin")
    def admin(usuario=Depends(requiere_admin)):
        return {"email": usuario.email}

    app_prueba.dependency_overrides[get_db] = lambda: db
    return TestClient(app_prueba)


@pytest.fixture()
def ana(db):
    return service.crear_usuario(db, "ana@correo.com", "ana", "secreta123")


@pytest.fixture()
def admin(db):
    return service.crear_usuario(db, "admin@correo.com", "admin", "secreta123", RolUsuario.ADMIN)


def _bearer(usuario) -> dict:
    return {"Authorization": f"Bearer {crear_token_acceso(usuario.id)}"}


def test_sin_token_es_401_y_opcional_devuelve_none(cliente):
    assert cliente.get("/actual").status_code == 401
    assert cliente.get("/opcional").json() == {"email": None}


def test_token_en_header_bearer(cliente, ana):
    respuesta = cliente.get("/actual", headers=_bearer(ana))
    assert respuesta.status_code == 200
    assert respuesta.json() == {"email": "ana@correo.com"}


def test_token_en_cookie(cliente, ana):
    cliente.cookies.set(NOMBRE_COOKIE_TOKEN, crear_token_acceso(ana.id))
    assert cliente.get("/actual").json() == {"email": "ana@correo.com"}


def test_token_invalido_es_401(cliente):
    respuesta = cliente.get("/actual", headers={"Authorization": "Bearer basura"})
    assert respuesta.status_code == 401
    assert respuesta.headers["WWW-Authenticate"] == "Bearer"


def test_token_expirado_es_401(cliente, ana):
    token = crear_token_acceso(ana.id, expira_en=timedelta(seconds=-1))
    assert cliente.get("/actual", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_token_de_usuario_inexistente_es_401(cliente, db, ana):
    headers = _bearer(ana)
    db.delete(ana)
    db.commit()
    assert cliente.get("/actual", headers=headers).status_code == 401


def test_usuario_desactivado_es_401(cliente, db, ana):
    ana.activo = False
    db.commit()
    assert cliente.get("/actual", headers=_bearer(ana)).status_code == 401


def test_requiere_admin_rechaza_usuario_comun_con_403(cliente, ana):
    assert cliente.get("/admin", headers=_bearer(ana)).status_code == 403


def test_requiere_admin_acepta_administrador(cliente, admin):
    assert cliente.get("/admin", headers=_bearer(admin)).status_code == 200


def test_requiere_admin_sin_token_es_401(cliente):
    assert cliente.get("/admin").status_code == 401
