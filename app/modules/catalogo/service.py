from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager, joinedload, selectinload

from app.db.enums import EstadoEvento
from app.modules.catalogo.models import Cuota, Deporte, Evento


def _ahora_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def obtener_evento(db: Session, evento_id: UUID) -> Evento:
    evento = db.get(Evento, evento_id)
    if evento is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return evento


def obtener_cuota(db: Session, cuota_id: UUID) -> Cuota:
    cuota = db.scalar(select(Cuota).where(Cuota.id == cuota_id).options(joinedload(Cuota.evento)))
    if cuota is None:
        raise HTTPException(status_code=404, detail="Cuota no encontrada")
    return cuota


def obtener_cuotas(db: Session, cuota_ids: Iterable[UUID]) -> dict[UUID, Cuota]:
    """Cuotas por id, con su evento cargado. Los ids que no existen se omiten."""
    ids = list(cuota_ids)
    if not ids:
        return {}
    consulta = select(Cuota).where(Cuota.id.in_(ids)).options(joinedload(Cuota.evento))
    return {cuota.id: cuota for cuota in db.scalars(consulta)}


# Contrato: lo implementa el Integrante B, lo consume el Integrante C.
def obtener_cuota_para_apuesta(db: Session, cuota_id: UUID) -> Cuota:
    """Cuota validada para apostar: activa, en un evento PROGRAMADO que aún no inicia."""
    cuota = obtener_cuota(db, cuota_id)
    if not cuota.activa:
        raise HTTPException(status_code=400, detail="La cuota no está activa")
    if cuota.evento.estado != EstadoEvento.PROGRAMADO:
        raise HTTPException(status_code=400, detail="El evento no acepta apuestas")
    if cuota.evento.inicia_en <= _ahora_utc():
        raise HTTPException(status_code=400, detail="El evento ya inició")
    return cuota


def listar_deportes(db: Session) -> list[Deporte]:
    return list(db.scalars(select(Deporte).where(Deporte.activo.is_(True)).order_by(Deporte.nombre)))


def listar_eventos(db: Session, deporte_id: int | None = None) -> list[Evento]:
    """Eventos que todavía aceptan apuestas (PROGRAMADO y sin iniciar), los más próximos primero."""
    ahora = _ahora_utc()
    consulta = (
        select(Evento)
        .join(Evento.deporte)
        .where(Evento.estado == EstadoEvento.PROGRAMADO, Evento.inicia_en > ahora, Deporte.activo.is_(True))
        .options(contains_eager(Evento.deporte), selectinload(Evento.cuotas))
        .order_by(Evento.inicia_en)
    )
    if deporte_id is not None:
        consulta = consulta.where(Evento.deporte_id == deporte_id)
    return list(db.scalars(consulta))
