from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import NOMBRE_COOKIE_TOKEN, get_db, get_usuario_opcional
from app.core.security import crear_token_acceso
from app.db.enums import RolUsuario
from app.modules.billetera import service as billetera_service
from app.modules.billetera.schemas import RecargaIn
from app.modules.usuarios import service as usuarios_service
from app.modules.usuarios.models import Usuario
from app.modules.usuarios.schemas import RegistroIn
from app.web.templating import templates

router = APIRouter()

TRANSACCIONES_POR_PAGINA = 10

MENSAJES_VALIDACION = {
    "email": "Ingresa un email válido",
    "nombre_usuario": "El nombre de usuario debe tener entre 3 y 50 caracteres",
    "password": "La contraseña debe tener entre 8 y 72 caracteres",
    "monto": "Ingresa un monto mayor que cero, con hasta 2 decimales",
}


def _redirigir(destino: str) -> RedirectResponse:
    return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)


def _abrir_sesion(destino: str, usuario: Usuario) -> RedirectResponse:
    respuesta = _redirigir(destino)
    respuesta.set_cookie(
        NOMBRE_COOKIE_TOKEN,
        crear_token_acceso(usuario.id),
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
    )
    return respuesta


def _mensaje_validacion(error: ValidationError) -> str:
    campo = error.errors()[0]["loc"][0]
    return MENSAJES_VALIDACION.get(campo, "Los datos ingresados no son válidos")


@router.get("/login")
def formulario_login(request: Request, usuario: Usuario | None = Depends(get_usuario_opcional)):
    if usuario:
        return _redirigir("/")
    return templates.TemplateResponse(request, "auth/login.html", {"error": None, "email": ""})


@router.post("/login")
def iniciar_sesion(
    request: Request,
    email: str = Form(),
    password: str = Form(),
    db: Session = Depends(get_db),
):
    try:
        usuario = usuarios_service.autenticar(db, email, password)
    except HTTPException as error:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": error.detail, "email": email},
            status_code=error.status_code,
        )
    return _abrir_sesion("/", usuario)


@router.get("/registro")
def formulario_registro(request: Request, usuario: Usuario | None = Depends(get_usuario_opcional)):
    if usuario:
        return _redirigir("/")
    return _pagina_registro(request, error=None, email="", nombre_usuario="")


@router.post("/registro")
def registrarse(
    request: Request,
    email: str = Form(),
    nombre_usuario: str = Form(),
    password: str = Form(),
    db: Session = Depends(get_db),
):
    try:
        datos = RegistroIn(email=email, nombre_usuario=nombre_usuario, password=password)
        usuario = usuarios_service.crear_usuario(db, datos.email, datos.nombre_usuario, datos.password)
    except ValidationError as error:
        return _pagina_registro(
            request, _mensaje_validacion(error), email, nombre_usuario, status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    except HTTPException as error:
        return _pagina_registro(request, error.detail, email, nombre_usuario, error.status_code)
    return _abrir_sesion("/", usuario)


@router.post("/logout")
def cerrar_sesion():
    respuesta = _redirigir("/")
    respuesta.delete_cookie(NOMBRE_COOKIE_TOKEN)
    return respuesta


@router.get("/web/saldo")
def fragmento_saldo(request: Request, usuario: Usuario | None = Depends(get_usuario_opcional)):
    """Fragmento HTMX que refresca el saldo de la navbar (evento `saldo-actualizado`)."""
    if usuario is None:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    return templates.TemplateResponse(request, "billetera/_saldo_nav.html", {"usuario": usuario})


@router.get("/billetera")
def pantalla_billetera(
    request: Request,
    pagina: int = Query(1, ge=1),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if usuario is None:
        return _redirigir("/login")
    transacciones, total = billetera_service.listar_transacciones(
        db, usuario.id, TRANSACCIONES_POR_PAGINA, (pagina - 1) * TRANSACCIONES_POR_PAGINA
    )
    contexto = {
        "usuario": usuario,
        "transacciones": transacciones,
        "pagina": pagina,
        "paginas": max(1, ceil(total / TRANSACCIONES_POR_PAGINA)),
    }
    return templates.TemplateResponse(request, "billetera/index.html", contexto)


@router.get("/admin/billetera")
def formulario_recarga(
    request: Request,
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if (rechazo := _rechazar_si_no_admin(usuario)) is not None:
        return rechazo
    return _pagina_recarga(request, db, usuario)


@router.post("/admin/billetera/recargar")
def recargar(
    request: Request,
    usuario_id: UUID = Form(),
    monto: str = Form(),
    descripcion: str = Form(default=""),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if (rechazo := _rechazar_si_no_admin(usuario)) is not None:
        return rechazo
    try:
        datos = RecargaIn(usuario_id=usuario_id, monto=monto, descripcion=descripcion.strip() or None)
        transaccion = billetera_service.recargar_saldo(db, datos.usuario_id, datos.monto, datos.descripcion)
    except ValidationError as error:
        return _pagina_recarga(
            request, db, usuario, error=_mensaje_validacion(error), codigo=status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    except HTTPException as error:
        return _pagina_recarga(request, db, usuario, error=error.detail, codigo=error.status_code)
    destinatario = usuarios_service.obtener_por_id(db, transaccion.usuario_id)
    mensaje = f"Se recargaron {transaccion.monto} créditos a {destinatario.nombre_usuario}. Nuevo saldo: {transaccion.saldo_posterior}"
    return _pagina_recarga(request, db, usuario, mensaje=mensaje)


def _pagina_registro(request: Request, error: str | None, email: str, nombre_usuario: str, codigo: int = 200):
    contexto = {"error": error, "email": email, "nombre_usuario": nombre_usuario}
    return templates.TemplateResponse(request, "auth/registro.html", contexto, status_code=codigo)


def _rechazar_si_no_admin(usuario: Usuario | None) -> RedirectResponse | None:
    if usuario is None:
        return _redirigir("/login")
    if usuario.rol != RolUsuario.ADMIN:
        return _redirigir("/")
    return None


def _pagina_recarga(
    request: Request,
    db: Session,
    usuario: Usuario,
    mensaje: str | None = None,
    error: str | None = None,
    codigo: int = 200,
):
    contexto = {
        "usuario": usuario,
        "usuarios": usuarios_service.listar_usuarios(db, limite=200),
        "mensaje": mensaje,
        "error": error,
    }
    return templates.TemplateResponse(request, "billetera/recarga.html", contexto, status_code=codigo)
