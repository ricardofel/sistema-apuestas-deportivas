from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_usuario_actual, requiere_admin
from app.modules.billetera import service
from app.modules.billetera.schemas import (
    PaginaTransacciones,
    RecargaIn,
    SaldoOut,
    TransaccionOut,
)
from app.modules.usuarios.models import Usuario

router = APIRouter(tags=["Billetera"])


@router.get("/billetera/saldo", response_model=SaldoOut)
def saldo(usuario: Usuario = Depends(get_usuario_actual)):
    return SaldoOut(saldo=usuario.saldo)


@router.get("/billetera/transacciones", response_model=PaginaTransacciones)
def transacciones(
    limite: int = Query(20, ge=1, le=100),
    desplazamiento: int = Query(0, ge=0),
    usuario: Usuario = Depends(get_usuario_actual),
    db: Session = Depends(get_db),
):
    items, total = service.listar_transacciones(db, usuario.id, limite, desplazamiento)
    return PaginaTransacciones(
        items=items, total=total, limite=limite, desplazamiento=desplazamiento
    )


@router.post(
    "/admin/billetera/recargar",
    response_model=TransaccionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requiere_admin)],
)
def recargar(datos: RecargaIn, db: Session = Depends(get_db)):
    return service.recargar_saldo(db, datos.usuario_id, datos.monto, datos.descripcion)
