from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager, selectinload

from app.db.enums import EstadoEvento
from app.modules.catalogo.models import Cuota, Deporte, Evento


# Contrato: lo implementa el Integrante B, lo consume el Integrante C.
def obtener_cuota_para_apuesta(db: Session, cuota_id: UUID) -> Cuota:
    raise NotImplementedError("Pendiente: Integrante B")


def listar_deportes(db: Session) -> list[Deporte]:
    return list(db.scalars(select(Deporte).where(Deporte.activo.is_(True)).order_by(Deporte.nombre)))


def listar_eventos(db: Session, deporte_id: int | None = None) -> list[Evento]:
    """Eventos que todavía aceptan apuestas (PROGRAMADO y sin iniciar), los más próximos primero."""
    ahora = datetime.now(UTC).replace(tzinfo=None)
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
