"""Pantallas de administración del catálogo: acceso, panel, eventos y cuotas."""
import re
from datetime import UTC, datetime, timedelta

import pytest

from app.db.enums import EstadoEvento, RolUsuario
from app.modules.catalogo.models import Evento
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


def _datos_evento(deporte_id, /, **cambios) -> dict:
    datos = {
        "deporte_id": str(deporte_id),
        "equipo_local": "Emelec",
        "equipo_visitante": "Aucas",
        "inicia_en": "2099-05-20T19:30",
    }
    return {**datos, **cambios}


def _filas_de_eventos(html: str) -> list[str]:
    return re.findall(r'font-medium text-slate-900">(.*?) <span', html)


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


class TestAccesoListaAdmin:
    def test_sin_sesion_redirige_al_login(self, client):
        respuesta = client.get("/admin/eventos", follow_redirects=False)
        assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/login")

    def test_usuario_comun_redirige_al_inicio(self, comun):
        respuesta = comun.get("/admin/eventos", follow_redirects=False)
        assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/")

    @pytest.mark.parametrize("ruta", ["/admin/eventos", "/admin/deportes"])
    def test_post_sin_sesion_redirige_al_login_y_no_guarda(self, client, db, ruta):
        deporte = crear_deporte(db, "Tenis")
        respuesta = client.post(ruta, data=_datos_evento(deporte.id, nombre="Nuevo"), follow_redirects=False)
        assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/login")
        assert db.query(Evento).count() == 0

    @pytest.mark.parametrize("ruta", ["/admin/eventos", "/admin/deportes"])
    def test_post_de_usuario_comun_redirige_al_inicio_y_no_guarda(self, comun, db, ruta):
        deporte = crear_deporte(db, "Tenis")
        respuesta = comun.post(ruta, data=_datos_evento(deporte.id, nombre="Nuevo"), follow_redirects=False)
        assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/")
        assert [d["nombre"] for d in comun.get("/api/deportes").json()] == ["Tenis"]
        assert db.query(Evento).count() == 0


class TestListaAdminEventos:
    def test_lista_eventos_de_todos_los_estados(self, admin, db):
        deporte = crear_deporte(db)
        for estado, local in zip(EstadoEvento, ["Uno", "Dos", "Tres", "Cuatro"], strict=True):
            crear_evento(db, deporte, estado=estado, equipo_local=local)
        assert set(_filas_de_eventos(admin.get("/admin/eventos").text)) == {"Uno", "Dos", "Tres", "Cuatro"}

    def test_incluye_eventos_que_ya_iniciaron(self, admin, db):
        ayer = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=3)
        crear_evento(db, equipo_local="Pasado", inicia_en=ayer)
        assert _filas_de_eventos(admin.get("/admin/eventos").text) == ["Pasado"]

    def test_filtra_por_estado(self, admin, db):
        deporte = crear_deporte(db)
        crear_evento(db, deporte, equipo_local="Abierto")
        crear_evento(db, deporte, estado=EstadoEvento.CANCELADO, equipo_local="Cerrado")
        html = admin.get("/admin/eventos", params={"estado": "CANCELADO"}).text
        assert _filas_de_eventos(html) == ["Cerrado"]

    def test_filtra_por_deporte(self, admin, db):
        futbol, tenis = crear_deporte(db, "Fútbol"), crear_deporte(db, "Tenis")
        crear_evento(db, futbol, equipo_local="Futbolista")
        crear_evento(db, tenis, equipo_local="Tenista")
        assert _filas_de_eventos(admin.get("/admin/eventos", params={"deporte": tenis.id}).text) == ["Tenista"]

    def test_un_estado_invalido_se_ignora(self, admin, db):
        crear_evento(db, equipo_local="Visible")
        respuesta = admin.get("/admin/eventos", params={"estado": "NOEXISTE"})
        assert respuesta.status_code == 200 and _filas_de_eventos(respuesta.text) == ["Visible"]

    def test_pagina_de_a_veinte_con_enlaces(self, admin, db):
        deporte = crear_deporte(db)
        for i in range(25):
            crear_evento(db, deporte, equipo_local=f"Equipo {i:02d}")
        primera = admin.get("/admin/eventos").text
        segunda = admin.get("/admin/eventos", params={"pagina": 2}).text
        assert len(_filas_de_eventos(primera)) == 20 and len(_filas_de_eventos(segunda)) == 5
        assert "Página 1 de 2" in primera and "pagina=2" in primera
        assert "Página 2 de 2" in segunda and "pagina=1" in segunda

    def test_cada_evento_enlaza_a_su_gestion(self, admin, db):
        evento = crear_evento(db)
        assert f'href="/admin/eventos/{evento.id}"' in admin.get("/admin/eventos").text

    def test_sin_eventos_lo_dice(self, admin):
        assert "No hay eventos con esos filtros" in admin.get("/admin/eventos").text

    def test_sin_deportes_no_ofrece_el_formulario_de_evento(self, admin):
        assert "Primero crea un deporte" in admin.get("/admin/eventos").text


