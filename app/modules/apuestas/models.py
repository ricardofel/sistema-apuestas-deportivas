import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import EstadoBoleto, EstadoSeleccion
from app.db.types import Dinero


def _ahora() -> datetime:
    return datetime.now(UTC)


class Boleto(Base):
    __tablename__ = "boletos"
    # Dinero guarda centavos: monto > 0 se escribe igual (ver app/db/types.py)
    __table_args__ = (CheckConstraint("monto > 0", name="ck_boletos_monto_positivo"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("usuarios.id"), index=True)
    monto: Mapped[Decimal] = mapped_column(Dinero)
    cuota_total: Mapped[Decimal] = mapped_column(Dinero)
    ganancia_potencial: Mapped[Decimal] = mapped_column(Dinero)
    estado: Mapped[EstadoBoleto] = mapped_column(
        Enum(EstadoBoleto, native_enum=False, create_constraint=True, name="estado_boleto"),
        default=EstadoBoleto.PENDIENTE,
        server_default=EstadoBoleto.PENDIENTE.value,
        index=True,
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_ahora)
    liquidado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    selecciones: Mapped[list["Seleccion"]] = relationship(
        back_populates="boleto", cascade="all, delete-orphan", passive_deletes=True
    )


class Seleccion(Base):
    __tablename__ = "selecciones"
    __table_args__ = (UniqueConstraint("boleto_id", "evento_id", name="uq_selecciones_boleto_evento"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    boleto_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("boletos.id", ondelete="CASCADE"), index=True)
    cuota_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cuotas.id"))
    evento_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eventos.id"), index=True)
    cuota_congelada: Mapped[Decimal] = mapped_column(Dinero)
    estado: Mapped[EstadoSeleccion] = mapped_column(
        Enum(EstadoSeleccion, native_enum=False, create_constraint=True, name="estado_seleccion"),
        default=EstadoSeleccion.PENDIENTE,
        server_default=EstadoSeleccion.PENDIENTE.value,
    )

    boleto: Mapped[Boleto] = relationship(back_populates="selecciones")
