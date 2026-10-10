import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import EstadoEvento, TipoSeleccion
from app.db.types import Dinero


class Deporte(Base):
    __tablename__ = "deportes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(50), unique=True)
    activo: Mapped[bool] = mapped_column(default=True, server_default=true())


class Evento(Base):
    __tablename__ = "eventos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    deporte_id: Mapped[int] = mapped_column(ForeignKey("deportes.id"))
    equipo_local: Mapped[str] = mapped_column(String(100))
    equipo_visitante: Mapped[str] = mapped_column(String(100))
    inicia_en: Mapped[datetime] = mapped_column(DateTime, index=True)
    estado: Mapped[EstadoEvento] = mapped_column(
        Enum(EstadoEvento, native_enum=False, create_constraint=True, name="estado_evento"),
        default=EstadoEvento.PROGRAMADO,
        server_default=EstadoEvento.PROGRAMADO.value,
        index=True,
    )
    resultado: Mapped[TipoSeleccion | None] = mapped_column(
        Enum(TipoSeleccion, native_enum=False, create_constraint=True, name="resultado_evento"),
        nullable=True,
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    deporte: Mapped[Deporte] = relationship()
    cuotas: Mapped[list["Cuota"]] = relationship(back_populates="evento")


class Cuota(Base):
    __tablename__ = "cuotas"
    __table_args__ = (
        UniqueConstraint("evento_id", "seleccion", name="uq_cuotas_evento_seleccion"),
        # Dinero guarda centavos: 100 equivale a 1.00 (ver app/db/types.py)
        CheckConstraint("valor > 100", name="ck_cuotas_valor_mayor_a_uno"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    evento_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eventos.id"), index=True)
    seleccion: Mapped[TipoSeleccion] = mapped_column(
        Enum(TipoSeleccion, native_enum=False, create_constraint=True, name="tipo_seleccion")
    )
    valor: Mapped[Decimal] = mapped_column(Dinero)
    activa: Mapped[bool] = mapped_column(default=True, server_default=true())

    evento: Mapped[Evento] = relationship(back_populates="cuotas")
