import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, requiere_admin
from app.db.enums import EstadoEvento
from app.modules.catalogo import service
from app.modules.catalogo.schemas import (
    CancelacionEventoOut,
    CuotaEditarIn,
    CuotaOut,
    CuotasIn,
    DeporteIn,
    DeporteOut,
    EventoEditarIn,
    EventoIn,
    EventoOut,
    LiquidacionOut,
    Pagina,
    ReembolsoOut,
    ResultadoEventoOut,
    ResultadoIn,
)

router = APIRouter(tags=["Catálogo"])


@router.get("/deportes", response_model=list[DeporteOut])
def deportes(db: Session = Depends(get_db)):
    return service.listar_deportes(db)


@router.post(
    "/admin/deportes",
    response_model=DeporteOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requiere_admin)],
)
def crear_deporte(datos: DeporteIn, db: Session = Depends(get_db)):
    return service.crear_deporte(db, datos.nombre)


@router.get("/eventos", response_model=Pagina[EventoOut])
def eventos(
    deporte_id: int | None = Query(None),
    estado: EstadoEvento | None = Query(None),
    limite: int = Query(20, ge=1, le=100),
    desplazamiento: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    items, total = service.listar_eventos_paginado(db, deporte_id, estado, limite, desplazamiento)
    return Pagina[EventoOut](items=items, total=total, limite=limite, desplazamiento=desplazamiento)


@router.get("/eventos/{evento_id}", response_model=EventoOut)
def detalle_evento(evento_id: uuid.UUID, db: Session = Depends(get_db)):
    return service.obtener_detalle_evento(db, evento_id)


@router.post(
    "/admin/eventos",
    response_model=EventoOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requiere_admin)],
)
def crear_evento(datos: EventoIn, db: Session = Depends(get_db)):
    return service.crear_evento(db, datos)


@router.patch(
    "/admin/eventos/{evento_id}",
    response_model=EventoOut,
    dependencies=[Depends(requiere_admin)],
)
def editar_evento(evento_id: uuid.UUID, datos: EventoEditarIn, db: Session = Depends(get_db)):
    return service.editar_evento(db, evento_id, datos)


@router.post(
    "/admin/eventos/{evento_id}/cuotas",
    response_model=list[CuotaOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requiere_admin)],
)
def crear_cuotas(evento_id: uuid.UUID, datos: CuotasIn, db: Session = Depends(get_db)):
    return service.crear_cuotas(db, evento_id, datos)


@router.patch(
    "/admin/cuotas/{cuota_id}",
    response_model=CuotaOut,
    dependencies=[Depends(requiere_admin)],
)
def editar_cuota(cuota_id: uuid.UUID, datos: CuotaEditarIn, db: Session = Depends(get_db)):
    return service.editar_cuota(db, cuota_id, datos)


@router.post(
    "/admin/eventos/{evento_id}/resultado",
    response_model=ResultadoEventoOut,
    dependencies=[Depends(requiere_admin)],
)
def registrar_resultado(evento_id: uuid.UUID, datos: ResultadoIn, db: Session = Depends(get_db)):
    evento, resumen = service.registrar_resultado(db, evento_id, datos.resultado)
    return ResultadoEventoOut(evento=evento, liquidacion=LiquidacionOut(**resumen))


@router.post(
    "/admin/eventos/{evento_id}/cancelar",
    response_model=CancelacionEventoOut,
    dependencies=[Depends(requiere_admin)],
)
def cancelar_evento(evento_id: uuid.UUID, db: Session = Depends(get_db)):
    evento, resumen = service.cancelar_evento(db, evento_id)
    return CancelacionEventoOut(evento=evento, reembolsos=ReembolsoOut(**resumen))
