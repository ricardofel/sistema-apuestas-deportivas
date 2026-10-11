"""Pantallas de administración del catálogo: acceso, panel, eventos y cuotas."""
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.enums import EstadoEvento, RolUsuario, TipoSeleccion
from app.modules.catalogo.models import Evento
from app.modules.usuarios import service as usuarios_service
from tests.factories import crear_cuota, crear_deporte, crear_evento


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


def _cuotas_del_evento(db, evento):
    db.expire_all()
    return {c.seleccion: c for c in db.get(Evento, evento.id).cuotas}


def _evento_con_cuotas(db, **campos):
    evento = crear_evento(db, **campos)
    crear_cuota(db, evento, TipoSeleccion.LOCAL, Decimal("2.00"))
    crear_cuota(db, evento, TipoSeleccion.VISITANTE, Decimal("3.00"))
    return evento


class TestAccesoGestionEvento:
    def test_get_sin_sesion_redirige_al_login(self, client, db):
        evento = crear_evento(db)
        respuesta = client.get(f"/admin/eventos/{evento.id}", follow_redirects=False)
        assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/login")

    def test_get_de_usuario_comun_redirige_al_inicio(self, comun, db):
        evento = crear_evento(db)
        respuesta = comun.get(f"/admin/eventos/{evento.id}", follow_redirects=False)
        assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/")

    @pytest.mark.parametrize(
        "ruta",
        ["/admin/eventos/{e}/editar", "/admin/eventos/{e}/cuotas", "/admin/cuotas/{c}/editar"],
    )
    def test_post_sin_sesion_redirige_y_no_cambia_nada(self, client, db, ruta):
        evento = _evento_con_cuotas(db)
        cuota = evento.cuotas[0]
        datos = {"equipo_local": "Otro", "valor": "9.99", "cuota_local": "9.99", "cuota_visitante": "9.99"}
        respuesta = client.post(ruta.format(e=evento.id, c=cuota.id), data=datos, follow_redirects=False)
        assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/login")
        db.refresh(evento)
        db.refresh(cuota)
        assert evento.equipo_local == "Barcelona" and cuota.valor == Decimal("2.00")

    @pytest.mark.parametrize(
        "ruta",
        ["/admin/eventos/{e}/editar", "/admin/eventos/{e}/cuotas", "/admin/cuotas/{c}/editar"],
    )
    def test_post_de_usuario_comun_redirige_y_no_cambia_nada(self, comun, db, ruta):
        evento = _evento_con_cuotas(db)
        cuota = evento.cuotas[0]
        datos = {"equipo_local": "Otro", "valor": "9.99", "cuota_local": "9.99", "cuota_visitante": "9.99"}
        respuesta = comun.post(ruta.format(e=evento.id, c=cuota.id), data=datos, follow_redirects=False)
        assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/")
        db.refresh(evento)
        db.refresh(cuota)
        assert evento.equipo_local == "Barcelona" and cuota.valor == Decimal("2.00")


class TestGestionEvento:
    def test_muestra_los_datos_del_evento(self, admin, db):
        evento = crear_evento(db, equipo_local="Barcelona SC", inicia_en=datetime(2030, 5, 20, 22, 30))
        html = admin.get(f"/admin/eventos/{evento.id}").text
        assert "Barcelona SC" in html and "Programado" in html and "20/05/2030 17:30" in html
        assert 'value="2030-05-20T17:30"' in html

    def test_muestra_las_cuotas_incluidas_las_inactivas(self, admin, db):
        evento = _evento_con_cuotas(db)
        apagada = evento.cuotas[1]
        apagada.activa = False
        db.commit()
        html = admin.get(f"/admin/eventos/{evento.id}").text
        assert "2.00" in html and "3.00" in html and "Inactiva" in html

    def test_evento_inexistente_404(self, admin):
        respuesta = admin.get(f"/admin/eventos/{uuid.uuid4()}")
        assert respuesta.status_code == 404 and "Evento no encontrado" in respuesta.text

    def test_id_que_no_es_uuid_404(self, admin):
        assert admin.get("/admin/eventos/abc").status_code == 404

    def test_evento_cerrado_no_ofrece_editar_ni_cambiar_valores(self, admin, db):
        evento = _evento_con_cuotas(db, estado=EstadoEvento.CANCELADO)
        html = admin.get(f"/admin/eventos/{evento.id}").text
        assert "ya no se puede editar" in html
        assert "/editar" not in html.replace(f"/admin/cuotas/{evento.cuotas[0].id}/editar", "").replace(
            f"/admin/cuotas/{evento.cuotas[1].id}/editar", ""
        )
        assert "Cambiar valor" not in html


