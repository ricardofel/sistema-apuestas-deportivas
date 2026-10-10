from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.db.enums import EstadoBoleto, EstadoEvento, EstadoSeleccion, TipoSeleccion, TipoTransaccion
from app.modules.apuestas.models import Boleto, Seleccion
from app.modules.billetera.models import Transaccion
from app.modules.catalogo.models import Cuota, Deporte
from app.modules.usuarios import service as usuarios_service
from tests.factories import crear_boleto, crear_cuota, crear_deporte, crear_evento


@pytest.fixture()
def ana(db):
    return usuarios_service.crear_usuario(db, "ana@correo.com", "ana", "secreta123")


class TestCatalogo:
    def test_valores_por_defecto(self, db):
        evento = crear_evento(db)
        cuota = crear_cuota(db, evento)
        db.refresh(evento)
        assert evento.estado == EstadoEvento.PROGRAMADO
        assert evento.resultado is None
        assert evento.creado_en is not None
        assert cuota.activa is True
        assert evento.deporte.activo is True

    def test_nombre_de_deporte_unico(self, db):
        crear_deporte(db, "Tenis")
        db.add(Deporte(nombre="Tenis"))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_evento_requiere_un_deporte_existente(self, db):
        with pytest.raises(IntegrityError):
            crear_evento(db, deporte=type("Falso", (), {"id": 999})())

    def test_un_evento_no_repite_cuota_para_el_mismo_resultado(self, db):
        evento = crear_evento(db)
        crear_cuota(db, evento, TipoSeleccion.LOCAL)
        db.add(Cuota(evento_id=evento.id, seleccion=TipoSeleccion.LOCAL, valor=Decimal("3.00")))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_cuota_debe_ser_mayor_a_uno(self, db):
        evento = crear_evento(db)
        db.add(Cuota(evento_id=evento.id, seleccion=TipoSeleccion.LOCAL, valor=Decimal("1.00")))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(Cuota(evento_id=evento.id, seleccion=TipoSeleccion.LOCAL, valor=Decimal("1.01")))
        db.commit()

    def test_el_evento_expone_sus_cuotas(self, db):
        evento = crear_evento(db)
        crear_cuota(db, evento, TipoSeleccion.LOCAL)
        crear_cuota(db, evento, TipoSeleccion.EMPATE, Decimal("3.10"))
        db.refresh(evento)
        assert {c.seleccion for c in evento.cuotas} == {TipoSeleccion.LOCAL, TipoSeleccion.EMPATE}


class TestApuestas:
    def test_valores_por_defecto_del_boleto(self, db, ana):
        boleto = crear_boleto(db, ana)
        db.refresh(boleto)
        assert boleto.estado == EstadoBoleto.PENDIENTE
        assert boleto.liquidado_en is None
        assert boleto.creado_en is not None
        assert boleto.ganancia_potencial == Decimal("20.00")

    def test_monto_del_boleto_debe_ser_positivo(self, db, ana):
        db.add(
            Boleto(usuario_id=ana.id, monto=Decimal("0"), cuota_total=Decimal("2"), ganancia_potencial=Decimal("0"))
        )
        with pytest.raises(IntegrityError):
            db.commit()

    def test_el_boleto_requiere_un_usuario_existente(self, db):
        db.add(
            Boleto(usuario_id=uuid4(), monto=Decimal("1"), cuota_total=Decimal("2"), ganancia_potencial=Decimal("2"))
        )
        with pytest.raises(IntegrityError):
            db.commit()

    def test_seleccion_guarda_la_cuota_congelada(self, db, ana):
        boleto = crear_boleto(db, ana)
        cuota = crear_cuota(db)
        seleccion = Seleccion(
            boleto_id=boleto.id, cuota_id=cuota.id, evento_id=cuota.evento_id, cuota_congelada=cuota.valor
        )
        db.add(seleccion)
        db.commit()
        cuota.valor = Decimal("5.00")
        db.commit()
        db.refresh(seleccion)
        assert seleccion.cuota_congelada == Decimal("2.00")
        assert seleccion.estado == EstadoSeleccion.PENDIENTE

    def test_no_permite_dos_selecciones_del_mismo_evento_en_un_boleto(self, db, ana):
        boleto = crear_boleto(db, ana)
        evento = crear_evento(db)
        local = crear_cuota(db, evento, TipoSeleccion.LOCAL)
        empate = crear_cuota(db, evento, TipoSeleccion.EMPATE, Decimal("3.00"))
        for cuota in (local, empate):
            db.add(
                Seleccion(
                    boleto_id=boleto.id, cuota_id=cuota.id, evento_id=evento.id, cuota_congelada=cuota.valor
                )
            )
        with pytest.raises(IntegrityError):
            db.commit()

    def test_borrar_un_boleto_borra_sus_selecciones(self, db, ana):
        boleto = crear_boleto(db, ana)
        cuota = crear_cuota(db)
        db.add(
            Seleccion(boleto_id=boleto.id, cuota_id=cuota.id, evento_id=cuota.evento_id, cuota_congelada=cuota.valor)
        )
        db.commit()
        db.execute(delete(Boleto).where(Boleto.id == boleto.id))
        db.commit()
        assert db.scalar(select(func.count()).select_from(Seleccion)) == 0

    def test_la_transaccion_apunta_a_un_boleto_existente(self, db, ana):
        db.add(
            Transaccion(
                usuario_id=ana.id,
                boleto_id=uuid4(),
                tipo=TipoTransaccion.APUESTA,
                monto=Decimal("-1.00"),
                saldo_posterior=Decimal("0.00"),
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
