"""Registrar resultado y cancelar un evento: una sola transacción con la liquidación de apuestas."""
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.db.enums import EstadoEvento, TipoSeleccion
from app.modules.catalogo import service
from tests.factories import crear_cuota, crear_evento

RUTA_LIQUIDAR = "app.modules.apuestas.liquidacion.liquidar_evento"
RUTA_CANCELAR = "app.modules.apuestas.liquidacion.procesar_cancelacion_evento"

RESUMEN_LIQUIDACION = {
    "selecciones_acertadas": 2,
    "selecciones_fallidas": 1,
    "boletos_ganados": 1,
    "boletos_perdidos": 1,
    "boletos_pendientes": 0,
    "premios_acreditados": Decimal("30.00"),
}
RESUMEN_CANCELACION = {
    "selecciones_anuladas": 2,
    "boletos_recalculados": 1,
    "boletos_reembolsados": 1,
    "monto_reembolsado": Decimal("10.00"),
}


def _evento_con_cuotas(db, **campos):
    evento = crear_evento(db, **campos)
    crear_cuota(db, evento, TipoSeleccion.LOCAL, Decimal("2.00"))
    crear_cuota(db, evento, TipoSeleccion.VISITANTE, Decimal("3.00"))
    return evento


@pytest.fixture()
def liquidacion(monkeypatch):
    """Parchea las dos funciones de Daniel y registra con qué se llamaron."""
    llamadas = {"liquidar": [], "cancelar": []}

    def liquidar(db, evento_id):
        llamadas["liquidar"].append(evento_id)
        return RESUMEN_LIQUIDACION

    def cancelar(db, evento_id):
        llamadas["cancelar"].append(evento_id)
        return RESUMEN_CANCELACION

    monkeypatch.setattr(RUTA_LIQUIDAR, liquidar, raising=False)
    monkeypatch.setattr(RUTA_CANCELAR, cancelar, raising=False)
    return llamadas


def _error(funcion, *args) -> HTTPException:
    with pytest.raises(HTTPException) as info:
        funcion(*args)
    return info.value


class TestRegistrarResultado:
    def test_finaliza_el_evento_y_liquida_una_sola_vez(self, db, liquidacion):
        evento = _evento_con_cuotas(db)
        resultado, resumen = service.registrar_resultado(db, evento.id, TipoSeleccion.LOCAL)
        assert resultado.estado == EstadoEvento.FINALIZADO
        assert resultado.resultado == TipoSeleccion.LOCAL
        assert liquidacion["liquidar"] == [evento.id]
        assert resumen == RESUMEN_LIQUIDACION

    def test_el_estado_queda_guardado_en_la_base(self, db, liquidacion):
        evento = _evento_con_cuotas(db)
        service.registrar_resultado(db, evento.id, TipoSeleccion.VISITANTE)
        db.expire_all()
        guardado = service.obtener_evento(db, evento.id)
        assert (guardado.estado, guardado.resultado) == (EstadoEvento.FINALIZADO, TipoSeleccion.VISITANTE)

    def test_acepta_un_evento_en_vivo(self, db, liquidacion):
        evento = _evento_con_cuotas(db, estado=EstadoEvento.EN_VIVO)
        evento_final, _ = service.registrar_resultado(db, evento.id, TipoSeleccion.LOCAL)
        assert evento_final.estado == EstadoEvento.FINALIZADO

    def test_devuelve_todas_las_cuotas_del_evento(self, db, liquidacion):
        evento = _evento_con_cuotas(db)
        resultado, _ = service.registrar_resultado(db, evento.id, TipoSeleccion.LOCAL)
        assert len(resultado.cuotas) == 2

    def test_evento_inexistente_404(self, db, liquidacion):
        error = _error(service.registrar_resultado, db, uuid.uuid4(), TipoSeleccion.LOCAL)
        assert (error.status_code, error.detail) == (404, "Evento no encontrado")
        assert liquidacion["liquidar"] == []

    @pytest.mark.parametrize("estado", [EstadoEvento.FINALIZADO, EstadoEvento.CANCELADO])
    def test_evento_cerrado_400(self, db, liquidacion, estado):
        evento = _evento_con_cuotas(db, estado=estado)
        error = _error(service.registrar_resultado, db, evento.id, TipoSeleccion.LOCAL)
        assert (error.status_code, error.detail) == (400, "El evento ya fue cerrado")
        assert liquidacion["liquidar"] == []

    def test_resultado_sin_cuota_en_el_evento_400(self, db, liquidacion):
        evento = _evento_con_cuotas(db)
        error = _error(service.registrar_resultado, db, evento.id, TipoSeleccion.EMPATE)
        assert (error.status_code, error.detail) == (400, "El resultado no es válido para este evento")
        db.refresh(evento)
        assert evento.estado == EstadoEvento.PROGRAMADO and evento.resultado is None
        assert liquidacion["liquidar"] == []

    def test_resultado_en_evento_sin_cuotas_400(self, db, liquidacion):
        evento = crear_evento(db)
        error = _error(service.registrar_resultado, db, evento.id, TipoSeleccion.LOCAL)
        assert error.status_code == 400

    def test_si_la_liquidacion_falla_hace_rollback_y_relanza(self, db, monkeypatch):
        evento = _evento_con_cuotas(db)

        def liquidar_con_error(db, evento_id):
            raise RuntimeError("falla al liquidar")

        monkeypatch.setattr(RUTA_LIQUIDAR, liquidar_con_error, raising=False)

        with pytest.raises(RuntimeError, match="falla al liquidar"):
            service.registrar_resultado(db, evento.id, TipoSeleccion.LOCAL)

        db.expire_all()
        guardado = service.obtener_evento(db, evento.id)
        assert guardado.estado == EstadoEvento.PROGRAMADO
        assert guardado.resultado is None

    def test_si_la_liquidacion_lanza_http_tambien_hace_rollback(self, db, monkeypatch):
        evento = _evento_con_cuotas(db)

        def liquidar_con_http(db, evento_id):
            raise HTTPException(status_code=400, detail="Saldo inconsistente")

        monkeypatch.setattr(RUTA_LIQUIDAR, liquidar_con_http, raising=False)

        assert _error(service.registrar_resultado, db, evento.id, TipoSeleccion.LOCAL).status_code == 400
        db.expire_all()
        assert service.obtener_evento(db, evento.id).estado == EstadoEvento.PROGRAMADO


