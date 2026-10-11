"""Tests de procesar_cancelacion_evento (Integrante C): reembolsos y combinadas recalculadas."""
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.enums import EstadoBoleto, EstadoEvento, EstadoSeleccion, TipoSeleccion, TipoTransaccion
from app.modules.apuestas import service
from app.modules.apuestas.liquidacion import liquidar_evento, procesar_cancelacion_evento
from app.modules.billetera.models import Transaccion
from tests.apuestas_utils import ana, catalogo_simulado, deporte  # noqa: F401
from tests.apuestas_utils import datos_boleto, nueva_cuota


def _cancelar(db, evento):
    """Simula lo que hace catálogo al cancelar: cierra el evento y procesa los boletos."""
    evento.estado = EstadoEvento.CANCELADO
    db.flush()
    resumen = procesar_cancelacion_evento(db, evento.id)
    db.commit()
    return resumen


def _finalizar(db, evento, resultado):
    evento.estado = EstadoEvento.FINALIZADO
    evento.resultado = resultado
    db.flush()
    resumen = liquidar_evento(db, evento.id)
    db.commit()
    return resumen


def _apostar(db, usuario, monto, *cuotas):
    boleto, _ = service.crear_boleto(db, usuario, datos_boleto(monto, *cuotas))
    return boleto


def _transacciones(db, usuario, tipo):
    return list(
        db.scalars(select(Transaccion).where(Transaccion.usuario_id == usuario.id, Transaccion.tipo == tipo))
    )


def _saldo(db, usuario):
    db.refresh(usuario)
    return usuario.saldo


class TestReembolso:
    def test_boleto_simple_se_reembolsa(self, db, ana, deporte):
        cuota = nueva_cuota(db, deporte, "2.00")
        boleto = _apostar(db, ana, "10.00", cuota)

        resumen = _cancelar(db, cuota.evento)

        assert resumen == {
            "selecciones_anuladas": 1,
            "boletos_recalculados": 0,
            "boletos_reembolsados": 1,
            "monto_reembolsado": Decimal("10.00"),
        }
        assert boleto.estado == EstadoBoleto.REEMBOLSADO
        assert boleto.liquidado_en is not None
        assert boleto.selecciones[0].estado == EstadoSeleccion.ANULADA
        assert _saldo(db, ana) == Decimal("100.00")

        [reembolso] = _transacciones(db, ana, TipoTransaccion.REEMBOLSO)
        assert reembolso.monto == Decimal("10.00")
        assert reembolso.boleto_id == boleto.id

    def test_combinada_con_todos_sus_eventos_cancelados_se_reembolsa(self, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "2.00")
        c2 = nueva_cuota(db, deporte, "1.50")
        boleto = _apostar(db, ana, "10.00", c1, c2)

        primero = _cancelar(db, c1.evento)
        assert primero["boletos_recalculados"] == 1
        assert boleto.estado == EstadoBoleto.PENDIENTE

        segundo = _cancelar(db, c2.evento)
        assert segundo["boletos_reembolsados"] == 1
        assert boleto.estado == EstadoBoleto.REEMBOLSADO
        assert _saldo(db, ana) == Decimal("100.00")


class TestRecalculo:
    def test_combinada_se_recalcula_y_espera(self, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "2.00")
        c2 = nueva_cuota(db, deporte, "1.50")
        boleto = _apostar(db, ana, "10.00", c1, c2)  # 3.00 -> 30.00

        resumen = _cancelar(db, c2.evento)

        assert resumen["boletos_recalculados"] == 1
        assert resumen["boletos_reembolsados"] == 0
        assert boleto.cuota_total == Decimal("2.00")
        assert boleto.ganancia_potencial == Decimal("20.00")
        assert boleto.estado == EstadoBoleto.PENDIENTE
        assert boleto.liquidado_en is None
        assert _saldo(db, ana) == Decimal("90.00")

        _finalizar(db, c1.evento, TipoSeleccion.LOCAL)
        assert boleto.estado == EstadoBoleto.GANADO
        assert _saldo(db, ana) == Decimal("110.00")  # paga el premio recalculado: 20.00

    def test_si_lo_que_queda_ya_acerto_gana_al_cancelar(self, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "2.00")
        c2 = nueva_cuota(db, deporte, "1.50")
        boleto = _apostar(db, ana, "10.00", c1, c2)
        _finalizar(db, c1.evento, TipoSeleccion.LOCAL)  # acierta, el boleto espera
        assert boleto.estado == EstadoBoleto.PENDIENTE

        _cancelar(db, c2.evento)

        assert boleto.estado == EstadoBoleto.GANADO
        assert boleto.ganancia_potencial == Decimal("20.00")
        [premio] = _transacciones(db, ana, TipoTransaccion.PREMIO)
        assert premio.monto == Decimal("20.00")
        assert _saldo(db, ana) == Decimal("110.00")

    def test_recalculo_redondea_half_up(self, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "1.85")
        c2 = nueva_cuota(db, deporte, "2.10")
        c3 = nueva_cuota(db, deporte, "1.30")
        boleto = _apostar(db, ana, "7.33", c1, c2, c3)

        _cancelar(db, c3.evento)

        # 1.85 x 2.10 = 3.885 -> 3.89 ; 7.33 x 3.89 = 28.5137 -> 28.51
        assert boleto.cuota_total == Decimal("3.89")
        assert boleto.ganancia_potencial == Decimal("28.51")

    def test_la_cuota_congelada_no_cambia(self, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "2.00")
        c2 = nueva_cuota(db, deporte, "1.50")
        boleto = _apostar(db, ana, "10.00", c1, c2)
        c1.valor = Decimal("9.00")  # el admin edita la cuota después de apostar
        db.commit()

        _cancelar(db, c2.evento)

        assert boleto.cuota_total == Decimal("2.00")


