"""Pantallas públicas del catálogo: detalle de evento y botones de cuota con HTMX."""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.enums import EstadoEvento, TipoSeleccion
from app.modules.usuarios import service as usuarios_service
from tests.factories import crear_cuota, crear_deporte, crear_evento

PANEL = 'id="panel-boleto"'


def _futuro(horas: int = 24) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=horas)


def _evento_con_cuotas(db, **campos):
    evento = crear_evento(db, **campos)
    crear_cuota(db, evento, TipoSeleccion.LOCAL, Decimal("2.10"))
    crear_cuota(db, evento, TipoSeleccion.EMPATE, Decimal("3.20"))
    crear_cuota(db, evento, TipoSeleccion.VISITANTE, Decimal("3.40"))
    return evento


@pytest.fixture()
def sesion(client, db):
    """Cliente con un usuario común que ya inició sesión."""
    usuarios_service.crear_usuario(db, "ana@correo.com", "ana", "secreta123")
    client.post("/login", data={"email": "ana@correo.com", "password": "secreta123"}, follow_redirects=False)
    return client


class TestDetalleEvento:
    def test_muestra_los_datos_y_las_cuotas(self, client, db):
        evento = _evento_con_cuotas(db, equipo_local="Barcelona SC", equipo_visitante="Emelec")
        html = client.get(f"/eventos/{evento.id}").text
        assert "Barcelona SC" in html and "Emelec" in html and "Fútbol" in html
        for valor in ("2.10", "3.20", "3.40"):
            assert valor in html

    def test_la_fecha_se_muestra_en_hora_de_ecuador(self, client, db):
        evento = crear_evento(db, inicia_en=datetime(2030, 5, 20, 22, 30))
        assert "20/05/2030 17:30" in client.get(f"/eventos/{evento.id}").text

    def test_no_muestra_cuotas_inactivas(self, client, db):
        evento = crear_evento(db)
        crear_cuota(db, evento, TipoSeleccion.LOCAL, Decimal("2.00"))
        apagada = crear_cuota(db, evento, TipoSeleccion.VISITANTE, Decimal("7.77"))
        apagada.activa = False
        db.commit()
        assert "7.77" not in client.get(f"/eventos/{evento.id}").text

    def test_evento_sin_cuotas_avisa(self, client, db):
        evento = crear_evento(db)
        assert "todavía no tiene cuotas" in client.get(f"/eventos/{evento.id}").text

    def test_deporte_sin_empate_no_lo_muestra(self, client, db):
        evento = crear_evento(db, crear_deporte(db, "Tenis"))
        crear_cuota(db, evento, TipoSeleccion.LOCAL)
        crear_cuota(db, evento, TipoSeleccion.VISITANTE)
        assert "Empate" not in client.get(f"/eventos/{evento.id}").text

    def test_funciona_para_cualquier_estado(self, client, db):
        deporte = crear_deporte(db)
        for estado in EstadoEvento:
            resultado = TipoSeleccion.LOCAL if estado == EstadoEvento.FINALIZADO else None
            evento = crear_evento(db, deporte, estado=estado, resultado=resultado)
            assert client.get(f"/eventos/{evento.id}").status_code == 200

    def test_finalizado_muestra_el_resultado(self, client, db):
        evento = _evento_con_cuotas(
            db, estado=EstadoEvento.FINALIZADO, resultado=TipoSeleccion.VISITANTE, equipo_visitante="Aucas"
        )
        html = client.get(f"/eventos/{evento.id}").text
        assert "Finalizado" in html and "Gana Aucas" in html

    def test_finalizado_con_empate(self, client, db):
        evento = _evento_con_cuotas(db, estado=EstadoEvento.FINALIZADO, resultado=TipoSeleccion.EMPATE)
        assert "Resultado" in client.get(f"/eventos/{evento.id}").text

    def test_cancelado_lo_indica(self, client, db):
        evento = _evento_con_cuotas(db, estado=EstadoEvento.CANCELADO)
        html = client.get(f"/eventos/{evento.id}").text
        assert "Cancelado" in html and "fue cancelado" in html

    def test_evento_inexistente_404_con_pagina(self, client):
        respuesta = client.get(f"/eventos/{uuid.uuid4()}")
        assert respuesta.status_code == 404 and "Evento no encontrado" in respuesta.text

    def test_id_que_no_es_uuid_404(self, client):
        assert client.get("/eventos/abc").status_code == 404


