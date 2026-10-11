from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_usuario_actual, requiere_admin
from app.db.enums import EstadoBoleto
from app.modules.apuestas import service
from app.modules.apuestas.schemas import BoletoCreadoOut, BoletoIn, BoletoOut, Pagina
from app.modules.usuarios.models import Usuario

router = APIRouter(tags=["Apuestas"])


@router.post("/boletos", response_model=BoletoCreadoOut, status_code=status.HTTP_201_CREATED)
def crear_boleto(
    datos: BoletoIn,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    boleto, saldo_restante = service.crear_boleto(db, usuario, datos)
    descripcion = service.describir_boleto(db, boleto)
    return BoletoCreadoOut(**descripcion.model_dump(), saldo_restante=saldo_restante)


# Debe ir antes de /boletos/{boleto_id}: si no, "mios" se toma como UUID y da 422.
@router.get("/boletos/mios", response_model=Pagina[BoletoOut])
def mis_boletos(
    estado: EstadoBoleto | None = None,
    limite: int = Query(20, ge=1, le=100),
    desplazamiento: int = Query(0, ge=0),
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    boletos, total = service.listar_boletos(db, usuario.id, estado, limite, desplazamiento)
    return Pagina[BoletoOut](
        items=service.describir_boletos(db, boletos),
        total=total,
        limite=limite,
        desplazamiento=desplazamiento,
    )


@router.get("/boletos/{boleto_id}", response_model=BoletoOut)
def ver_boleto(
    boleto_id: UUID,
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    return service.describir_boleto(db, service.obtener_boleto(db, boleto_id, usuario))


@router.get(
    "/admin/boletos",
    response_model=Pagina[BoletoOut],
    dependencies=[Depends(requiere_admin)],
)
def todos_los_boletos(
    estado: EstadoBoleto | None = None,
    usuario_id: UUID | None = None,
    limite: int = Query(20, ge=1, le=100),
    desplazamiento: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    boletos, total = service.listar_boletos(db, usuario_id, estado, limite, desplazamiento)
    return Pagina[BoletoOut](
        items=service.describir_boletos(db, boletos),
        total=total,
        limite=limite,
        desplazamiento=desplazamiento,
    )
