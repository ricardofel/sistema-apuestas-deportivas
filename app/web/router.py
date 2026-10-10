from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.core.dependencies import get_usuario_opcional
from app.modules.usuarios.models import Usuario
from app.web import apuestas, catalogo, usuarios
from app.web.templating import templates

router = APIRouter(include_in_schema=False)

router.include_router(usuarios.router)
router.include_router(catalogo.router)
router.include_router(apuestas.router)


@router.get("/", response_class=HTMLResponse)
def index(request: Request, usuario: Usuario | None = Depends(get_usuario_opcional)):
    return templates.TemplateResponse(request, "index.html", {"usuario": usuario})
