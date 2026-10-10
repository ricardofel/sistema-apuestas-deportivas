from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_usuario_opcional
from app.modules.catalogo import service as catalogo_service
from app.modules.usuarios.models import Usuario
from app.web.templating import templates

router = APIRouter()


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
