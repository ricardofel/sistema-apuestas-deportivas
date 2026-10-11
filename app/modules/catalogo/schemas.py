import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.db.enums import EstadoEvento, TipoSeleccion

T = TypeVar("T")

NombreDeporte = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
NombreEquipo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ValorCuota = Annotated[Decimal, Field(gt=1, max_digits=6, decimal_places=2)]


def _a_utc_sin_zona(valor: datetime) -> datetime:
    """Sin zona se asume UTC; con zona se convierte a UTC (así se guardan las fechas)."""
    if valor.tzinfo is None:
        return valor
    return valor.astimezone(UTC).replace(tzinfo=None)


class Pagina(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limite: int
    desplazamiento: int


class DeporteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    activo: bool


class DeporteIn(BaseModel):
    nombre: NombreDeporte


class CuotaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seleccion: TipoSeleccion
    valor: Decimal
    activa: bool


class CuotaIn(BaseModel):
    seleccion: TipoSeleccion
    valor: ValorCuota


class CuotasIn(BaseModel):
    cuotas: list[CuotaIn] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def validar_selecciones(self):
        selecciones = [cuota.seleccion for cuota in self.cuotas]
        if len(set(selecciones)) != len(selecciones):
            raise ValueError("No puede haber selecciones repetidas")
        if TipoSeleccion.LOCAL not in selecciones or TipoSeleccion.VISITANTE not in selecciones:
            raise ValueError("Las cuotas de LOCAL y VISITANTE son obligatorias")
        return self


class CuotaEditarIn(BaseModel):
    valor: ValorCuota | None = None
    activa: bool | None = None

    @model_validator(mode="after")
    def validar_al_menos_un_campo(self):
        if self.valor is None and self.activa is None:
            raise ValueError("Indica al menos un campo para editar")
        return self


class EventoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    deporte: DeporteOut
    equipo_local: str
    equipo_visitante: str
    inicia_en: datetime
    estado: EstadoEvento
    resultado: TipoSeleccion | None
    creado_en: datetime
    cuotas: list[CuotaOut]


class EventoIn(BaseModel):
    deporte_id: int
    equipo_local: NombreEquipo
    equipo_visitante: NombreEquipo
    inicia_en: datetime

    @field_validator("inicia_en")
    @classmethod
    def normalizar_fecha(cls, valor: datetime) -> datetime:
        return _a_utc_sin_zona(valor)

    @model_validator(mode="after")
    def validar_equipos_distintos(self):
        if self.equipo_local.casefold() == self.equipo_visitante.casefold():
            raise ValueError("Los equipos deben ser distintos")
        return self


class EventoEditarIn(BaseModel):
    deporte_id: int | None = None
    equipo_local: NombreEquipo | None = None
    equipo_visitante: NombreEquipo | None = None
    inicia_en: datetime | None = None

    @field_validator("inicia_en")
    @classmethod
    def normalizar_fecha(cls, valor: datetime | None) -> datetime | None:
        return None if valor is None else _a_utc_sin_zona(valor)

    @model_validator(mode="after")
    def validar_campos(self):
        if all(valor is None for valor in self.model_dump().values()):
            raise ValueError("Indica al menos un campo para editar")
        local, visitante = self.equipo_local, self.equipo_visitante
        if local and visitante and local.casefold() == visitante.casefold():
            raise ValueError("Los equipos deben ser distintos")
        return self


class ResultadoIn(BaseModel):
    resultado: TipoSeleccion


class LiquidacionOut(BaseModel):
    selecciones_acertadas: int
    selecciones_fallidas: int
    boletos_ganados: int
    boletos_perdidos: int
    boletos_pendientes: int
    premios_acreditados: Decimal


class ReembolsoOut(BaseModel):
    selecciones_anuladas: int
    boletos_recalculados: int
    boletos_reembolsados: int
    monto_reembolsado: Decimal


class ResultadoEventoOut(BaseModel):
    evento: EventoOut
    liquidacion: LiquidacionOut


class CancelacionEventoOut(BaseModel):
    evento: EventoOut
    reembolsos: ReembolsoOut
