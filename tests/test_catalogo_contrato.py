"""Contrato de catálogo que consume el módulo de apuestas."""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.db.enums import EstadoEvento, TipoSeleccion
from app.modules.catalogo import service
from tests.factories import crear_cuota, crear_evento


def _error(funcion, *args):
    with pytest.raises(HTTPException) as info:
        funcion(*args)
    return info.value


class TestObtenerEvento:
    def test_devuelve_el_evento(self, db):
        evento = crear_evento(db)
        assert service.obtener_evento(db, evento.id).id == evento.id

    def test_lanza_404_si_no_existe(self, db):
        error = _error(service.obtener_evento, db, uuid.uuid4())
        assert (error.status_code, error.detail) == (404, "Evento no encontrado")


class TestObtenerCuota:
    def test_devuelve_la_cuota_con_su_evento(self, db):
        cuota = crear_cuota(db)
        db.expire_all()
        encontrada = service.obtener_cuota(db, cuota.id)
        assert encontrada.evento.equipo_local == "Barcelona"

    def test_lanza_404_si_no_existe(self, db):
        error = _error(service.obtener_cuota, db, uuid.uuid4())
        assert (error.status_code, error.detail) == (404, "Cuota no encontrada")


class TestObtenerCuotas:
    def test_devuelve_un_diccionario_por_id_con_evento(self, db):
        evento = crear_evento(db)
        local = crear_cuota(db, evento, TipoSeleccion.LOCAL)
        visitante = crear_cuota(db, evento, TipoSeleccion.VISITANTE, Decimal("3.00"))
        db.expire_all()
        resultado = service.obtener_cuotas(db, [local.id, visitante.id])
        assert set(resultado) == {local.id, visitante.id}
        assert resultado[local.id].evento.id == evento.id

    def test_omite_los_ids_inexistentes(self, db):
        cuota = crear_cuota(db)
        resultado = service.obtener_cuotas(db, [cuota.id, uuid.uuid4()])
        assert list(resultado) == [cuota.id]

    def test_sin_ids_devuelve_vacio(self, db):
        assert service.obtener_cuotas(db, []) == {}


class TestObtenerCuotaParaApuesta:
    def test_caso_feliz_devuelve_la_cuota_con_evento(self, db):
        cuota = crear_cuota(db, valor=Decimal("2.50"))
        validada = service.obtener_cuota_para_apuesta(db, cuota.id)
        assert validada.id == cuota.id
        assert validada.valor == Decimal("2.50")
        assert validada.evento.equipo_visitante == "LDU"

    def test_cuota_inexistente_404(self, db):
        error = _error(service.obtener_cuota_para_apuesta, db, uuid.uuid4())
        assert (error.status_code, error.detail) == (404, "Cuota no encontrada")

    def test_cuota_inactiva_400(self, db):
        cuota = crear_cuota(db)
        cuota.activa = False
        db.commit()
        error = _error(service.obtener_cuota_para_apuesta, db, cuota.id)
        assert (error.status_code, error.detail) == (400, "La cuota no está activa")

    @pytest.mark.parametrize("estado", [EstadoEvento.EN_VIVO, EstadoEvento.FINALIZADO, EstadoEvento.CANCELADO])
    def test_evento_que_no_esta_programado_400(self, db, estado):
        cuota = crear_cuota(db, crear_evento(db, estado=estado))
        error = _error(service.obtener_cuota_para_apuesta, db, cuota.id)
        assert (error.status_code, error.detail) == (400, "El evento no acepta apuestas")

    def test_evento_que_ya_inicio_400(self, db):
        ayer = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        cuota = crear_cuota(db, crear_evento(db, inicia_en=ayer))
        error = _error(service.obtener_cuota_para_apuesta, db, cuota.id)
        assert (error.status_code, error.detail) == (400, "El evento ya inició")
