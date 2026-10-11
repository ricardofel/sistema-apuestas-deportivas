from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager, joinedload, selectinload

from app.db.enums import EstadoEvento, TipoSeleccion
from app.modules.catalogo.models import Cuota, Deporte, Evento
from app.modules.catalogo.schemas import CuotaEditarIn, CuotasIn, EventoEditarIn, EventoIn


def _ahora_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def obtener_evento(db: Session, evento_id: UUID) -> Evento:
    evento = db.get(Evento, evento_id)
    if evento is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return evento


def obtener_cuota(db: Session, cuota_id: UUID) -> Cuota:
    cuota = db.scalar(select(Cuota).where(Cuota.id == cuota_id).options(joinedload(Cuota.evento)))
    if cuota is None:
        raise HTTPException(status_code=404, detail="Cuota no encontrada")
    return cuota


def obtener_cuotas(db: Session, cuota_ids: Iterable[UUID]) -> dict[UUID, Cuota]:
    """Cuotas por id, con su evento cargado. Los ids que no existen se omiten."""
    ids = list(cuota_ids)
    if not ids:
        return {}
    consulta = select(Cuota).where(Cuota.id.in_(ids)).options(joinedload(Cuota.evento))
    return {cuota.id: cuota for cuota in db.scalars(consulta)}


# Contrato: lo implementa el Integrante B, lo consume el Integrante C.
def obtener_cuota_para_apuesta(db: Session, cuota_id: UUID) -> Cuota:
    """Cuota validada para apostar: activa, en un evento PROGRAMADO que aún no inicia."""
    cuota = obtener_cuota(db, cuota_id)
    if not cuota.activa:
        raise HTTPException(status_code=400, detail="La cuota no está activa")
    if cuota.evento.estado != EstadoEvento.PROGRAMADO:
        raise HTTPException(status_code=400, detail="El evento no acepta apuestas")
    if cuota.evento.inicia_en <= _ahora_utc():
        raise HTTPException(status_code=400, detail="El evento ya inició")
    return cuota


def listar_deportes(db: Session) -> list[Deporte]:
    return list(db.scalars(select(Deporte).where(Deporte.activo.is_(True)).order_by(Deporte.nombre)))


def listar_eventos(db: Session, deporte_id: int | None = None) -> list[Evento]:
    """Eventos que todavía aceptan apuestas (PROGRAMADO y sin iniciar), los más próximos primero."""
    ahora = _ahora_utc()
    consulta = (
        select(Evento)
        .join(Evento.deporte)
        .where(Evento.estado == EstadoEvento.PROGRAMADO, Evento.inicia_en > ahora, Deporte.activo.is_(True))
        .options(contains_eager(Evento.deporte), selectinload(Evento.cuotas))
        .order_by(Evento.inicia_en)
    )
    if deporte_id is not None:
        consulta = consulta.where(Evento.deporte_id == deporte_id)
    return list(db.scalars(consulta))


def crear_deporte(db: Session, nombre: str) -> Deporte:
    existente = db.scalar(select(Deporte.id).where(func.lower(Deporte.nombre) == nombre.lower()))
    if existente is not None:
        raise HTTPException(status_code=409, detail="Ya existe un deporte con ese nombre")
    deporte = Deporte(nombre=nombre)
    db.add(deporte)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un deporte con ese nombre") from None
    return deporte


def _cargar_cuotas(solo_activas: bool):
    """Opción de carga de las cuotas de un evento; el público solo ve las activas."""
    relacion = Evento.cuotas.and_(Cuota.activa.is_(True)) if solo_activas else Evento.cuotas
    return selectinload(relacion)


def listar_eventos_paginado(
    db: Session,
    deporte_id: int | None = None,
    estado: EstadoEvento | None = None,
    limite: int = 20,
    desplazamiento: int = 0,
    solo_cuotas_activas: bool = True,
) -> tuple[list[Evento], int]:
    """Eventos de cualquier estado (filtrables), por fecha de inicio. Excluye deportes inactivos."""
    filtros = [Deporte.activo.is_(True)]
    if deporte_id is not None:
        filtros.append(Evento.deporte_id == deporte_id)
    if estado is not None:
        filtros.append(Evento.estado == estado)

    total = db.scalar(select(func.count()).select_from(Evento).join(Evento.deporte).where(*filtros)) or 0
    consulta = (
        select(Evento)
        .join(Evento.deporte)
        .where(*filtros)
        .options(contains_eager(Evento.deporte), _cargar_cuotas(solo_cuotas_activas))
        .order_by(Evento.inicia_en, Evento.id)
        .limit(limite)
        .offset(desplazamiento)
        .execution_options(populate_existing=True)
    )
    return list(db.scalars(consulta)), total


def obtener_detalle_evento(db: Session, evento_id: UUID, solo_cuotas_activas: bool = True) -> Evento:
    consulta = (
        select(Evento)
        .where(Evento.id == evento_id)
        .options(joinedload(Evento.deporte), _cargar_cuotas(solo_cuotas_activas))
        .execution_options(populate_existing=True)
    )
    evento = db.scalar(consulta)
    if evento is None:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return evento


def _validar_deporte_activo(db: Session, deporte_id: int) -> None:
    deporte = db.get(Deporte, deporte_id)
    if deporte is None:
        raise HTTPException(status_code=404, detail="Deporte no encontrado")
    if not deporte.activo:
        raise HTTPException(status_code=400, detail="El deporte no está activo")


def _validar_fecha_futura(inicia_en: datetime) -> None:
    if inicia_en <= _ahora_utc():
        raise HTTPException(status_code=400, detail="La fecha de inicio debe ser futura")


