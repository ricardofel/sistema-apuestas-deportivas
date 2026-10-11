import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, Field

from app.db.enums import EstadoBoleto, EstadoSeleccion, TipoSeleccion

T = TypeVar("T")

# Regla del monto de una apuesta; la usan BoletoIn y el panel de boleto.
MontoApuesta = Annotated[Decimal, Field(ge=1, le=500, max_digits=12, decimal_places=2)]


class SeleccionIn(BaseModel):
    cuota_id: uuid.UUID


class BoletoIn(BaseModel):
    monto: MontoApuesta
    selecciones: list[SeleccionIn] = Field(min_length=1, max_length=10)


class SeleccionOut(BaseModel):
    evento_id: uuid.UUID
    evento: str  # "Local vs Visitante"
    seleccion: TipoSeleccion
    cuota_congelada: Decimal
    estado: EstadoSeleccion


class BoletoOut(BaseModel):
    id: uuid.UUID
    monto: Decimal
    cuota_total: Decimal
    ganancia_potencial: Decimal
    estado: EstadoBoleto
    creado_en: datetime
    liquidado_en: datetime | None
    selecciones: list[SeleccionOut]


class BoletoCreadoOut(BoletoOut):
    saldo_restante: Decimal


class Pagina(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limite: int
    desplazamiento: int
