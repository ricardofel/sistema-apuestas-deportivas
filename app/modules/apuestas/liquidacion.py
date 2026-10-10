from uuid import UUID

from sqlalchemy.orm import Session


# Contrato: lo implementa el Integrante C, lo consume el Integrante B.
def liquidar_evento(db: Session, evento_id: UUID) -> dict:
    raise NotImplementedError("Pendiente: Integrante C")