class TestEditarEventoDesdeLaPantalla:
    def test_guarda_los_cambios(self, admin, db):
        evento = crear_evento(db)
        datos = _datos_evento(evento.deporte_id, equipo_local="Emelec", inicia_en="2099-01-02T20:00")
        respuesta = admin.post(f"/admin/eventos/{evento.id}/editar", data=datos)
        assert respuesta.status_code == 200 and "Evento actualizado" in respuesta.text
        db.refresh(evento)
        assert evento.equipo_local == "Emelec" and evento.inicia_en.isoformat() == "2099-01-03T01:00:00"

    def test_puede_cambiar_de_deporte(self, admin, db):
        evento = crear_evento(db)
        tenis = crear_deporte(db, "Tenis")
        admin.post(f"/admin/eventos/{evento.id}/editar", data=_datos_evento(tenis.id))
        db.refresh(evento)
        assert evento.deporte_id == tenis.id

    @pytest.mark.parametrize(
        ("cambios", "codigo", "mensaje"),
        [
            ({"equipo_local": ""}, 422, "El equipo local debe tener entre 1 y 100 caracteres"),
            ({"equipo_local": "LDU", "equipo_visitante": "ldu"}, 422, "Los equipos deben ser distintos"),
            ({"inicia_en": "no es fecha"}, 422, "Ingresa una fecha de inicio válida"),
            ({"inicia_en": "2000-01-01T10:00"}, 400, "La fecha de inicio debe ser futura"),
            ({"deporte_id": "999"}, 404, "Deporte no encontrado"),
        ],
    )
    def test_datos_invalidos_no_guardan_y_muestran_el_error(self, admin, db, cambios, codigo, mensaje):
        evento = crear_evento(db, equipo_local="Original")
        respuesta = admin.post(f"/admin/eventos/{evento.id}/editar", data=_datos_evento(evento.deporte_id, **cambios))
        assert respuesta.status_code == codigo and mensaje in respuesta.text
        db.refresh(evento)
        assert evento.equipo_local == "Original"

    def test_evento_cerrado_400(self, admin, db):
        evento = crear_evento(db, estado=EstadoEvento.FINALIZADO, equipo_local="Original")
        respuesta = admin.post(f"/admin/eventos/{evento.id}/editar", data=_datos_evento(evento.deporte_id))
        assert respuesta.status_code == 400 and "Solo se puede editar un evento programado" in respuesta.text
        db.refresh(evento)
        assert evento.equipo_local == "Original"

    def test_evento_inexistente_404(self, admin, db):
        deporte = crear_deporte(db)
        assert admin.post(f"/admin/eventos/{uuid.uuid4()}/editar", data=_datos_evento(deporte.id)).status_code == 404