def crear_evento(db: Session, datos: EventoIn) -> Evento:
    _validar_deporte_activo(db, datos.deporte_id)
    _validar_fecha_futura(datos.inicia_en)
    evento = Evento(
        deporte_id=datos.deporte_id,
        equipo_local=datos.equipo_local,
        equipo_visitante=datos.equipo_visitante,
        inicia_en=datos.inicia_en,
    )
    db.add(evento)
    db.commit()
    return obtener_detalle_evento(db, evento.id, solo_cuotas_activas=False)


def editar_evento(db: Session, evento_id: UUID, datos: EventoEditarIn) -> Evento:
    evento = obtener_evento(db, evento_id)
    if evento.estado != EstadoEvento.PROGRAMADO:
        raise HTTPException(status_code=400, detail="Solo se puede editar un evento programado")

    cambios = datos.model_dump(exclude_none=True)
    if "deporte_id" in cambios and cambios["deporte_id"] != evento.deporte_id:
        _validar_deporte_activo(db, cambios["deporte_id"])
    if "inicia_en" in cambios:
        _validar_fecha_futura(cambios["inicia_en"])
    local = cambios.get("equipo_local", evento.equipo_local)
    visitante = cambios.get("equipo_visitante", evento.equipo_visitante)
    if local.casefold() == visitante.casefold():
        raise HTTPException(status_code=400, detail="Los equipos deben ser distintos")

    for campo, valor in cambios.items():
        setattr(evento, campo, valor)
    db.commit()
    return obtener_detalle_evento(db, evento.id, solo_cuotas_activas=False)


def crear_cuotas(db: Session, evento_id: UUID, datos: CuotasIn) -> list[Cuota]:
    evento = obtener_evento(db, evento_id)
    if evento.estado != EstadoEvento.PROGRAMADO:
        raise HTTPException(status_code=400, detail="Solo se pueden cargar cuotas a un evento programado")

    existentes = set(db.scalars(select(Cuota.seleccion).where(Cuota.evento_id == evento.id)))
    repetidas = [c.seleccion.value for c in datos.cuotas if c.seleccion in existentes]
    if repetidas:
        raise HTTPException(status_code=409, detail=f"El evento ya tiene cuota para: {', '.join(repetidas)}")

    cuotas = [Cuota(evento_id=evento.id, seleccion=c.seleccion, valor=c.valor) for c in datos.cuotas]
    db.add_all(cuotas)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="El evento ya tiene cuota para alguna de las selecciones") from None
    return cuotas


def editar_cuota(db: Session, cuota_id: UUID, datos: CuotaEditarIn) -> Cuota:
    """Edita el valor (solo evento PROGRAMADO) o la activación. Los boletos usan `cuota_congelada`."""
    cuota = obtener_cuota(db, cuota_id)
    if datos.valor is not None and cuota.evento.estado != EstadoEvento.PROGRAMADO:
        raise HTTPException(status_code=400, detail="Solo se puede cambiar el valor de un evento programado")
    if datos.valor is not None:
        cuota.valor = datos.valor
    if datos.activa is not None:
        cuota.activa = datos.activa
    db.commit()
    return cuota


ESTADOS_ABIERTOS = (EstadoEvento.PROGRAMADO, EstadoEvento.EN_VIVO)


def _obtener_evento_abierto(db: Session, evento_id: UUID) -> Evento:
    evento = obtener_evento(db, evento_id)
    if evento.estado not in ESTADOS_ABIERTOS:
        raise HTTPException(status_code=400, detail="El evento ya fue cerrado")
    return evento


def registrar_resultado(db: Session, evento_id: UUID, resultado: TipoSeleccion) -> tuple[Evento, dict]:
    """Finaliza el evento y liquida los boletos en una sola transacción.

    Devuelve el evento y el resumen de la liquidación. Si algo falla, el evento no queda FINALIZADO.
    """
    # Import perezoso: apuestas.liquidacion importa este módulo (evita el import circular).
    from app.modules.apuestas import liquidacion

    evento = _obtener_evento_abierto(db, evento_id)
    selecciones = set(db.scalars(select(Cuota.seleccion).where(Cuota.evento_id == evento.id)))
    if resultado not in selecciones:
        raise HTTPException(status_code=400, detail="El resultado no es válido para este evento")

    try:
        evento.estado = EstadoEvento.FINALIZADO
        evento.resultado = resultado
        db.flush()
        resumen = liquidacion.liquidar_evento(db, evento.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return obtener_detalle_evento(db, evento.id, solo_cuotas_activas=False), resumen


def cancelar_evento(db: Session, evento_id: UUID) -> tuple[Evento, dict]:
    """Cancela el evento y procesa los reembolsos en una sola transacción."""
    from app.modules.apuestas import liquidacion

    evento = _obtener_evento_abierto(db, evento_id)
    try:
        evento.estado = EstadoEvento.CANCELADO
        db.flush()
        resumen = liquidacion.procesar_cancelacion_evento(db, evento.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return obtener_detalle_evento(db, evento.id, solo_cuotas_activas=False), resumen


def contar_eventos_por_estado(db: Session) -> dict[EstadoEvento, int]:
    """Cantidad de eventos por estado; los estados sin eventos cuentan 0."""
    filas = dict(db.execute(select(Evento.estado, func.count()).group_by(Evento.estado)).all())
    return {estado: filas.get(estado, 0) for estado in EstadoEvento}


def contar_deportes(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Deporte).where(Deporte.activo.is_(True))) or 0