class TestBoletosYaLiquidados:
    def test_boleto_perdido_no_se_toca(self, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "2.00")
        c2 = nueva_cuota(db, deporte, "1.50")
        boleto = _apostar(db, ana, "10.00", c1, c2)
        _finalizar(db, c1.evento, TipoSeleccion.VISITANTE)  # pierde
        liquidado_en = boleto.liquidado_en

        resumen = _cancelar(db, c2.evento)

        assert resumen["boletos_recalculados"] == resumen["boletos_reembolsados"] == 0
        assert boleto.estado == EstadoBoleto.PERDIDO
        assert boleto.liquidado_en == liquidado_en
        assert boleto.cuota_total == Decimal("3.00")
        assert _transacciones(db, ana, TipoTransaccion.REEMBOLSO) == []
        assert _saldo(db, ana) == Decimal("90.00")

    def test_ejecutar_dos_veces_no_reembolsa_dos_veces(self, db, ana, deporte):
        cuota = nueva_cuota(db, deporte, "2.00")
        _apostar(db, ana, "10.00", cuota)
        _cancelar(db, cuota.evento)

        repetido = procesar_cancelacion_evento(db, cuota.evento_id)
        db.commit()

        assert repetido == {
            "selecciones_anuladas": 0,
            "boletos_recalculados": 0,
            "boletos_reembolsados": 0,
            "monto_reembolsado": Decimal("0.00"),
        }
        assert len(_transacciones(db, ana, TipoTransaccion.REEMBOLSO)) == 1
        assert _saldo(db, ana) == Decimal("100.00")


class TestContrato:
    def test_no_hace_commit(self, db, ana, deporte):
        cuota = nueva_cuota(db, deporte, "2.00")
        boleto = _apostar(db, ana, "10.00", cuota)

        procesar_cancelacion_evento(db, cuota.evento_id)
        db.rollback()

        db.refresh(boleto)
        assert boleto.estado == EstadoBoleto.PENDIENTE
        assert boleto.selecciones[0].estado == EstadoSeleccion.PENDIENTE
        assert _saldo(db, ana) == Decimal("90.00")

    def test_evento_inexistente_da_404(self, db):
        with pytest.raises(HTTPException) as error:
            procesar_cancelacion_evento(db, uuid4())
        assert error.value.status_code == 404

    def test_libro_mayor_cuadra_con_el_saldo(self, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "2.00")
        c2 = nueva_cuota(db, deporte, "1.50")
        c3 = nueva_cuota(db, deporte, "3.00")
        _apostar(db, ana, "10.00", c1)  # reembolso 10.00
        _apostar(db, ana, "20.00", c2, c3)  # se recalcula a 3.00 -> gana 60.00
        _apostar(db, ana, "5.00", c3)  # gana 15.00

        _cancelar(db, c1.evento)
        _cancelar(db, c2.evento)
        _finalizar(db, c3.evento, TipoSeleccion.LOCAL)

        # 100 - 10 - 20 - 5 + 10 + 60 + 15 = 150.00
        saldo = _saldo(db, ana)
        assert saldo == Decimal("150.00")
        suma = db.scalar(select(func.sum(Transaccion.monto)).where(Transaccion.usuario_id == ana.id))
        assert suma == saldo
