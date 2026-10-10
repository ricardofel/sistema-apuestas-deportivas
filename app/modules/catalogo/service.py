from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.modules.catalogo.models import Cuota


# Contrato: lo implementa el Integrante B, lo consume el Integrante C.
def obtener_cuota_para_apuesta(db: Session, cuota_id: UUID) -> Cuota:
    raise NotImplementedError("Pendiente: Integrante B")
