import re
from datetime import datetime

import pytest

from app.db.enums import RolUsuario
from app.modules.usuarios import service as usuarios_service
from app.web.templating import hora_local


def _activos(html: str) -> list[str]:
    return re.findall(r'<a href="([^"]+)" aria-current="page"', html)


def _entrar(client, email):
    client.post("/login", data={"email": email, "password": "secreta123"}, follow_redirects=False)


@pytest.fixture()
def ana(db):
    return usuarios_service.crear_usuario(db, "ana@correo.com", "ana", "secreta123")


class TestMenuActivo:
    def test_en_el_inicio_ninguna_seccion_esta_activa(self, client):
        assert _activos(client.get("/").text) == []

    def test_eventos_queda_marcado_sin_sesion(self, client):
        assert _activos(client.get("/eventos").text) == ["/eventos"]

    def test_el_logo_nunca_se_marca_como_seccion_activa(self, client):
        assert "/" not in _activos(client.get("/eventos").text)

    def test_la_seccion_activa_cambia_con_la_pagina(self, client, ana):
        _entrar(client, "ana@correo.com")
        assert _activos(client.get("/eventos").text) == ["/eventos"]
        assert _activos(client.get("/billetera").text) == ["/billetera"]

    def test_admin_marca_su_seccion_en_subrutas(self, client, db):
        usuarios_service.crear_usuario(db, "admin@correo.com", "admin", "secreta123", RolUsuario.ADMIN)
        _entrar(client, "admin@correo.com")
        assert _activos(client.get("/admin/billetera").text) == ["/admin"]

    def test_login_y_registro_no_marcan_ninguna_seccion(self, client):
        assert _activos(client.get("/login").text) == []
        assert _activos(client.get("/registro").text) == []

    def test_con_sesion_se_ve_el_boton_salir_y_el_saldo(self, client, ana):
        _entrar(client, "ana@correo.com")
        html = client.get("/eventos").text
        assert "Salir" in html and "0.00 créditos" in html


def test_hora_local_convierte_utc_a_ecuador():
    assert hora_local(datetime(2026, 1, 1, 15, 0)) == "01/01/2026 10:00"
    assert hora_local(datetime(2026, 1, 1, 3, 30)) == "31/12/2025 22:30"