class TestCargarCuotasDesdeLaPantalla:
    def test_carga_las_tres_cuotas(self, admin, db):
        evento = crear_evento(db)
        datos = {"cuota_local": "2.10", "cuota_empate": "3.20", "cuota_visitante": "3.40"}
        respuesta = admin.post(f"/admin/eventos/{evento.id}/cuotas", data=datos)
        assert respuesta.status_code == 200 and "Se cargaron 3 cuotas" in respuesta.text
        cuotas = _cuotas_del_evento(db, evento)
        assert {s: c.valor for s, c in cuotas.items()} == {
            TipoSeleccion.LOCAL: Decimal("2.10"),
            TipoSeleccion.EMPATE: Decimal("3.20"),
            TipoSeleccion.VISITANTE: Decimal("3.40"),
        }

    def test_sin_empate_carga_solo_local_y_visitante(self, admin, db):
        evento = crear_evento(db)
        datos = {"cuota_local": "1.50", "cuota_empate": "", "cuota_visitante": "2.60"}
        admin.post(f"/admin/eventos/{evento.id}/cuotas", data=datos)
        assert set(_cuotas_del_evento(db, evento)) == {TipoSeleccion.LOCAL, TipoSeleccion.VISITANTE}

    @pytest.mark.parametrize(
        "datos",
        [
            {"cuota_local": "1.00", "cuota_visitante": "2.00"},
            {"cuota_local": "abc", "cuota_visitante": "2.00"},
            {"cuota_local": "", "cuota_visitante": "2.00"},
            {"cuota_local": "2.00", "cuota_visitante": "2.00", "cuota_empate": "0.50"},
            {"cuota_local": "2.123", "cuota_visitante": "2.00"},
        ],
    )
    def test_valores_invalidos_422_y_no_guarda_nada(self, admin, db, datos):
        evento = crear_evento(db)
        respuesta = admin.post(f"/admin/eventos/{evento.id}/cuotas", data=datos)
        assert respuesta.status_code == 422
        assert "Cada cuota debe ser un número mayor que 1.00" in respuesta.text
        assert _cuotas_del_evento(db, evento) == {}

    def test_conserva_lo_escrito_tras_un_error(self, admin, db):
        evento = crear_evento(db)
        respuesta = admin.post(
            f"/admin/eventos/{evento.id}/cuotas", data={"cuota_local": "2.50", "cuota_visitante": "1.00"}
        )
        assert 'value="2.50"' in respuesta.text

    def test_evento_cerrado_400(self, admin, db):
        evento = crear_evento(db, estado=EstadoEvento.CANCELADO)
        respuesta = admin.post(
            f"/admin/eventos/{evento.id}/cuotas", data={"cuota_local": "2.00", "cuota_visitante": "3.00"}
        )
        assert respuesta.status_code == 400
        assert "Solo se pueden cargar cuotas a un evento programado" in respuesta.text

    def test_si_ya_tiene_cuotas_no_ofrece_el_formulario_y_el_post_da_409(self, admin, db):
        evento = _evento_con_cuotas(db)
        assert "Cargar cuotas" not in admin.get(f"/admin/eventos/{evento.id}").text
        respuesta = admin.post(
            f"/admin/eventos/{evento.id}/cuotas", data={"cuota_local": "5.00", "cuota_visitante": "6.00"}
        )
        assert respuesta.status_code == 409 and "ya tiene cuota para: LOCAL, VISITANTE" in respuesta.text

    def test_evento_inexistente_404(self, admin):
        respuesta = admin.post(
            f"/admin/eventos/{uuid.uuid4()}/cuotas", data={"cuota_local": "2.00", "cuota_visitante": "3.00"}
        )
        assert respuesta.status_code == 404