class TestCancelarEvento:
    def test_cancela_el_evento_y_procesa_los_reembolsos_una_vez(self, db, liquidacion):
        evento = _evento_con_cuotas(db)
        cancelado, resumen = service.cancelar_evento(db, evento.id)
        assert cancelado.estado == EstadoEvento.CANCELADO
        assert cancelado.resultado is None
        assert liquidacion["cancelar"] == [evento.id]
        assert liquidacion["liquidar"] == []
        assert resumen == RESUMEN_CANCELACION

    def test_el_estado_queda_guardado_en_la_base(self, db, liquidacion):
        evento = _evento_con_cuotas(db)
        service.cancelar_evento(db, evento.id)
        db.expire_all()
        assert service.obtener_evento(db, evento.id).estado == EstadoEvento.CANCELADO

    def test_acepta_un_evento_en_vivo(self, db, liquidacion):
        evento = _evento_con_cuotas(db, estado=EstadoEvento.EN_VIVO)
        assert service.cancelar_evento(db, evento.id)[0].estado == EstadoEvento.CANCELADO

    def test_evento_inexistente_404(self, db, liquidacion):
        error = _error(service.cancelar_evento, db, uuid.uuid4())
        assert (error.status_code, error.detail) == (404, "Evento no encontrado")

    @pytest.mark.parametrize("estado", [EstadoEvento.FINALIZADO, EstadoEvento.CANCELADO])
    def test_evento_cerrado_400(self, db, liquidacion, estado):
        evento = _evento_con_cuotas(db, estado=estado)
        error = _error(service.cancelar_evento, db, evento.id)
        assert (error.status_code, error.detail) == (400, "El evento ya fue cerrado")
        assert liquidacion["cancelar"] == []

    def test_si_el_reembolso_falla_hace_rollback_y_relanza(self, db, monkeypatch):
        evento = _evento_con_cuotas(db)

        def cancelar_con_error(db, evento_id):
            raise RuntimeError("falla al reembolsar")

        monkeypatch.setattr(RUTA_CANCELAR, cancelar_con_error, raising=False)

        with pytest.raises(RuntimeError, match="falla al reembolsar"):
            service.cancelar_evento(db, evento.id)

        db.expire_all()
        assert service.obtener_evento(db, evento.id).estado == EstadoEvento.PROGRAMADO
