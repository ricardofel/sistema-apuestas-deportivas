import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import TipoTransaccion


class TransaccionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    usuario_id: uuid.UUID
    boleto_id: uuid.UUID | None
    tipo: TipoTransaccion
    monto: Decimal
    saldo_posterior: Decimal
    descripcion: str | None
    creado_en: datetime


class PaginaTransacciones(BaseModel):
    items: list[TransaccionOut]
    total: int
    limite: int
    desplazamiento: int


class SaldoOut(BaseModel):
    saldo: Decimal


class RecargaIn(BaseModel):
    usuario_id: uuid.UUID
    monto: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    descripcion: str | None = Field(default=None, max_length=255)
