from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.enums import RolUsuario
from app.modules.billetera import service as billetera_service
from app.modules.usuarios import service as usuarios_service

CLAVE = "secreta123"


@pytest.fixture()
def ana(db):
    return usuarios_service.crear_usuario(db, "ana@correo.com", "ana", CLAVE)


@pytest.fixture()
def admin(db):
    return usuarios_service.crear_usuario(db, "admin@correo.com", "admin", CLAVE, RolUsuario.ADMIN)


def _entrar(client, email):
    respuesta = client.post("/login", data={"email": email, "password": CLAVE}, follow_redirects=False)
    assert respuesta.status_code == 303
    return respuesta


class TestRegistro:
    def test_formulario(self, client):
        respuesta = client.get("/registro")
        assert respuesta.status_code == 200
        assert "Crear cuenta" in respuesta.text

    def test_registro_inicia_sesion_automaticamente(self, client):
        datos = {"email": "ana@correo.com", "nombre_usuario": "ana", "password": CLAVE}
        respuesta = client.post("/registro", data=datos, follow_redirects=False)
        assert respuesta.status_code == 303
        assert respuesta.headers["location"] == "/"
        assert "httponly" in respuesta.headers["set-cookie"].lower()
        assert "ana" in client.get("/").text
        assert "Salir" in client.get("/").text

    def test_email_duplicado_muestra_el_error(self, client, ana):
        datos = {"email": "ana@correo.com", "nombre_usuario": "otra", "password": CLAVE}
        respuesta = client.post("/registro", data=datos)
        assert respuesta.status_code == 409
        assert "El email ya está registrado" in respuesta.text

    def test_contrasena_corta_muestra_el_error(self, client):
        datos = {"email": "ana@correo.com", "nombre_usuario": "ana", "password": "corta"}
        respuesta = client.post("/registro", data=datos)
        assert respuesta.status_code == 422
        assert "La contraseña debe tener entre 8 y 72 caracteres" in respuesta.text
        assert 'value="ana@correo.com"' in respuesta.text


class TestLoginYLogout:
    def test_formulario(self, client):
        assert client.get("/login").status_code == 200

    def test_login_correcto_guarda_cookie_y_redirige(self, client, ana):
        respuesta = _entrar(client, "ana@correo.com")
        assert respuesta.headers["location"] == "/"
        assert "access_token=" in respuesta.headers["set-cookie"]

    def test_login_incorrecto_muestra_el_error(self, client, ana):
        respuesta = client.post("/login", data={"email": "ana@correo.com", "password": "mala-clave"})
        assert respuesta.status_code == 401
        assert "Credenciales inválidas" in respuesta.text

    def test_con_sesion_iniciada_el_login_redirige(self, client, ana):
        _entrar(client, "ana@correo.com")
        assert client.get("/login", follow_redirects=False).headers["location"] == "/"

    def test_logout_cierra_la_sesion(self, client, ana):
        _entrar(client, "ana@correo.com")
        assert client.post("/logout", follow_redirects=False).status_code == 303
        client.cookies.clear()
        assert client.get("/billetera", follow_redirects=False).headers["location"] == "/login"

    def test_navbar_anonima_ofrece_login_y_registro(self, client):
        html = client.get("/").text
        assert "Iniciar sesión" in html and "Registrarse" in html


class TestBilletera:
    def test_sin_sesion_redirige_al_login(self, client):
        respuesta = client.get("/billetera", follow_redirects=False)
        assert respuesta.status_code == 303
        assert respuesta.headers["location"] == "/login"

    def test_muestra_saldo_e_historial(self, client, db, ana):
        billetera_service.recargar_saldo(db, ana.id, Decimal("40.00"), "Bono de bienvenida")
        billetera_service.debitar(db, ana.id, Decimal("15.50"), None, "Apuesta")
        db.commit()
        _entrar(client, "ana@correo.com")
        html = client.get("/billetera").text
        assert "24.50" in html
        assert "Bono de bienvenida" in html
        assert "+40.00" in html and "-15.50" in html

    def test_sin_movimientos(self, client, ana):
        _entrar(client, "ana@correo.com")
        assert "Todavía no tienes movimientos" in client.get("/billetera").text

    def test_paginacion(self, client, db, ana):
        for numero in range(12):
            billetera_service.recargar_saldo(db, ana.id, Decimal("1.00"), f"Recarga {numero}")
        _entrar(client, "ana@correo.com")
        primera = client.get("/billetera").text
        segunda = client.get("/billetera?pagina=2").text
        assert "Página 1 de 2" in primera and "Siguiente" in primera
        assert "Página 2 de 2" in segunda and "Anterior" in segunda
        assert "Recarga 11" in primera and "Recarga 0" in segunda

    def test_fragmento_de_saldo_para_htmx(self, client, db, ana):
        assert client.get("/web/saldo").status_code == 401
        billetera_service.recargar_saldo(db, ana.id, Decimal("7.25"))
        _entrar(client, "ana@correo.com")
        respuesta = client.get("/web/saldo")
        assert respuesta.status_code == 200
        assert "7.25 créditos" in respuesta.text
        assert "<html" not in respuesta.text

    def test_la_navbar_muestra_el_saldo(self, client, db, ana):
        billetera_service.recargar_saldo(db, ana.id, Decimal("3.00"))
        _entrar(client, "ana@correo.com")
        html = client.get("/").text
        assert "3.00 créditos" in html
        assert 'hx-trigger="saldo-actualizado from:body"' in html


class TestRecargaAdmin:
    def test_sin_sesion_redirige_al_login(self, client):
        assert client.get("/admin/billetera", follow_redirects=False).headers["location"] == "/login"

    def test_usuario_comun_es_enviado_al_inicio(self, client, ana):
        _entrar(client, "ana@correo.com")
        assert client.get("/admin/billetera", follow_redirects=False).headers["location"] == "/"
        datos = {"usuario_id": str(ana.id), "monto": "10.00"}
        assert client.post("/admin/billetera/recargar", data=datos, follow_redirects=False).status_code == 303

    def test_admin_ve_el_formulario_con_los_usuarios(self, client, ana, admin):
        _entrar(client, "admin@correo.com")
        html = client.get("/admin/billetera").text
        assert "Recargar saldo" in html
        assert "ana@correo.com" in html

    def test_admin_recarga_saldo(self, client, db, ana, admin):
        _entrar(client, "admin@correo.com")
        datos = {"usuario_id": str(ana.id), "monto": "25.50", "descripcion": "Bono"}
        respuesta = client.post("/admin/billetera/recargar", data=datos)
        assert respuesta.status_code == 200
        assert "Se recargaron 25.50 créditos a ana" in respuesta.text
        db.refresh(ana)
        assert ana.saldo == Decimal("25.50")

    @pytest.mark.parametrize("monto", ["0", "-5", "abc", "1.234"])
    def test_monto_invalido_muestra_el_error(self, client, ana, admin, monto):
        _entrar(client, "admin@correo.com")
        respuesta = client.post("/admin/billetera/recargar", data={"usuario_id": str(ana.id), "monto": monto})
        assert respuesta.status_code == 422
        assert "Ingresa un monto mayor que cero" in respuesta.text

    def test_usuario_inexistente_muestra_el_error(self, client, admin):
        _entrar(client, "admin@correo.com")
        respuesta = client.post("/admin/billetera/recargar", data={"usuario_id": str(uuid4()), "monto": "5.00"})
        assert respuesta.status_code == 404
        assert "Usuario no encontrado" in respuesta.text
