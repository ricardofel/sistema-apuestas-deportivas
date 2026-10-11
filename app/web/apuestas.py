from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_usuario_opcional
from app.db.enums import EstadoBoleto
from app.modules.apuestas import service as apuestas_service
from app.modules.usuarios.models import Usuario
from app.web.templating import templates

router = APIRouter()

BOLETOS_POR_PAGINA = 10


def _redirigir(destino: str) -> RedirectResponse:
    return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)


def _estado_valido(valor: str | None) -> EstadoBoleto | None:
    """El filtro llega como texto; uno desconocido se ignora en vez de dar error."""
    try:
        return EstadoBoleto(valor) if valor else None
    except ValueError:
        return None


@router.get("/mis-boletos")
def mis_boletos(
    request: Request,
    estado: str | None = Query(None),
    pagina: int = Query(1, ge=1),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if usuario is None:
        return _redirigir("/login")
    filtro = _estado_valido(estado)
    boletos, total = apuestas_service.listar_boletos(
        db, usuario.id, filtro, BOLETOS_POR_PAGINA, (pagina - 1) * BOLETOS_POR_PAGINA
    )
    contexto = {
        "usuario": usuario,
        "boletos": apuestas_service.describir_boletos(db, boletos),
        "estado_activo": filtro.value if filtro else None,
        "estados": list(EstadoBoleto),
        "pagina": pagina,
        "paginas": max(1, ceil(total / BOLETOS_POR_PAGINA)),
        "total": total,
    }
    return templates.TemplateResponse(request, "boletos/lista.html", contexto)


@router.get("/boleto/{boleto_id}")
def detalle_boleto(
    request: Request,
    boleto_id: str,
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if usuario is None:
        return _redirigir("/login")
    try:
        # Un id mal escrito se trata igual que uno inexistente: 404, no 422.
        boleto = apuestas_service.obtener_boleto(db, UUID(boleto_id), usuario)
    except (ValueError, HTTPException):
        return templates.TemplateResponse(
            request, "boletos/no_encontrado.html", {"usuario": usuario}, status_code=status.HTTP_404_NOT_FOUND
        )
    contexto = {"usuario": usuario, "boleto": apuestas_service.describir_boleto(db, boleto)}
    return templates.TemplateResponse(request, "boletos/detalle.html", contexto)
