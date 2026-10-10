from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.security import crear_token_acceso
from app.db.enums import RolUsuario, TipoTransaccion
from app.modules.billetera import service
from app.modules.billetera.models import Transaccion
from app.modules.usuarios import service as usuarios_service
from tests.factories import crear_boleto


@pytest.fixture()
def ana(db):
    return usuarios_service.crear_usuario(db, "ana@correo.com", "ana", "secreta123")


@pytest.fixture()
def admin(db):
    return usuarios_service.crear_usuario(db, "admin@correo.com", "admin", "secreta123", RolUsuario.ADMIN)


@pytest.fixture()
def boleto(db, ana):
    return crear_boleto(db, ana)


def _headers(usuario) -> dict:
    return {"Authorization": f"Bearer {crear_token_acceso(usuario.id)}"}


def _cargar(db, usuario, monto="100.00"):
    return service.recargar_saldo(db, usuario.id, Decimal(monto))


class TestModelo:
    def test_requiere_un_usuario_existente(self, db):
        db.add(
            Transaccion(
                usuario_id=uuid4(),
                tipo=TipoTransaccion.RECARGA,
                monto=Decimal("1.00"),
                saldo_posterior=Decimal("1.00"),
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


class TestServicio:
    def test_acreditar_suma_saldo_y_registra_la_transaccion(self, db, ana, boleto):
        transaccion = service.acreditar(
            db, ana.id, Decimal("50.00"), TipoTransaccion.PREMIO, boleto.id, "Premio"
        )
        assert ana.saldo == Decimal("50.00")
        assert transaccion.monto == Decimal("50.00")
        assert transaccion.saldo_posterior == Decimal("50.00")
        assert transaccion.tipo == TipoTransaccion.PREMIO

    def test_debitar_guarda_el_monto_negativo(self, db, ana, boleto):
        _cargar(db, ana)
        transaccion = service.debitar(db, ana.id, Decimal("10.00"), boleto.id, "Apuesta")
        assert ana.saldo == Decimal("90.00")
        assert transaccion.monto == Decimal("-10.00")
        assert transaccion.saldo_posterior == Decimal("90.00")
        assert transaccion.tipo == TipoTransaccion.APUESTA
        assert transaccion.boleto_id == boleto.id

    def test_debitar_todo_el_saldo_es_valido(self, db, ana, boleto):
        _cargar(db, ana, "10.00")
        service.debitar(db, ana.id, Decimal("10.00"), boleto.id, "Apuesta")
        assert ana.saldo == Decimal("0.00")

    def test_saldo_insuficiente_devuelve_400_y_no_cambia_nada(self, db, ana, boleto):
        _cargar(db, ana, "10.00")
        with pytest.raises(HTTPException) as error:
            service.debitar(db, ana.id, Decimal("10.01"), boleto.id, "Apuesta")
        assert error.value.status_code == 400
        assert ana.saldo == Decimal("10.00")
        assert db.scalar(select(func.count()).select_from(Transaccion)) == 1

    def test_usuario_inexistente_devuelve_404(self, db):
        with pytest.raises(HTTPException) as error:
            service.acreditar(db, uuid4(), Decimal("1.00"), TipoTransaccion.RECARGA, None, "x")
        assert error.value.status_code == 404

    @pytest.mark.parametrize("monto", [Decimal("0"), Decimal("-5.00")])
    def test_monto_no_positivo_es_rechazado(self, db, ana, monto):
        with pytest.raises(ValueError):
            service.debitar(db, ana.id, monto, uuid4(), "x")
        with pytest.raises(ValueError):
            service.acreditar(db, ana.id, monto, TipoTransaccion.RECARGA, None, "x")

    def test_acreditar_no_acepta_tipo_apuesta(self, db, ana):
        with pytest.raises(ValueError):
            service.acreditar(db, ana.id, Decimal("1.00"), TipoTransaccion.APUESTA, None, "x")

    def test_los_decimales_no_pierden_precision(self, db, ana):
        _cargar(db, ana, "0.10")
        _cargar(db, ana, "0.20")
        assert ana.saldo == Decimal("0.30")

    def test_la_suma_de_montos_siempre_iguala_el_saldo(self, db, ana, boleto):
        _cargar(db, ana, "100.00")
        service.debitar(db, ana.id, Decimal("33.33"), boleto.id, "Apuesta")
        service.acreditar(db, ana.id, Decimal("12.50"), TipoTransaccion.PREMIO, None, "Premio")
        service.debitar(db, ana.id, Decimal("0.07"), boleto.id, "Apuesta")
        db.commit()
        suma = sum(t.monto for t in db.scalars(select(Transaccion)))
        assert suma == ana.saldo == Decimal("79.10")

    def test_debitar_y_acreditar_no_hacen_commit(self, db, ana, boleto):
        _cargar(db, ana, "100.00")
        service.debitar(db, ana.id, Decimal("40.00"), boleto.id, "Apuesta")
        db.rollback()
        db.refresh(ana)
        assert ana.saldo == Decimal("100.00")
        assert db.scalar(select(func.count()).select_from(Transaccion)) == 1

    def test_recargar_saldo_si_hace_commit(self, db, ana):
        _cargar(db, ana, "25.00")
        db.rollback()
        db.refresh(ana)
        assert ana.saldo == Decimal("25.00")

    def test_historial_paginado_y_del_propio_usuario(self, db, ana, admin):
        for _ in range(5):
            _cargar(db, ana, "1.00")
        _cargar(db, admin, "9.00")
        items, total = service.listar_transacciones(db, ana.id, limite=2)
        assert total == 5
        assert len(items) == 2
        assert all(t.usuario_id == ana.id for t in items)
        assert items[0].creado_en >= items[1].creado_en
        assert len(service.listar_transacciones(db, ana.id, limite=10, desplazamiento=4)[0]) == 1


class TestApi:
    def test_saldo_requiere_sesion(self, client):
        assert client.get("/api/billetera/saldo").status_code == 401

    def test_consultar_saldo(self, client, db, ana):
        _cargar(db, ana, "15.50")
        respuesta = client.get("/api/billetera/saldo", headers=_headers(ana))
        assert respuesta.json() == {"saldo": "15.50"}

    def test_historial_de_transacciones(self, client, db, ana, boleto):
        _cargar(db, ana, "10.00")
        service.debitar(db, ana.id, Decimal("4.00"), boleto.id, "Apuesta")
        db.commit()
        respuesta = client.get("/api/billetera/transacciones?limite=1", headers=_headers(ana))
        cuerpo = respuesta.json()
        assert cuerpo["total"] == 2
        assert cuerpo["limite"] == 1
        assert cuerpo["items"][0]["tipo"] == "APUESTA"
        assert cuerpo["items"][0]["monto"] == "-4.00"

    def test_admin_recarga_saldo_a_un_usuario(self, client, db, ana, admin):
        respuesta = client.post(
            "/api/admin/billetera/recargar",
            json={"usuario_id": str(ana.id), "monto": "75.25", "descripcion": "Bono"},
            headers=_headers(admin),
        )
        assert respuesta.status_code == 201
        assert respuesta.json()["tipo"] == "RECARGA"
        assert respuesta.json()["saldo_posterior"] == "75.25"
        assert client.get("/api/billetera/saldo", headers=_headers(ana)).json() == {"saldo": "75.25"}

    def test_usuario_comun_no_puede_recargar(self, client, ana):
        respuesta = client.post(
            "/api/admin/billetera/recargar",
            json={"usuario_id": str(ana.id), "monto": "10.00"},
            headers=_headers(ana),
        )
        assert respuesta.status_code == 403

    def test_recargar_usuario_inexistente_devuelve_404(self, client, admin):
        respuesta = client.post(
            "/api/admin/billetera/recargar",
            json={"usuario_id": str(uuid4()), "monto": "10.00"},
            headers=_headers(admin),
        )
        assert respuesta.status_code == 404

    @pytest.mark.parametrize("monto", ["0", "-1.00", "10.123"])
    def test_monto_de_recarga_invalido_devuelve_422(self, client, ana, admin, monto):
        respuesta = client.post(
            "/api/admin/billetera/recargar",
            json={"usuario_id": str(ana.id), "monto": monto},
            headers=_headers(admin),
        )
        assert respuesta.status_code == 422