class TestBotonesDeCuota:
    def test_con_sesion_cada_cuota_es_un_boton_htmx(self, sesion, db):
        evento = _evento_con_cuotas(db)
        html = sesion.get(f"/eventos/{evento.id}").text
        assert html.count('hx-post="/web/boleto/agregar/') == 3
        for cuota in evento.cuotas:
            assert f'hx-post="/web/boleto/agregar/{cuota.id}"' in html
        assert 'hx-target="#panel-boleto"' in html and 'hx-swap="innerHTML"' in html

    def test_con_sesion_hay_panel_de_boleto(self, sesion, db):
        evento = _evento_con_cuotas(db)
        html = sesion.get(f"/eventos/{evento.id}").text
        assert PANEL in html and 'hx-get="/web/boleto/panel"' in html and 'hx-trigger="load"' in html
        assert "lg:grid-cols-3" in html

    def test_sin_sesion_la_cuota_enlaza_al_login(self, client, db):
        evento = _evento_con_cuotas(db)
        html = client.get(f"/eventos/{evento.id}").text
        assert "hx-post" not in html and PANEL not in html
        assert html.count('href="/login"') >= 3

    @pytest.mark.parametrize("estado", [EstadoEvento.EN_VIVO, EstadoEvento.FINALIZADO, EstadoEvento.CANCELADO])
    def test_evento_no_programado_no_tiene_botones(self, sesion, db, estado):
        evento = _evento_con_cuotas(db, estado=estado)
        assert "hx-post" not in sesion.get(f"/eventos/{evento.id}").text

    def test_evento_programado_que_ya_inicio_no_tiene_botones(self, sesion, db):
        evento = _evento_con_cuotas(db, inicia_en=_futuro(-1))
        assert "hx-post" not in sesion.get(f"/eventos/{evento.id}").text

    def test_cuota_inactiva_no_es_boton(self, sesion, db):
        evento = crear_evento(db)
        crear_cuota(db, evento, TipoSeleccion.LOCAL)
        apagada = crear_cuota(db, evento, TipoSeleccion.VISITANTE)
        apagada.activa = False
        db.commit()
        html = sesion.get(f"/eventos/{evento.id}").text
        assert html.count("hx-post") == 1 and f"/web/boleto/agregar/{apagada.id}" not in html


class TestListaConBoleto:
    def test_con_sesion_las_cuotas_son_botones_y_hay_panel(self, sesion, db):
        evento = _evento_con_cuotas(db)
        html = sesion.get("/eventos").text
        assert html.count('hx-post="/web/boleto/agregar/') == 3
        assert f'hx-post="/web/boleto/agregar/{evento.cuotas[0].id}"' in html
        assert html.count(PANEL) == 1 and "lg:grid-cols-3" in html

    def test_sin_sesion_enlazan_al_login_y_no_hay_panel(self, client, db):
        _evento_con_cuotas(db)
        html = client.get("/eventos").text
        assert "hx-post" not in html and PANEL not in html
        assert html.count('href="/login"') >= 3

    def test_el_fragmento_htmx_no_trae_el_panel(self, sesion, db):
        _evento_con_cuotas(db)
        html = sesion.get("/eventos", headers={"HX-Request": "true"}).text
        assert PANEL not in html and "<html" not in html and "hx-post" in html

    def test_la_tarjeta_enlaza_al_detalle(self, client, db):
        evento = _evento_con_cuotas(db)
        assert f'href="/eventos/{evento.id}"' in client.get("/eventos").text
