"""Pantallas de administración del catálogo: acceso, panel, eventos y cuotas."""
import re

import pytest

from app.db.enums import EstadoEvento, RolUsuario
from app.modules.usuarios import service as usuarios_service
from tests.factories import crear_deporte, crear_evento


def _entrar(client, email):
    client.post("/login", data={"email": email, "password": "secreta123"}, follow_redirects=False)


@pytest.fixture()
def admin(client, db):
    """Cliente con un administrador que ya inició sesión."""
    usuarios_service.crear_usuario(db, "admin@correo.com", "admin", "secreta123", RolUsuario.ADMIN)
    _entrar(client, "admin@correo.com")
    return client


@pytest.fixture()
def comun(client, db):
    """Cliente con un usuario común que ya inició sesión."""
    usuarios_service.crear_usuario(db, "ana@correo.com", "ana", "secreta123")
    _entrar(client, "ana@correo.com")
    return client


def _numeros_del_panel(html: str) -> dict[str, int]:
    pares = re.findall(r'estado=([A-Z_]+)".*?text-4xl[^>]*>(\d+)<', html, flags=re.S)
    return {estado: int(cantidad) for estado, cantidad in pares}


class TestPanelAdmin:
    def test_sin_sesion_redirige_al_login(self, client):
        respuesta = client.get("/admin", follow_redirects=False)
        assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/login")

    def test_usuario_comun_redirige_al_inicio(self, comun):
        respuesta = comun.get("/admin", follow_redirects=False)
        assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/")

    def test_admin_ve_el_panel_con_enlaces(self, admin):
        respuesta = admin.get("/admin")
        assert respuesta.status_code == 200
        assert 'href="/admin/eventos"' in respuesta.text and 'href="/admin/billetera"' in respuesta.text

    def test_muestra_los_contadores_de_eventos_por_estado(self, admin, db):
        deporte = crear_deporte(db)
        crear_evento(db, deporte)
        crear_evento(db, deporte)
        crear_evento(db, deporte, estado=EstadoEvento.CANCELADO)
        assert _numeros_del_panel(admin.get("/admin").text) == {
            "PROGRAMADO": 2,
            "EN_VIVO": 0,
            "FINALIZADO": 0,
            "CANCELADO": 1,
        }

    def test_muestra_la_cantidad_de_deportes_activos(self, admin, db):
        crear_deporte(db, "Fútbol")
        crear_deporte(db, "Tenis")
        assert re.search(r"Deportes activos</p>\s*<p[^>]*>2<", admin.get("/admin").text)

    def test_el_menu_marca_admin_como_activo(self, admin):
        assert 'href="/admin" aria-current="page"' in admin.get("/admin").text
