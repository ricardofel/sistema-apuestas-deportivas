"""Pantallas de administración del catálogo (rutas /admin/...). Solo para el rol ADMIN."""
from datetime import UTC, datetime
from math import ceil

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_usuario_opcional
from app.db.enums import EstadoEvento, RolUsuario
from app.modules.catalogo import service as catalogo_service
from app.modules.catalogo.schemas import DeporteIn, EventoIn
from app.modules.usuarios.models import Usuario
from app.web.templating import HORA_ECUADOR, templates

router = APIRouter()

EVENTOS_POR_PAGINA = 20

MENSAJES_VALIDACION = {
    "deporte_id": "Elige un deporte",
    "equipo_local": "El equipo local debe tener entre 1 y 100 caracteres",
    "equipo_visitante": "El equipo visitante debe tener entre 1 y 100 caracteres",
    "inicia_en": "Ingresa una fecha de inicio válida",
    "nombre": "El nombre del deporte debe tener entre 1 y 50 caracteres",
}


def _rechazar_si_no_admin(usuario: Usuario | None) -> RedirectResponse | None:
    """Sin sesión va a /login; con sesión pero sin rol de administrador, al inicio."""
    if usuario is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if usuario.rol != RolUsuario.ADMIN:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return None


def _mensaje_validacion(error: ValidationError) -> str:
    primero = error.errors()[0]
    if primero["loc"]:
        return MENSAJES_VALIDACION.get(primero["loc"][0], "Los datos ingresados no son válidos")
    # Error de varios campos a la vez (ej. equipos iguales): el schema ya trae el mensaje en español.
    return primero["msg"].removeprefix("Value error, ")


def _fecha_ecuador_a_utc(texto: str) -> datetime:
    """`<input type="datetime-local">` entrega hora de Ecuador sin zona; se guarda en UTC (+5 h)."""
    local = datetime.fromisoformat(texto)
    return local.replace(tzinfo=HORA_ECUADOR).astimezone(UTC).replace(tzinfo=None)


def _estado_o_none(valor: str | None) -> EstadoEvento | None:
    try:
        return EstadoEvento(valor) if valor else None
    except ValueError:
        return None


@router.get("/admin")
def panel_admin(
    request: Request,
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if (rechazo := _rechazar_si_no_admin(usuario)) is not None:
        return rechazo
    contexto = {
        "usuario": usuario,
        "eventos_por_estado": catalogo_service.contar_eventos_por_estado(db),
        "total_deportes": catalogo_service.contar_deportes(db),
    }
    return templates.TemplateResponse(request, "admin/index.html", contexto)


def _pagina_eventos(
    request: Request,
    db: Session,
    usuario: Usuario,
    *,
    estado: EstadoEvento | None = None,
    deporte: int | None = None,
    pagina: int = 1,
    formulario: dict | None = None,
    nombre_deporte: str = "",
    mensaje: str | None = None,
    error: str | None = None,
    evento_nuevo=None,
    codigo: int = 200,
):
    eventos, total = catalogo_service.listar_eventos_paginado(
        db, deporte, estado, EVENTOS_POR_PAGINA, (pagina - 1) * EVENTOS_POR_PAGINA, solo_cuotas_activas=False
    )
    contexto = {
        "usuario": usuario,
        "eventos": eventos,
        "deportes": catalogo_service.listar_deportes(db),
        "estados": list(EstadoEvento),
        "estado_activo": estado,
        "deporte_activo": deporte,
        "pagina": pagina,
        "paginas": max(1, ceil(total / EVENTOS_POR_PAGINA)),
        "total": total,
        "formulario": formulario or {},
        "nombre_deporte": nombre_deporte,
        "mensaje": mensaje,
        "error": error,
        "evento_nuevo": evento_nuevo,
    }
    return templates.TemplateResponse(request, "admin/eventos.html", contexto, status_code=codigo)


@router.get("/admin/eventos")
def lista_admin_eventos(
    request: Request,
    estado: str | None = Query(None),
    deporte: int | None = Query(None),
    pagina: int = Query(1, ge=1),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if (rechazo := _rechazar_si_no_admin(usuario)) is not None:
        return rechazo
    return _pagina_eventos(request, db, usuario, estado=_estado_o_none(estado), deporte=deporte, pagina=pagina)


@router.post("/admin/eventos")
def crear_evento(
    request: Request,
    deporte_id: str = Form(default=""),
    equipo_local: str = Form(default=""),
    equipo_visitante: str = Form(default=""),
    inicia_en: str = Form(default=""),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if (rechazo := _rechazar_si_no_admin(usuario)) is not None:
        return rechazo
    formulario = {
        "deporte_id": deporte_id,
        "equipo_local": equipo_local,
        "equipo_visitante": equipo_visitante,
        "inicia_en": inicia_en,
    }
    try:
        fecha = _fecha_ecuador_a_utc(inicia_en)
    except ValueError:
        return _pagina_eventos(
            request, db, usuario, formulario=formulario, error=MENSAJES_VALIDACION["inicia_en"],
            codigo=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    try:
        datos = EventoIn(
            deporte_id=deporte_id, equipo_local=equipo_local, equipo_visitante=equipo_visitante, inicia_en=fecha
        )
        evento = catalogo_service.crear_evento(db, datos)
    except ValidationError as error:
        return _pagina_eventos(
            request, db, usuario, formulario=formulario, error=_mensaje_validacion(error),
            codigo=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except HTTPException as error:
        return _pagina_eventos(request, db, usuario, formulario=formulario, error=error.detail, codigo=error.status_code)
    mensaje = f"Evento creado: {evento.equipo_local} vs {evento.equipo_visitante}"
    return _pagina_eventos(request, db, usuario, mensaje=mensaje, evento_nuevo=evento.id)


@router.post("/admin/deportes")
def crear_deporte(
    request: Request,
    nombre: str = Form(default=""),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if (rechazo := _rechazar_si_no_admin(usuario)) is not None:
        return rechazo
    try:
        datos = DeporteIn(nombre=nombre)
        deporte = catalogo_service.crear_deporte(db, datos.nombre)
    except ValidationError as error:
        return _pagina_eventos(
            request, db, usuario, nombre_deporte=nombre, error=_mensaje_validacion(error),
            codigo=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except HTTPException as error:
        return _pagina_eventos(request, db, usuario, nombre_deporte=nombre, error=error.detail, codigo=error.status_code)
    return _pagina_eventos(request, db, usuario, mensaje=f"Deporte creado: {deporte.nombre}")
