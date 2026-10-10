from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web import apuestas, catalogo, usuarios
from app.web.templating import templates

router = APIRouter(include_in_schema=False)

router.include_router(usuarios.router)
router.include_router(catalogo.router)
router.include_router(apuestas.router)


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")
