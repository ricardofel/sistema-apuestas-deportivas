"""Fixtures y fábricas compartidas por los tests de apuestas (Integrante C).

Uso en un archivo de tests:
    from tests.apuestas_utils import ana, beto, admin, catalogo_simulado, deporte  # noqa: F401
"""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.core.security import crear_token_acceso
from app.db.enums import EstadoEvento, RolUsuario, TipoSeleccion
from app.modules.apuestas.schemas import BoletoIn, SeleccionIn
from app.modules.billetera import service as billetera_service
from app.modules.catalogo import service as catalogo_service
from app.modules.catalogo.models import Cuota, Evento
from app.modules.usuarios import service as usuarios_service
from tests.factories import crear_cuota, crear_deporte, crear_evento

# --- Contrato de catálogo simulado --------------------------------------------------------
# Mientras las funciones de Erick no lleguen a main, se reemplazan por estas, que siguen
# el contrato del brief (mismos mensajes y códigos). raising=False permite parchear
# funciones que todavía no existen en catalogo/service.py.


def _obtener_evento(db, evento_id):
    evento = db.get(Evento, evento_id)
    if evento is None:
        raise HTTPException(404, "Evento no encontrado")
    return evento


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
    monkeypatch.setattr(catalogo_service, "obtener_evento", _obtener_evento, raising=False)
    monkeypatch.setattr(catalogo_service, "obtener_cuota", _obtener_cuota, raising=False)
    monkeypatch.setattr(catalogo_service, "obtener_cuotas", _obtener_cuotas, raising=False)
    monkeypatch.setattr(
        catalogo_service, "obtener_cuota_para_apuesta", _obtener_cuota_para_apuesta, raising=False
    )


# --- Fixtures de datos ----------------------------------------------------------------------


@pytest.fixture()
def deporte(db):
    return crear_deporte(db)


def _usuario_con_saldo(db, nombre):
    usuario = usuarios_service.crear_usuario(db, f"{nombre}@correo.com", nombre, "secreta123")
    billetera_service.recargar_saldo(db, usuario.id, Decimal("100.00"))
    return usuario


@pytest.fixture()
def ana(db):
    return _usuario_con_saldo(db, "ana")


@pytest.fixture()
def beto(db):
    return _usuario_con_saldo(db, "beto")


@pytest.fixture()
def admin(db):
    return usuarios_service.crear_usuario(db, "admin@correo.com", "admin", "secreta123", RolUsuario.ADMIN)


# --- Fábricas y ayudas ----------------------------------------------------------------------


def nueva_cuota(db, deporte, valor="2.00", seleccion=TipoSeleccion.LOCAL, **campos_evento):
    """Crea un evento nuevo con una cuota y devuelve la cuota."""
    evento = crear_evento(db, deporte=deporte, **campos_evento)
    return crear_cuota(db, evento=evento, seleccion=seleccion, valor=Decimal(valor))


def datos_boleto(monto, *cuotas) -> BoletoIn:
    return BoletoIn(monto=Decimal(monto), selecciones=[SeleccionIn(cuota_id=c.id) for c in cuotas])


def json_boleto(monto, *cuotas) -> dict:
    return {"monto": monto, "selecciones": [{"cuota_id": str(c.id)} for c in cuotas]}


def headers(usuario) -> dict:
    return {"Authorization": f"Bearer {crear_token_acceso(usuario.id)}"}


def contar(db, modelo) -> int:
    return db.scalar(select(func.count()).select_from(modelo))
