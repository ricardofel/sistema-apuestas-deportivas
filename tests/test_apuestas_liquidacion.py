"""Tests de liquidar_evento (Integrante C): ganados, perdidos, combinadas e idempotencia."""
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.enums import EstadoBoleto, EstadoEvento, EstadoSeleccion, TipoSeleccion, TipoTransaccion
from app.modules.apuestas import service
from app.modules.apuestas.liquidacion import liquidar_evento
from app.modules.billetera.models import Transaccion
from tests.apuestas_utils import ana, beto, catalogo_simulado, deporte  # noqa: F401
from tests.apuestas_utils import datos_boleto, nueva_cuota
from tests.factories import crear_cuota


def _finalizar(db, evento, resultado):
    """Simula lo que hace catálogo al registrar el resultado: cierra el evento y liquida."""
    evento.estado = EstadoEvento.FINALIZADO
    evento.resultado = resultado
    db.flush()
    resumen = liquidar_evento(db, evento.id)
    db.commit()
    return resumen


def _apostar(db, usuario, monto, *cuotas):
    boleto, _ = service.crear_boleto(db, usuario, datos_boleto(monto, *cuotas))
    return boleto


def _premios(db, usuario):
    return list(
        db.scalars(
            select(Transaccion).where(
                Transaccion.usuario_id == usuario.id, Transaccion.tipo == TipoTransaccion.PREMIO
            )
        )
    )


def _suma_libro_mayor(db, usuario):
    return db.scalar(select(func.sum(Transaccion.monto)).where(Transaccion.usuario_id == usuario.id))


class TestSimple:
    def test_ganada_paga_el_premio(self, db, ana, deporte):
        cuota = nueva_cuota(db, deporte, "2.00", TipoSeleccion.LOCAL)
        boleto = _apostar(db, ana, "10.00", cuota)

        resumen = _finalizar(db, cuota.evento, TipoSeleccion.LOCAL)

        assert resumen == {
            "selecciones_acertadas": 1,
            "selecciones_fallidas": 0,
            "boletos_ganados": 1,
            "boletos_perdidos": 0,
            "boletos_pendientes": 0,
            "premios_acreditados": Decimal("20.00"),
        }
        assert boleto.estado == EstadoBoleto.GANADO
        assert boleto.liquidado_en is not None
        assert boleto.selecciones[0].estado == EstadoSeleccion.ACERTADA
        db.refresh(ana)
        assert ana.saldo == Decimal("110.00")  # 100 - 10 + 20

        [premio] = _premios(db, ana)
        assert premio.monto == Decimal("20.00")
        assert premio.boleto_id == boleto.id

    def test_perdida_no_paga_nada(self, db, ana, deporte):
        cuota = nueva_cuota(db, deporte, "2.00", TipoSeleccion.LOCAL)
        boleto = _apostar(db, ana, "10.00", cuota)

        resumen = _finalizar(db, cuota.evento, TipoSeleccion.VISITANTE)

        assert resumen["selecciones_fallidas"] == 1
        assert resumen["boletos_perdidos"] == 1
        assert resumen["premios_acreditados"] == Decimal("0.00")
        assert boleto.estado == EstadoBoleto.PERDIDO
        assert boleto.liquidado_en is not None
        assert boleto.selecciones[0].estado == EstadoSeleccion.FALLIDA
        db.refresh(ana)
        assert ana.saldo == Decimal("90.00")
        assert _premios(db, ana) == []

    def test_varios_usuarios_en_el_mismo_evento(self, db, ana, beto, deporte):
        local = nueva_cuota(db, deporte, "2.00", TipoSeleccion.LOCAL)
        empate = crear_cuota(db, evento=local.evento, seleccion=TipoSeleccion.EMPATE, valor=Decimal("3.00"))
        _apostar(db, ana, "10.00", local)
        _apostar(db, beto, "10.00", empate)

        resumen = _finalizar(db, local.evento, TipoSeleccion.EMPATE)

        assert (resumen["boletos_ganados"], resumen["boletos_perdidos"]) == (1, 1)
        assert resumen["premios_acreditados"] == Decimal("30.00")
        db.refresh(ana)
        db.refresh(beto)
        assert (ana.saldo, beto.saldo) == (Decimal("90.00"), Decimal("120.00"))


