"""Tests de creación y consulta de boletos (Integrante C)."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.core.security import crear_token_acceso
from app.db.enums import (
    EstadoBoleto,
    EstadoEvento,
    EstadoSeleccion,
    RolUsuario,
    TipoSeleccion,
    TipoTransaccion,
)
from app.modules.apuestas import service
from app.modules.apuestas.models import Boleto, Seleccion
from app.modules.apuestas.schemas import BoletoIn, SeleccionIn
from app.modules.billetera import service as billetera_service
from app.modules.billetera.models import Transaccion
from app.modules.catalogo import service as catalogo_service
from app.modules.catalogo.models import Cuota
from app.modules.usuarios import service as usuarios_service
from tests.factories import crear_cuota, crear_deporte, crear_evento


# --- Contrato de catálogo simulado --------------------------------------------------------
# Mientras las funciones de Erick no lleguen a main, se reemplazan por estas, que siguen
# el contrato del brief (mismos mensajes y códigos). raising=False permite parchear
# funciones que todavía no existen en catalogo/service.py.


def _obtener_cuota(db, cuota_id):
    cuota = db.scalar(select(Cuota).where(Cuota.id == cuota_id).options(joinedload(Cuota.evento)))
    if cuota is None:
        raise HTTPException(404, "Cuota no encontrada")
    return cuota


def _obtener_cuotas(db, cuota_ids):
    ids = list(cuota_ids)
    if not ids:
        return {}
    consulta = select(Cuota).where(Cuota.id.in_(ids)).options(joinedload(Cuota.evento))
    return {c.id: c for c in db.scalars(consulta)}


def _obtener_cuota_para_apuesta(db, cuota_id):
    cuota = _obtener_cuota(db, cuota_id)
    if not cuota.activa:
        raise HTTPException(400, "La cuota no está activa")
    if cuota.evento.estado != EstadoEvento.PROGRAMADO:
        raise HTTPException(400, "El evento no acepta apuestas")
    if cuota.evento.inicia_en <= datetime.now(UTC).replace(tzinfo=None):
        raise HTTPException(400, "El evento ya inició")
    return cuota


@pytest.fixture(autouse=True)
def catalogo_simulado(monkeypatch):
    monkeypatch.setattr(catalogo_service, "obtener_cuota", _obtener_cuota, raising=False)
    monkeypatch.setattr(catalogo_service, "obtener_cuotas", _obtener_cuotas, raising=False)
    monkeypatch.setattr(
        catalogo_service, "obtener_cuota_para_apuesta", _obtener_cuota_para_apuesta, raising=False
    )


# --- Fábricas y fixtures propias ------------------------------------------------------------


@pytest.fixture()
def deporte(db):
    return crear_deporte(db)


@pytest.fixture()
def ana(db):
    usuario = usuarios_service.crear_usuario(db, "ana@correo.com", "ana", "secreta123")
    billetera_service.recargar_saldo(db, usuario.id, Decimal("100.00"))
    return usuario


@pytest.fixture()
def beto(db):
    usuario = usuarios_service.crear_usuario(db, "beto@correo.com", "beto", "secreta123")
    billetera_service.recargar_saldo(db, usuario.id, Decimal("100.00"))
    return usuario


@pytest.fixture()
def admin(db):
    return usuarios_service.crear_usuario(db, "admin@correo.com", "admin", "secreta123", RolUsuario.ADMIN)


def _cuota(db, deporte, valor="2.00", seleccion=TipoSeleccion.LOCAL, **campos_evento):
    """Crea un evento nuevo con una cuota y devuelve la cuota."""
    evento = crear_evento(db, deporte=deporte, **campos_evento)
    return crear_cuota(db, evento=evento, seleccion=seleccion, valor=Decimal(valor))


def _datos(monto, *cuotas) -> BoletoIn:
    return BoletoIn(monto=Decimal(monto), selecciones=[SeleccionIn(cuota_id=c.id) for c in cuotas])


def _json(monto, *cuotas) -> dict:
    return {"monto": monto, "selecciones": [{"cuota_id": str(c.id)} for c in cuotas]}


def _headers(usuario) -> dict:
    return {"Authorization": f"Bearer {crear_token_acceso(usuario.id)}"}


def _contar(db, modelo) -> int:
    return db.scalar(select(func.count()).select_from(modelo))


# --- Servicio: crear boleto -----------------------------------------------------------------


class TestCrearBoleto:
    def test_simple_calcula_cuota_y_ganancia(self, db, ana, deporte):
        cuota = _cuota(db, deporte, "2.00")
        boleto, saldo = service.crear_boleto(db, ana, _datos("10.00", cuota))

        assert boleto.cuota_total == Decimal("2.00")
        assert boleto.ganancia_potencial == Decimal("20.00")
        assert boleto.estado == EstadoBoleto.PENDIENTE
        assert boleto.liquidado_en is None
        assert saldo == Decimal("90.00")
        assert ana.saldo == Decimal("90.00")

        [seleccion] = boleto.selecciones
        assert seleccion.cuota_id == cuota.id
        assert seleccion.evento_id == cuota.evento_id
        assert seleccion.cuota_congelada == Decimal("2.00")
        assert seleccion.estado == EstadoSeleccion.PENDIENTE

    def test_combinada_multiplica_y_redondea_half_up(self, db, ana, deporte):
        # 1.85 x 2.10 = 3.885 -> 3.89 ; 7.33 x 3.89 = 28.5137 -> 28.51
        c1 = _cuota(db, deporte, "1.85")
        c2 = _cuota(db, deporte, "2.10")
        boleto, _ = service.crear_boleto(db, ana, _datos("7.33", c1, c2))

        assert boleto.cuota_total == Decimal("3.89")
        assert boleto.ganancia_potencial == Decimal("28.51")
        assert len(boleto.selecciones) == 2

    def test_registra_transaccion_apuesta_con_boleto_id(self, db, ana, deporte):
        boleto, _ = service.crear_boleto(db, ana, _datos("10.00", _cuota(db, deporte)))

        transaccion = db.scalar(select(Transaccion).where(Transaccion.tipo == TipoTransaccion.APUESTA))
        assert transaccion.boleto_id == boleto.id
        assert transaccion.monto == Decimal("-10.00")
        assert transaccion.saldo_posterior == Decimal("90.00")

    def test_cuota_congelada_no_cambia_si_se_edita_la_cuota(self, db, ana, deporte):
        cuota = _cuota(db, deporte, "2.00")
        boleto, _ = service.crear_boleto(db, ana, _datos("10.00", cuota))

        cuota.valor = Decimal("5.00")
        db.commit()
        db.refresh(boleto)

        assert boleto.selecciones[0].cuota_congelada == Decimal("2.00")
        assert boleto.cuota_total == Decimal("2.00")
        assert boleto.ganancia_potencial == Decimal("20.00")

    def test_mismo_evento_dos_veces_da_400(self, db, ana, deporte):
        local = _cuota(db, deporte, "2.00")
        visitante = crear_cuota(db, evento=local.evento, seleccion=TipoSeleccion.VISITANTE, valor=Decimal("3.00"))

        with pytest.raises(HTTPException) as error:
            service.crear_boleto(db, ana, _datos("10.00", local, visitante))
        assert error.value.status_code == 400
        assert error.value.detail == "No puedes apostar dos veces al mismo evento"

    def test_cuota_inactiva_da_400(self, db, ana, deporte):
        cuota = _cuota(db, deporte)
        cuota.activa = False
        db.commit()

        with pytest.raises(HTTPException) as error:
            service.crear_boleto(db, ana, _datos("10.00", cuota))
        assert (error.value.status_code, error.value.detail) == (400, "La cuota no está activa")

    def test_evento_iniciado_da_400(self, db, ana, deporte):
        ayer = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        cuota = _cuota(db, deporte, inicia_en=ayer)

        with pytest.raises(HTTPException) as error:
            service.crear_boleto(db, ana, _datos("10.00", cuota))
        assert (error.value.status_code, error.value.detail) == (400, "El evento ya inició")

    def test_evento_cancelado_da_400(self, db, ana, deporte):
        cuota = _cuota(db, deporte, estado=EstadoEvento.CANCELADO)

        with pytest.raises(HTTPException) as error:
            service.crear_boleto(db, ana, _datos("10.00", cuota))
        assert (error.value.status_code, error.value.detail) == (400, "El evento no acepta apuestas")

    def test_cuota_inexistente_da_404(self, db, ana):
        datos = BoletoIn(monto=Decimal("10.00"), selecciones=[SeleccionIn(cuota_id=uuid4())])
        with pytest.raises(HTTPException) as error:
            service.crear_boleto(db, ana, datos)
        assert error.value.status_code == 404

    def test_saldo_insuficiente_hace_rollback_total(self, db, ana, deporte):
        cuotas = [_cuota(db, deporte, "1.50"), _cuota(db, deporte, "2.00")]
        antes = (_contar(db, Boleto), _contar(db, Seleccion), _contar(db, Transaccion))

        with pytest.raises(HTTPException) as error:
            service.crear_boleto(db, ana, _datos("100.01", *cuotas))

        assert (error.value.status_code, error.value.detail) == (400, "Saldo insuficiente")
        assert (_contar(db, Boleto), _contar(db, Seleccion), _contar(db, Transaccion)) == antes
        db.refresh(ana)
        assert ana.saldo == Decimal("100.00")

    def test_dos_boletos_que_juntos_superan_el_saldo(self, db, ana, deporte):
        service.crear_boleto(db, ana, _datos("60.00", _cuota(db, deporte)))

        with pytest.raises(HTTPException) as error:
            service.crear_boleto(db, ana, _datos("60.00", _cuota(db, deporte)))

        assert error.value.status_code == 400
        db.refresh(ana)
        assert ana.saldo == Decimal("40.00")
        assert _contar(db, Boleto) == 1

    def test_apostar_todo_el_saldo_es_valido(self, db, ana, deporte):
        _, saldo = service.crear_boleto(db, ana, _datos("100.00", _cuota(db, deporte)))
        assert saldo == Decimal("0.00")

    def test_libro_mayor_cuadra_con_el_saldo(self, db, ana, deporte):
        service.crear_boleto(db, ana, _datos("10.00", _cuota(db, deporte)))
        service.crear_boleto(db, ana, _datos("25.50", _cuota(db, deporte), _cuota(db, deporte)))

        suma = db.scalar(select(func.sum(Transaccion.monto)).where(Transaccion.usuario_id == ana.id))
        db.refresh(ana)
        # SUM hereda el tipo Dinero de la columna: SQLAlchemy ya lo devuelve como Decimal.
        assert suma == ana.saldo == Decimal("64.50")


# --- API ------------------------------------------------------------------------------------


class TestApiCrear:
    def test_crea_y_devuelve_201_con_dinero_como_texto(self, client, db, ana, deporte):
        cuota = _cuota(db, deporte, "2.00", equipo_local="Barcelona SC", equipo_visitante="Emelec")

        respuesta = client.post("/api/boletos", json=_json("10.00", cuota), headers=_headers(ana))

        assert respuesta.status_code == 201
        cuerpo = respuesta.json()
        assert cuerpo["monto"] == "10.00"
        assert cuerpo["cuota_total"] == "2.00"
        assert cuerpo["ganancia_potencial"] == "20.00"
        assert cuerpo["saldo_restante"] == "90.00"
        assert cuerpo["estado"] == "PENDIENTE"
        assert cuerpo["liquidado_en"] is None
        assert cuerpo["selecciones"] == [
            {
                "evento_id": str(cuota.evento_id),
                "evento": "Barcelona SC vs Emelec",
                "seleccion": "LOCAL",
                "cuota_congelada": "2.00",
                "estado": "PENDIENTE",
            }
        ]

    def test_sin_sesion_da_401(self, client, db, deporte):
        respuesta = client.post("/api/boletos", json=_json("10.00", _cuota(db, deporte)))
        assert respuesta.status_code == 401

    @pytest.mark.parametrize("monto", ["0.99", "500.01", "0", "-5", "10.001"])
    def test_monto_fuera_de_rango_da_422(self, client, db, ana, deporte, monto):
        respuesta = client.post("/api/boletos", json=_json(monto, _cuota(db, deporte)), headers=_headers(ana))
        assert respuesta.status_code == 422

    @pytest.mark.parametrize("monto", ["1.00", "500.00"])
    def test_monto_en_los_limites_es_valido(self, client, db, ana, deporte, monto):
        billetera_service.recargar_saldo(db, ana.id, Decimal("500.00"))
        respuesta = client.post("/api/boletos", json=_json(monto, _cuota(db, deporte)), headers=_headers(ana))
        assert respuesta.status_code == 201

    @pytest.mark.parametrize("cantidad", [0, 11])
    def test_cantidad_de_selecciones_invalida_da_422(self, client, ana, cantidad):
        cuerpo = {"monto": "10.00", "selecciones": [{"cuota_id": str(uuid4())} for _ in range(cantidad)]}
        respuesta = client.post("/api/boletos", json=cuerpo, headers=_headers(ana))
        assert respuesta.status_code == 422

    def test_diez_selecciones_es_valido(self, client, db, ana, deporte):
        cuotas = [_cuota(db, deporte, "1.10") for _ in range(10)]
        respuesta = client.post("/api/boletos", json=_json("1.00", *cuotas), headers=_headers(ana))
        assert respuesta.status_code == 201
        assert len(respuesta.json()["selecciones"]) == 10

    def test_saldo_insuficiente_da_400(self, client, db, ana, deporte):
        respuesta = client.post("/api/boletos", json=_json("150.00", _cuota(db, deporte)), headers=_headers(ana))
        assert respuesta.status_code == 400
        assert respuesta.json()["detail"] == "Saldo insuficiente"


class TestApiConsultar:
    def test_mios_mas_recientes_primero_y_solo_los_propios(self, client, db, ana, beto, deporte):
        primero, _ = service.crear_boleto(db, ana, _datos("10.00", _cuota(db, deporte)))
        segundo, _ = service.crear_boleto(db, ana, _datos("20.00", _cuota(db, deporte)))
        service.crear_boleto(db, beto, _datos("5.00", _cuota(db, deporte)))

        respuesta = client.get("/api/boletos/mios", headers=_headers(ana))

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["total"] == 2
        assert [b["id"] for b in cuerpo["items"]] == [str(segundo.id), str(primero.id)]

    def test_mios_filtra_por_estado_y_pagina(self, client, db, ana, deporte):
        boletos = [service.crear_boleto(db, ana, _datos("1.00", _cuota(db, deporte)))[0] for _ in range(3)]
        boletos[0].estado = EstadoBoleto.GANADO
        db.commit()

        pendientes = client.get("/api/boletos/mios?estado=PENDIENTE", headers=_headers(ana)).json()
        assert pendientes["total"] == 2

        pagina = client.get("/api/boletos/mios?limite=1&desplazamiento=1", headers=_headers(ana)).json()
        assert (pagina["total"], pagina["limite"], pagina["desplazamiento"]) == (3, 1, 1)
        assert [b["id"] for b in pagina["items"]] == [str(boletos[1].id)]

    def test_mios_sin_sesion_da_401(self, client):
        assert client.get("/api/boletos/mios").status_code == 401

    def test_ver_boleto_propio(self, client, db, ana, deporte):
        boleto, _ = service.crear_boleto(db, ana, _datos("10.00", _cuota(db, deporte)))
        respuesta = client.get(f"/api/boletos/{boleto.id}", headers=_headers(ana))
        assert respuesta.status_code == 200
        assert respuesta.json()["id"] == str(boleto.id)

    def test_boleto_ajeno_da_404(self, client, db, ana, beto, deporte):
        boleto, _ = service.crear_boleto(db, ana, _datos("10.00", _cuota(db, deporte)))
        assert client.get(f"/api/boletos/{boleto.id}", headers=_headers(beto)).status_code == 404

    def test_boleto_inexistente_da_404(self, client, ana):
        assert client.get(f"/api/boletos/{uuid4()}", headers=_headers(ana)).status_code == 404

    def test_admin_puede_ver_cualquier_boleto(self, client, db, ana, admin, deporte):
        boleto, _ = service.crear_boleto(db, ana, _datos("10.00", _cuota(db, deporte)))
        assert client.get(f"/api/boletos/{boleto.id}", headers=_headers(admin)).status_code == 200


class TestApiAdmin:
    def test_usuario_normal_da_403(self, client, ana):
        assert client.get("/api/admin/boletos", headers=_headers(ana)).status_code == 403

    def test_sin_sesion_da_401(self, client):
        assert client.get("/api/admin/boletos").status_code == 401

    def test_lista_todos_y_filtra_por_usuario_y_estado(self, client, db, ana, beto, admin, deporte):
        service.crear_boleto(db, ana, _datos("10.00", _cuota(db, deporte)))
        de_beto, _ = service.crear_boleto(db, beto, _datos("5.00", _cuota(db, deporte)))

        todos = client.get("/api/admin/boletos", headers=_headers(admin)).json()
        assert todos["total"] == 2

        solo_beto = client.get(f"/api/admin/boletos?usuario_id={beto.id}", headers=_headers(admin)).json()
        assert [b["id"] for b in solo_beto["items"]] == [str(de_beto.id)]

        ganados = client.get("/api/admin/boletos?estado=GANADO", headers=_headers(admin)).json()
        assert ganados["total"] == 0
