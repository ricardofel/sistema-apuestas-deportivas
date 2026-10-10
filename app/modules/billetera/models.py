import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import TipoTransaccion
from app.db.types import Dinero


def _ahora() -> datetime:
    return datetime.now(UTC)


class Transaccion(Base):
    """Libro mayor inmutable: solo se insertan filas, nunca se actualizan ni se borran."""

    __tablename__ = "transacciones"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), index=True)
<<<<<<< HEAD
    boleto_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("boletos.id"), nullable=True)
=======
    boleto_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
>>>>>>> origin/RicardoE
    tipo: Mapped[TipoTransaccion] = mapped_column(
        Enum(TipoTransaccion, native_enum=False, create_constraint=True, name="tipo_transaccion")
    )
    monto: Mapped[Decimal] = mapped_column(Dinero)
    saldo_posterior: Mapped[Decimal] = mapped_column(Dinero)
    descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora, index=True)
