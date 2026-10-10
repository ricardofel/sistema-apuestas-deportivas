from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.enums import TipoTransaccion

if TYPE_CHECKING:
    from app.modules.billetera.models import Transaccion


# Contrato: lo implementa el Integrante A, lo consume el Integrante C.
def debitar(
    db: Session, usuario_id: UUID, monto: Decimal, boleto_id: UUID, descripcion: str
) -> Transaccion:
    raise NotImplementedError("Pendiente: Integrante A")


def acreditar(
    db: Session,
    usuario_id: UUID,
    monto: Decimal,
    tipo: TipoTransaccion,
    boleto_id: UUID | None,
    descripcion: str,
) -> Transaccion:
    raise NotImplementedError("Pendiente: Integrante A")