class TestCrearEventoDesdeLaPantalla:
    def test_crea_el_evento_y_ofrece_cargar_las_cuotas(self, admin, db):
        deporte = crear_deporte(db)
        respuesta = admin.post("/admin/eventos", data=_datos_evento(deporte.id))
        assert respuesta.status_code == 200
        assert "Evento creado: Emelec vs Aucas" in respuesta.text
        assert "Cargar las cuotas del evento" in respuesta.text
        assert _filas_de_eventos(respuesta.text) == ["Emelec"]

    def test_la_hora_de_ecuador_se_guarda_en_utc(self, admin, db):
        deporte = crear_deporte(db)
        admin.post("/admin/eventos", data=_datos_evento(deporte.id, inicia_en="2099-05-20T19:30"))
        assert db.query(Evento).one().inicia_en.isoformat() == "2099-05-21T00:30:00"

    def test_se_ve_en_la_hora_que_se_escribio(self, admin, db):
        deporte = crear_deporte(db)
        respuesta = admin.post("/admin/eventos", data=_datos_evento(deporte.id, inicia_en="2099-05-20T19:30"))
        assert "20/05/2099 19:30" in respuesta.text

    @pytest.mark.parametrize(
        ("cambios", "mensaje"),
        [
            ({"equipo_local": "   "}, "El equipo local debe tener entre 1 y 100 caracteres"),
            ({"equipo_visitante": ""}, "El equipo visitante debe tener entre 1 y 100 caracteres"),
            ({"equipo_local": "x" * 101}, "El equipo local debe tener entre 1 y 100 caracteres"),
            ({"equipo_local": "LDU", "equipo_visitante": "ldu"}, "Los equipos deben ser distintos"),
            ({"deporte_id": ""}, "Elige un deporte"),
            ({"inicia_en": ""}, "Ingresa una fecha de inicio válida"),
            ({"inicia_en": "mañana"}, "Ingresa una fecha de inicio válida"),
        ],
    )
    def test_datos_invalidos_422_y_no_crea_nada(self, admin, db, cambios, mensaje):
        deporte = crear_deporte(db)
        respuesta = admin.post("/admin/eventos", data=_datos_evento(deporte.id, **cambios))
        assert respuesta.status_code == 422 and mensaje in respuesta.text
        assert "Evento creado" not in respuesta.text
        assert db.query(Evento).count() == 0

    def test_conserva_lo_escrito_tras_un_error(self, admin, db):
        deporte = crear_deporte(db)
        datos = _datos_evento(deporte.id, equipo_local="Mi equipo", inicia_en="2000-01-01T10:00")
        respuesta = admin.post("/admin/eventos", data=datos)
        assert respuesta.status_code == 400
        assert 'value="Mi equipo"' in respuesta.text and 'value="2000-01-01T10:00"' in respuesta.text

    def test_fecha_pasada_400_con_el_mensaje_del_servicio(self, admin, db):
        deporte = crear_deporte(db)
        respuesta = admin.post("/admin/eventos", data=_datos_evento(deporte.id, inicia_en="2000-01-01T10:00"))
        assert respuesta.status_code == 400 and "La fecha de inicio debe ser futura" in respuesta.text

    def test_deporte_inexistente_404(self, admin, db):
        crear_deporte(db)
        respuesta = admin.post("/admin/eventos", data=_datos_evento(999))
        assert respuesta.status_code == 404 and "Deporte no encontrado" in respuesta.text


class TestCrearDeporteDesdeLaPantalla:
    def test_crea_el_deporte_y_aparece_en_el_formulario(self, admin):
        respuesta = admin.post("/admin/deportes", data={"nombre": " Tenis "})
        assert respuesta.status_code == 200 and "Deporte creado: Tenis" in respuesta.text
        assert ">Tenis</option>" in respuesta.text

    def test_nombre_duplicado_409(self, admin, db):
        crear_deporte(db, "Tenis")
        respuesta = admin.post("/admin/deportes", data={"nombre": "tenis"})
        assert respuesta.status_code == 409 and "Ya existe un deporte con ese nombre" in respuesta.text

    @pytest.mark.parametrize("nombre", ["", "   ", "x" * 51])
    def test_nombre_invalido_422(self, admin, nombre):
        respuesta = admin.post("/admin/deportes", data={"nombre": nombre})
        assert respuesta.status_code == 422
        assert "El nombre del deporte debe tener entre 1 y 50 caracteres" in respuesta.text
