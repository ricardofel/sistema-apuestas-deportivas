import pytest

from app.db.enums import RolUsuario
from app.modules.usuarios import service

REGISTRO = {"email": "ana@correo.com", "nombre_usuario": "ana", "password": "secreta123"}


def _login(client, email="ana@correo.com", password="secreta123"):
    return client.post("/api/auth/login", data={"username": email, "password": password})


def _headers(client, email="ana@correo.com", password="secreta123") -> dict:
    token = _login(client, email, password).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestRegistro:
    def test_registro_exitoso(self, client):
        respuesta = client.post("/api/auth/registro", json=REGISTRO)
        assert respuesta.status_code == 201
        cuerpo = respuesta.json()
        assert cuerpo["email"] == "ana@correo.com"
        assert cuerpo["rol"] == "USUARIO"
        assert cuerpo["saldo"] == "0.00"
        assert "password" not in cuerpo and "password_hash" not in cuerpo

    def test_no_permite_elegir_el_rol(self, client):
        respuesta = client.post("/api/auth/registro", json={**REGISTRO, "rol": "ADMIN"})
        assert respuesta.json()["rol"] == "USUARIO"

    def test_email_duplicado_devuelve_409(self, client):
        client.post("/api/auth/registro", json=REGISTRO)
        respuesta = client.post("/api/auth/registro", json={**REGISTRO, "nombre_usuario": "otra"})
        assert respuesta.status_code == 409

    @pytest.mark.parametrize(
        "campos",
        [{"password": "corta"}, {"email": "no-es-email"}, {"nombre_usuario": "ab"}],
    )
    def test_datos_invalidos_devuelven_422(self, client, campos):
        assert client.post("/api/auth/registro", json={**REGISTRO, **campos}).status_code == 422


class TestLogin:
    def test_login_devuelve_token_usable(self, client):
        client.post("/api/auth/registro", json=REGISTRO)
        respuesta = _login(client)
        assert respuesta.status_code == 200
        assert respuesta.json()["token_type"] == "bearer"

    def test_password_incorrecta_devuelve_401(self, client):
        client.post("/api/auth/registro", json=REGISTRO)
        assert _login(client, password="incorrecta").status_code == 401

    def test_usuario_inexistente_devuelve_401(self, client):
        assert _login(client, email="nadie@correo.com").status_code == 401


class TestPerfil:
    def test_perfil_del_usuario_autenticado(self, client):
        client.post("/api/auth/registro", json=REGISTRO)
        respuesta = client.get("/api/usuarios/yo", headers=_headers(client))
        assert respuesta.status_code == 200
        assert respuesta.json()["nombre_usuario"] == "ana"

    def test_sin_token_devuelve_401(self, client):
        assert client.get("/api/usuarios/yo").status_code == 401


class TestListadoAdmin:
    def test_administrador_ve_los_usuarios(self, client, db):
        client.post("/api/auth/registro", json=REGISTRO)
        service.crear_usuario(db, "admin@correo.com", "admin", "secreta123", RolUsuario.ADMIN)
        respuesta = client.get("/api/admin/usuarios", headers=_headers(client, "admin@correo.com"))
        assert respuesta.status_code == 200
        assert len(respuesta.json()) == 2

    def test_usuario_comun_recibe_403(self, client):
        client.post("/api/auth/registro", json=REGISTRO)
        assert client.get("/api/admin/usuarios", headers=_headers(client)).status_code == 403

    def test_paginacion(self, client, db):
        admin = service.crear_usuario(db, "admin@correo.com", "admin", "secreta123", RolUsuario.ADMIN)
        for numero in range(3):
            service.crear_usuario(db, f"u{numero}@correo.com", f"usuario{numero}", "secreta123")
        headers = _headers(client, admin.email)
        assert len(client.get("/api/admin/usuarios?limite=2", headers=headers).json()) == 2
        assert client.get("/api/admin/usuarios?limite=0", headers=headers).status_code == 422