class TestEditarCuotaDesdeLaPantalla:
    def test_cambia_el_valor_y_no_toca_otras_cuotas(self, admin, db):
        evento = _evento_con_cuotas(db)
        cuota = _cuotas_del_evento(db, evento)[TipoSeleccion.LOCAL]
        respuesta = admin.post(f"/admin/cuotas/{cuota.id}/editar", data={"valor": "2.75"})
        assert respuesta.status_code == 200 and "Cuota actualizada a 2.75" in respuesta.text
        cuotas = _cuotas_del_evento(db, evento)
        assert cuotas[TipoSeleccion.LOCAL].valor == Decimal("2.75")
        assert cuotas[TipoSeleccion.VISITANTE].valor == Decimal("3.00")

    def test_desactiva_y_reactiva(self, admin, db):
        evento = _evento_con_cuotas(db)
        cuota = _cuotas_del_evento(db, evento)[TipoSeleccion.LOCAL]
        assert "Cuota desactivada" in admin.post(f"/admin/cuotas/{cuota.id}/editar", data={"activa": "false"}).text
        assert _cuotas_del_evento(db, evento)[TipoSeleccion.LOCAL].activa is False
        assert "Cuota activada" in admin.post(f"/admin/cuotas/{cuota.id}/editar", data={"activa": "true"}).text
        assert _cuotas_del_evento(db, evento)[TipoSeleccion.LOCAL].activa is True

    @pytest.mark.parametrize("valor", ["1.00", "abc", "0", "-3"])
    def test_valor_invalido_422(self, admin, db, valor):
        evento = _evento_con_cuotas(db)
        cuota = _cuotas_del_evento(db, evento)[TipoSeleccion.LOCAL]
        respuesta = admin.post(f"/admin/cuotas/{cuota.id}/editar", data={"valor": valor})
        assert respuesta.status_code == 422
        assert _cuotas_del_evento(db, evento)[TipoSeleccion.LOCAL].valor == Decimal("2.00")

    def test_sin_datos_422(self, admin, db):
        cuota = _evento_con_cuotas(db).cuotas[0]
        respuesta = admin.post(f"/admin/cuotas/{cuota.id}/editar", data={})
        assert respuesta.status_code == 422 and "al menos un campo" in respuesta.text

    def test_no_cambia_el_valor_de_un_evento_cerrado(self, admin, db):
        evento = _evento_con_cuotas(db, estado=EstadoEvento.FINALIZADO)
        cuota = _cuotas_del_evento(db, evento)[TipoSeleccion.LOCAL]
        respuesta = admin.post(f"/admin/cuotas/{cuota.id}/editar", data={"valor": "9.00"})
        assert respuesta.status_code == 400
        assert "Solo se puede cambiar el valor de un evento programado" in respuesta.text
        assert _cuotas_del_evento(db, evento)[TipoSeleccion.LOCAL].valor == Decimal("2.00")

    def test_cuota_inexistente_o_id_invalido_404(self, admin):
        assert admin.post(f"/admin/cuotas/{uuid.uuid4()}/editar", data={"valor": "2.00"}).status_code == 404
        assert admin.post("/admin/cuotas/abc/editar", data={"valor": "2.00"}).status_code == 404


RESUMEN_LIQUIDACION = {
    "selecciones_acertadas": 2,
    "selecciones_fallidas": 1,
    "boletos_ganados": 3,
    "boletos_perdidos": 4,
    "boletos_pendientes": 5,
    "premios_acreditados": Decimal("30.00"),
}
RESUMEN_CANCELACION = {
    "selecciones_anuladas": 2,
    "boletos_recalculados": 1,
    "boletos_reembolsados": 6,
    "monto_reembolsado": Decimal("42.50"),
}


@pytest.fixture()
def liquidacion(monkeypatch):
    """Parchea las funciones de Daniel y registra con qué evento se llamaron."""
    llamadas = {"liquidar": [], "cancelar": []}

    def liquidar(db, evento_id):
        llamadas["liquidar"].append(evento_id)
        return RESUMEN_LIQUIDACION

    def cancelar(db, evento_id):
        llamadas["cancelar"].append(evento_id)
        return RESUMEN_CANCELACION

    monkeypatch.setattr("app.modules.apuestas.liquidacion.liquidar_evento", liquidar, raising=False)
    monkeypatch.setattr("app.modules.apuestas.liquidacion.procesar_cancelacion_evento", cancelar, raising=False)
    return llamadas


def _estado_guardado(db, evento):
    db.expire_all()
    guardado = db.get(Evento, evento.id)
    return guardado.estado, guardado.resultado


