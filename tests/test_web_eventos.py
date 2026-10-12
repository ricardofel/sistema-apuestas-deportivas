from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.enums import EstadoEvento, TipoSeleccion
from tests.factories import crear_cuota, crear_deporte, crear_evento


def _futuro(horas: int) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=horas)


def test_sin_eventos_muestra_el_mensaje_vacio(client):
    respuesta = client.get("/eventos")
    assert respuesta.status_code == 200
    assert "No hay eventos disponibles por ahora" in respuesta.text


def test_lista_eventos_con_sus_cuotas(client, db):
    futbol = crear_deporte(db, "Fútbol")
    evento = crear_evento(db, futbol, equipo_local="Barcelona", equipo_visitante="LDU")
    crear_cuota(db, evento, TipoSeleccion.LOCAL, Decimal("2.10"))
    crear_cuota(db, evento, TipoSeleccion.EMPATE, Decimal("3.20"))
    crear_cuota(db, evento, TipoSeleccion.VISITANTE, Decimal("3.40"))

    html = client.get("/eventos").text

    assert "Barcelona" in html and "LDU" in html
    assert "Fútbol" in html
    for valor in ("2.10", "3.20", "3.40"):
        assert valor in html


def test_deporte_sin_empate_no_muestra_esa_cuota(client, db):
    evento = crear_evento(db, crear_deporte(db, "Tenis"))
    crear_cuota(db, evento, TipoSeleccion.LOCAL, Decimal("1.50"))
    crear_cuota(db, evento, TipoSeleccion.VISITANTE, Decimal("2.50"))
    html = client.get("/eventos").text
    assert "Local" in html and "Visitante" in html
    assert "Empate" not in html


def test_no_muestra_cuotas_inactivas(client, db):
    evento = crear_evento(db)
    cuota = crear_cuota(db, evento, TipoSeleccion.LOCAL, Decimal("7.77"))
    cuota.activa = False
    db.commit()
    assert "7.77" not in client.get("/eventos").text


def test_solo_muestra_eventos_programados_y_futuros(client, db):
    deporte = crear_deporte(db)
    crear_evento(db, deporte, equipo_local="Visible", inicia_en=_futuro(5))
    crear_evento(db, deporte, equipo_local="YaInicio", inicia_en=_futuro(-2))
    crear_evento(db, deporte, equipo_local="Cancelado", estado=EstadoEvento.CANCELADO)
    crear_evento(db, deporte, equipo_local="Finalizado", estado=EstadoEvento.FINALIZADO)
    # Solo la lista de partidos abiertos: los finalizados aparecen aparte, en "Últimos resultados".
    html = client.get("/eventos", headers={"HX-Request": "true"}).text
    assert "Visible" in html
    assert "YaInicio" not in html and "Cancelado" not in html and "Finalizado" not in html


def test_no_muestra_deportes_inactivos(client, db):
    deporte = crear_deporte(db, "Ajedrez")
    crear_evento(db, deporte, equipo_local="Magnus")
    deporte.activo = False
    db.commit()
    html = client.get("/eventos").text
    assert "Magnus" not in html and "Ajedrez" not in html


def test_ordena_por_fecha_de_inicio(client, db):
    deporte = crear_deporte(db)
    crear_evento(db, deporte, equipo_local="Tarde", inicia_en=_futuro(10))
    crear_evento(db, deporte, equipo_local="Temprano", inicia_en=_futuro(2))
    html = client.get("/eventos").text
    assert html.index("Temprano") < html.index("Tarde")


def test_filtra_por_deporte(client, db):
    futbol = crear_deporte(db, "Fútbol")
    tenis = crear_deporte(db, "Tenis")
    crear_evento(db, futbol, equipo_local="EquipoFutbol")
    crear_evento(db, tenis, equipo_local="JugadorTenis")

    solo_tenis = client.get(f"/eventos?deporte={tenis.id}").text
    assert "JugadorTenis" in solo_tenis and "EquipoFutbol" not in solo_tenis

    todos = client.get("/eventos").text
    assert "JugadorTenis" in todos and "EquipoFutbol" in todos


def test_htmx_devuelve_solo_el_fragmento(client, db):
    crear_evento(db, equipo_local="Barcelona")
    completa = client.get("/eventos").text
    fragmento = client.get("/eventos", headers={"HX-Request": "true"}).text
    assert "<html" in completa
    assert "<html" not in fragmento and "Barcelona" in fragmento


def test_restaurar_historial_htmx_devuelve_la_pagina_completa(client):
    respuesta = client.get("/eventos", headers={"HX-Request": "true", "HX-History-Restore-Request": "true"})
    assert "<html" in respuesta.text
