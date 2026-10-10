import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.db.enums import RolUsuario


class RegistroIn(BaseModel):
    email: EmailStr
    nombre_usuario: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=50)]
    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def password_cabe_en_bcrypt(cls, valor: str) -> str:
        if len(valor.encode()) > 72:
            raise ValueError("La contraseña no puede superar 72 bytes")
        return valor


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    nombre_usuario: str
    rol: RolUsuario
    saldo: Decimal
    activo: bool
    creado_en: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