class TestAccesoCierre:
    @pytest.mark.parametrize("accion", ["resultado", "cancelar"])
    def test_sin_sesion_redirige_y_no_cierra_nada(self, client, db, liquidacion, accion):
        evento = _evento_con_cuotas(db)
        respuesta = client.post(
            f"/admin/eventos/{evento.id}/{accion}", data={"resultado": "LOCAL"}, follow_redirects=False
        )
        assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/login")
        assert _estado_guardado(db, evento) == (EstadoEvento.PROGRAMADO, None)
        assert liquidacion == {"liquidar": [], "cancelar": []}

    @pytest.mark.parametrize("accion", ["resultado", "cancelar"])
    def test_usuario_comun_redirige_y_no_cierra_nada(self, comun, db, liquidacion, accion):
        evento = _evento_con_cuotas(db)
        respuesta = comun.post(
            f"/admin/eventos/{evento.id}/{accion}", data={"resultado": "LOCAL"}, follow_redirects=False
        )
        assert (respuesta.status_code, respuesta.headers["location"]) == (303, "/")
        assert _estado_guardado(db, evento) == (EstadoEvento.PROGRAMADO, None)
        assert liquidacion == {"liquidar": [], "cancelar": []}


class TestFormulariosDeCierre:
    @pytest.mark.parametrize("estado", [EstadoEvento.PROGRAMADO, EstadoEvento.EN_VIVO])
    def test_un_evento_abierto_ofrece_resultado_y_cancelacion(self, admin, db, estado):
        evento = _evento_con_cuotas(db, estado=estado)
        html = admin.get(f"/admin/eventos/{evento.id}").text
        assert f'action="/admin/eventos/{evento.id}/resultado"' in html
        assert f'action="/admin/eventos/{evento.id}/cancelar"' in html

    @pytest.mark.parametrize("estado", [EstadoEvento.FINALIZADO, EstadoEvento.CANCELADO])
    def test_un_evento_cerrado_ya_no_los_ofrece(self, admin, db, estado):
        evento = _evento_con_cuotas(db, estado=estado, resultado=TipoSeleccion.LOCAL if estado == EstadoEvento.FINALIZADO else None)
        html = admin.get(f"/admin/eventos/{evento.id}").text
        assert "/resultado" not in html and "/cancelar" not in html

    def test_solo_ofrece_los_resultados_que_tienen_cuota(self, admin, db):
        evento = _evento_con_cuotas(db, equipo_local="Barcelona", equipo_visitante="Aucas")
        html = admin.get(f"/admin/eventos/{evento.id}").text
        assert 'value="LOCAL"' in html and 'value="VISITANTE"' in html and 'value="EMPATE"' not in html
        assert "Gana Barcelona" in html and "Gana Aucas" in html

    def test_sin_cuotas_pide_cargarlas_antes_de_registrar_resultado(self, admin, db):
        evento = crear_evento(db)
        html = admin.get(f"/admin/eventos/{evento.id}").text
        assert "antes de registrar un resultado" in html and 'name="resultado"' not in html

    def test_un_evento_finalizado_muestra_el_resultado_final(self, admin, db):
        evento = _evento_con_cuotas(
            db, estado=EstadoEvento.FINALIZADO, resultado=TipoSeleccion.VISITANTE, equipo_visitante="Aucas"
        )
        html = admin.get(f"/admin/eventos/{evento.id}").text
        assert "Resultado final" in html and "gana Aucas" in html


