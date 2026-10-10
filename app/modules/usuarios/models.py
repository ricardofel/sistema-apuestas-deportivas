import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, String, Uuid, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import RolUsuario
from app.db.types import Dinero


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (CheckConstraint("saldo >= 0", name="ck_usuarios_saldo_no_negativo"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    nombre_usuario: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    rol: Mapped[RolUsuario] = mapped_column(
        Enum(RolUsuario, native_enum=False, create_constraint=True, name="rol_usuario"),
        default=RolUsuario.USUARIO,
        server_default=RolUsuario.USUARIO.value,
    )
    saldo: Mapped[Decimal] = mapped_column(Dinero, default=Decimal("0.00"), server_default="0")
    activo: Mapped[bool] = mapped_column(default=True, server_default=true())
    creado_en: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