class TestCombinada:
    def test_una_pierna_fallida_pierde_de_inmediato(self, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "2.00")
        c2 = nueva_cuota(db, deporte, "1.50")
        boleto = _apostar(db, ana, "10.00", c1, c2)

        resumen = _finalizar(db, c1.evento, TipoSeleccion.VISITANTE)

        assert resumen["boletos_perdidos"] == 1
        assert boleto.estado == EstadoBoleto.PERDIDO
        assert boleto.liquidado_en is not None
        # La otra pierna sigue pendiente: su partido aún no se juega.
        estados = {s.evento_id: s.estado for s in boleto.selecciones}
        assert estados[c2.evento_id] == EstadoSeleccion.PENDIENTE

    def test_un_boleto_perdido_no_cambia_al_liquidar_el_otro_evento(self, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "2.00")
        c2 = nueva_cuota(db, deporte, "1.50")
        boleto = _apostar(db, ana, "10.00", c1, c2)
        _finalizar(db, c1.evento, TipoSeleccion.VISITANTE)
        liquidado_en = boleto.liquidado_en

        resumen = _finalizar(db, c2.evento, TipoSeleccion.LOCAL)

        assert resumen["selecciones_acertadas"] == 1  # la selección sí se marca...
        assert resumen["boletos_ganados"] == 0  # ...pero el boleto ya estaba cerrado
        assert boleto.estado == EstadoBoleto.PERDIDO
        assert boleto.liquidado_en == liquidado_en
        assert _premios(db, ana) == []

    def test_espera_al_segundo_evento_y_luego_gana(self, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "2.00")
        c2 = nueva_cuota(db, deporte, "1.50")
        boleto = _apostar(db, ana, "10.00", c1, c2)  # cuota 3.00 -> ganancia 30.00

        primero = _finalizar(db, c1.evento, TipoSeleccion.LOCAL)
        assert primero["boletos_pendientes"] == 1
        assert boleto.estado == EstadoBoleto.PENDIENTE
        assert boleto.liquidado_en is None

        segundo = _finalizar(db, c2.evento, TipoSeleccion.LOCAL)
        assert segundo["boletos_ganados"] == 1
        assert segundo["premios_acreditados"] == Decimal("30.00")
        assert boleto.estado == EstadoBoleto.GANADO
        db.refresh(ana)
        assert ana.saldo == Decimal("120.00")  # 100 - 10 + 30

    def test_selecciones_anuladas_no_impiden_ganar(self, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "2.00")
        c2 = nueva_cuota(db, deporte, "1.50")
        boleto = _apostar(db, ana, "10.00", c1, c2)
        anulada = next(s for s in boleto.selecciones if s.evento_id == c2.evento_id)
        anulada.estado = EstadoSeleccion.ANULADA
        db.commit()

        resumen = _finalizar(db, c1.evento, TipoSeleccion.LOCAL)

        assert resumen["boletos_ganados"] == 1
        assert boleto.estado == EstadoBoleto.GANADO


class TestIdempotencia:
    def test_ejecutar_dos_veces_no_paga_dos_veces(self, db, ana, deporte):
        cuota = nueva_cuota(db, deporte, "2.00")
        boleto = _apostar(db, ana, "10.00", cuota)
        _finalizar(db, cuota.evento, TipoSeleccion.LOCAL)
        liquidado_en = boleto.liquidado_en

        repetido = liquidar_evento(db, cuota.evento_id)
        db.commit()

        assert repetido == {
            "selecciones_acertadas": 0,
            "selecciones_fallidas": 0,
            "boletos_ganados": 0,
            "boletos_perdidos": 0,
            "boletos_pendientes": 0,
            "premios_acreditados": Decimal("0.00"),
        }
        assert len(_premios(db, ana)) == 1
        assert boleto.liquidado_en == liquidado_en
        db.refresh(ana)
        assert ana.saldo == Decimal("110.00")

    def test_evento_sin_apuestas_devuelve_resumen_en_cero(self, db, deporte):
        cuota = nueva_cuota(db, deporte)
        resumen = _finalizar(db, cuota.evento, TipoSeleccion.LOCAL)
        assert resumen["boletos_ganados"] == resumen["selecciones_acertadas"] == 0


class TestContrato:
    def test_no_hace_commit(self, db, ana, deporte):
        """Si catálogo hace rollback, no debe quedar nada de la liquidación."""
        cuota = nueva_cuota(db, deporte, "2.00")
        boleto = _apostar(db, ana, "10.00", cuota)
        cuota.evento.resultado = TipoSeleccion.LOCAL
        db.flush()

        liquidar_evento(db, cuota.evento_id)
        db.rollback()

        db.refresh(boleto)
        db.refresh(ana)
        assert boleto.estado == EstadoBoleto.PENDIENTE
        assert boleto.liquidado_en is None
        assert ana.saldo == Decimal("90.00")
        assert _premios(db, ana) == []

    def test_evento_sin_resultado_da_400(self, db, deporte):
        cuota = nueva_cuota(db, deporte)
        with pytest.raises(HTTPException) as error:
            liquidar_evento(db, cuota.evento_id)
        assert (error.value.status_code, error.value.detail) == (400, "El evento no tiene resultado")

    def test_evento_inexistente_da_404(self, db):
        with pytest.raises(HTTPException) as error:
            liquidar_evento(db, uuid4())
        assert error.value.status_code == 404


class TestLibroMayor:
    def test_la_suma_de_transacciones_es_igual_al_saldo(self, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "2.00")
        c2 = nueva_cuota(db, deporte, "1.75")
        c3 = nueva_cuota(db, deporte, "3.10")
        _apostar(db, ana, "10.00", c1)  # gana 20.00
        _apostar(db, ana, "15.50", c2)  # pierde
        _apostar(db, ana, "7.25", c1, c3)  # cuota 6.20 -> gana 44.95

        _finalizar(db, c1.evento, TipoSeleccion.LOCAL)
        _finalizar(db, c2.evento, TipoSeleccion.EMPATE)
        _finalizar(db, c3.evento, TipoSeleccion.LOCAL)
        _finalizar(db, c1.evento, TipoSeleccion.LOCAL)  # repetido: no debe alterar nada

        db.refresh(ana)
        # 100 - 10 - 15.50 - 7.25 + 20 + 44.95 = 132.20
        assert ana.saldo == Decimal("132.20")
        assert _suma_libro_mayor(db, ana) == ana.saldo