class TestRegistrarResultadoDesdeLaPantalla:
    def test_finaliza_el_evento_liquida_y_muestra_el_resumen(self, admin, db, liquidacion):
        evento = _evento_con_cuotas(db)
        respuesta = admin.post(f"/admin/eventos/{evento.id}/resultado", data={"resultado": "LOCAL"})
        assert respuesta.status_code == 200
        assert "Boletos ganados: 3, perdidos: 4, pendientes: 5" in respuesta.text
        assert "Premios acreditados: 30.00" in respuesta.text
        assert _estado_guardado(db, evento) == (EstadoEvento.FINALIZADO, TipoSeleccion.LOCAL)
        assert liquidacion["liquidar"] == [evento.id]
        assert "Resultado final" in respuesta.text and "/resultado" not in respuesta.text

    def test_resultado_sin_cuota_en_el_evento_400(self, admin, db, liquidacion):
        evento = _evento_con_cuotas(db)
        respuesta = admin.post(f"/admin/eventos/{evento.id}/resultado", data={"resultado": "EMPATE"})
        assert respuesta.status_code == 400 and "El resultado no es válido para este evento" in respuesta.text
        assert _estado_guardado(db, evento) == (EstadoEvento.PROGRAMADO, None)
        assert liquidacion["liquidar"] == []

    @pytest.mark.parametrize("valor", ["", "GANA", "local"])
    def test_resultado_que_no_existe_422(self, admin, db, liquidacion, valor):
        evento = _evento_con_cuotas(db)
        respuesta = admin.post(f"/admin/eventos/{evento.id}/resultado", data={"resultado": valor})
        assert respuesta.status_code == 422 and "Elige un resultado válido" in respuesta.text
        assert liquidacion["liquidar"] == []

    def test_evento_cerrado_400(self, admin, db, liquidacion):
        evento = _evento_con_cuotas(db, estado=EstadoEvento.CANCELADO)
        respuesta = admin.post(f"/admin/eventos/{evento.id}/resultado", data={"resultado": "LOCAL"})
        assert respuesta.status_code == 400 and "El evento ya fue cerrado" in respuesta.text
        assert liquidacion["liquidar"] == []

    def test_evento_inexistente_o_id_invalido_404(self, admin, liquidacion):
        assert admin.post(f"/admin/eventos/{uuid.uuid4()}/resultado", data={"resultado": "LOCAL"}).status_code == 404
        assert admin.post("/admin/eventos/abc/resultado", data={"resultado": "LOCAL"}).status_code == 404

    def test_si_la_liquidacion_falla_hay_rollback_y_mensaje_amable(self, admin, db, monkeypatch):
        evento = _evento_con_cuotas(db)

        def liquidar_con_error(db, evento_id):
            raise RuntimeError("falla interna")

        monkeypatch.setattr("app.modules.apuestas.liquidacion.liquidar_evento", liquidar_con_error, raising=False)
        respuesta = admin.post(f"/admin/eventos/{evento.id}/resultado", data={"resultado": "LOCAL"})
        assert respuesta.status_code == 500
        assert "no se guardó ningún cambio" in respuesta.text and "falla interna" not in respuesta.text
        assert _estado_guardado(db, evento) == (EstadoEvento.PROGRAMADO, None)


class TestCancelarDesdeLaPantalla:
    def test_cancela_el_evento_y_muestra_los_reembolsos(self, admin, db, liquidacion):
        evento = _evento_con_cuotas(db)
        respuesta = admin.post(f"/admin/eventos/{evento.id}/cancelar")
        assert respuesta.status_code == 200
        assert "Evento cancelado. Boletos reembolsados: 6. Monto reembolsado: 42.50" in respuesta.text
        assert _estado_guardado(db, evento) == (EstadoEvento.CANCELADO, None)
        assert liquidacion["cancelar"] == [evento.id] and liquidacion["liquidar"] == []

    @pytest.mark.parametrize("estado", [EstadoEvento.FINALIZADO, EstadoEvento.CANCELADO])
    def test_evento_cerrado_400(self, admin, db, liquidacion, estado):
        evento = _evento_con_cuotas(db, estado=estado)
        respuesta = admin.post(f"/admin/eventos/{evento.id}/cancelar")
        assert respuesta.status_code == 400 and "El evento ya fue cerrado" in respuesta.text
        assert liquidacion["cancelar"] == []

    def test_evento_inexistente_o_id_invalido_404(self, admin, liquidacion):
        assert admin.post(f"/admin/eventos/{uuid.uuid4()}/cancelar").status_code == 404
        assert admin.post("/admin/eventos/abc/cancelar").status_code == 404

    def test_si_el_reembolso_falla_hay_rollback_y_mensaje_amable(self, admin, db, monkeypatch):
        evento = _evento_con_cuotas(db)

        def cancelar_con_error(db, evento_id):
            raise RuntimeError("falla interna")

        monkeypatch.setattr(
            "app.modules.apuestas.liquidacion.procesar_cancelacion_evento", cancelar_con_error, raising=False
        )
        respuesta = admin.post(f"/admin/eventos/{evento.id}/cancelar")
        assert respuesta.status_code == 500 and "no se guardó ningún cambio" in respuesta.text
        assert _estado_guardado(db, evento) == (EstadoEvento.PROGRAMADO, None)
