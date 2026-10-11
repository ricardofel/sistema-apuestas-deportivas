from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_usuario_opcional
from app.db.enums import EstadoEvento
from app.modules.catalogo import service as catalogo_service
from app.modules.usuarios.models import Usuario
from app.web import admin_catalogo
from app.web.templating import templates

router = APIRouter()
router.include_router(admin_catalogo.router)


@router.get("/eventos")
def lista_eventos(
    request: Request,
    deporte: int | None = Query(None),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    contexto = {
        "usuario": usuario,
        "deportes": catalogo_service.listar_deportes(db),
        "eventos": catalogo_service.listar_eventos(db, deporte),
        "deporte_activo": deporte,
    }
    # Con HTMX (filtro por deporte) solo se devuelve el fragmento, no la página completa.
    es_fragmento = "HX-Request" in request.headers and "HX-History-Restore-Request" not in request.headers
    plantilla = "eventos/_lista.html" if es_fragmento else "eventos/lista.html"
    return templates.TemplateResponse(request, plantilla, contexto)


@router.get("/eventos/{evento_id}")
def detalle_evento(
    request: Request,
    evento_id: str,
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    try:
        evento = catalogo_service.obtener_detalle_evento(db, UUID(evento_id))
    except (ValueError, HTTPException):
        return templates.TemplateResponse(request, "eventos/no_encontrado.html", {"usuario": usuario}, status_code=404)
    ahora = datetime.now(UTC).replace(tzinfo=None)
    contexto = {
        "usuario": usuario,
        "evento": evento,
        "apostable": evento.estado == EstadoEvento.PROGRAMADO and evento.inicia_en > ahora,
    }
    return templates.TemplateResponse(request, "eventos/detalle.html", contexto)
