"""Pantallas de administración del catálogo (rutas /admin/...). Solo para el rol ADMIN."""
import logging
from datetime import UTC, datetime
from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_usuario_opcional
from app.db.enums import EstadoEvento, RolUsuario, TipoSeleccion
from app.modules.catalogo import service as catalogo_service
from app.modules.catalogo.schemas import (
    CuotaEditarIn,
    CuotasIn,
    DeporteIn,
    EventoEditarIn,
    EventoIn,
    ResultadoIn,
)
from app.modules.usuarios.models import Usuario
from app.web.templating import HORA_ECUADOR, templates

router = APIRouter()
logger = logging.getLogger(__name__)

EVENTOS_POR_PAGINA = 20

MENSAJES_VALIDACION = {
    "deporte_id": "Elige un deporte",
    "equipo_local": "El equipo local debe tener entre 1 y 100 caracteres",
    "equipo_visitante": "El equipo visitante debe tener entre 1 y 100 caracteres",
    "inicia_en": "Ingresa una fecha de inicio válida",
    "nombre": "El nombre del deporte debe tener entre 1 y 50 caracteres",
    "valor": "Cada cuota debe ser un número mayor que 1.00, con hasta 2 decimales",
    "resultado": "Elige un resultado válido",
}

SELECCIONES = [
    (TipoSeleccion.LOCAL, "Local"),
    (TipoSeleccion.EMPATE, "Empate"),
    (TipoSeleccion.VISITANTE, "Visitante"),
]


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
        # Para las cuotas, el campo que falla es el último tramo (cuotas.0.valor).
        return MENSAJES_VALIDACION.get(primero["loc"][-1], "Los datos ingresados no son válidos")
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


def _uuid_o_none(valor: str) -> UUID | None:
    try:
        return UUID(valor)
    except ValueError:
        return None


def _a_hora_ecuador(valor: datetime) -> str:
    """Fecha en UTC (sin zona) con el formato que espera `<input type="datetime-local">`."""
    return valor.replace(tzinfo=UTC).astimezone(HORA_ECUADOR).strftime("%Y-%m-%dT%H:%M")


def _no_encontrado(request: Request, usuario: Usuario):
    return templates.TemplateResponse(
        request, "eventos/no_encontrado.html", {"usuario": usuario}, status_code=status.HTTP_404_NOT_FOUND
    )


def _pagina_evento(
    request: Request,
    db: Session,
    usuario: Usuario,
    evento_id: UUID,
    *,
    formulario: dict | None = None,
    formulario_cuotas: dict | None = None,
    mensaje: str | None = None,
    error: str | None = None,
    codigo: int = 200,
):
    try:
        evento = catalogo_service.obtener_detalle_evento(db, evento_id, solo_cuotas_activas=False)
    except HTTPException:
        return _no_encontrado(request, usuario)
    por_seleccion = {cuota.seleccion: cuota for cuota in evento.cuotas}
    contexto = {
        "usuario": usuario,
        "evento": evento,
        "deportes": catalogo_service.listar_deportes(db),
        "cuotas": [(seleccion, etiqueta, por_seleccion.get(seleccion)) for seleccion, etiqueta in SELECCIONES],
        "formulario": formulario
        or {
            "deporte_id": str(evento.deporte_id),
            "equipo_local": evento.equipo_local,
            "equipo_visitante": evento.equipo_visitante,
            "inicia_en": _a_hora_ecuador(evento.inicia_en),
        },
        "formulario_cuotas": formulario_cuotas or {},
        "mensaje": mensaje,
        "error": error,
    }
    return templates.TemplateResponse(request, "admin/evento.html", contexto, status_code=codigo)


@router.get("/admin/eventos/{evento_id}")
def gestion_evento(
    request: Request,
    evento_id: str,
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if (rechazo := _rechazar_si_no_admin(usuario)) is not None:
        return rechazo
    if (id_evento := _uuid_o_none(evento_id)) is None:
        return _no_encontrado(request, usuario)
    return _pagina_evento(request, db, usuario, id_evento)


@router.post("/admin/eventos/{evento_id}/editar")
def editar_evento(
    request: Request,
    evento_id: str,
    deporte_id: str = Form(default=""),
    equipo_local: str = Form(default=""),
    equipo_visitante: str = Form(default=""),
    inicia_en: str = Form(default=""),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if (rechazo := _rechazar_si_no_admin(usuario)) is not None:
        return rechazo
    if (id_evento := _uuid_o_none(evento_id)) is None:
        return _no_encontrado(request, usuario)
    formulario = {
        "deporte_id": deporte_id,
        "equipo_local": equipo_local,
        "equipo_visitante": equipo_visitante,
        "inicia_en": inicia_en,
    }
    try:
        fecha = _fecha_ecuador_a_utc(inicia_en)
    except ValueError:
        return _pagina_evento(
            request, db, usuario, id_evento, formulario=formulario, error=MENSAJES_VALIDACION["inicia_en"],
            codigo=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    try:
        datos = EventoEditarIn(
            deporte_id=deporte_id, equipo_local=equipo_local, equipo_visitante=equipo_visitante, inicia_en=fecha
        )
        catalogo_service.editar_evento(db, id_evento, datos)
    except ValidationError as error:
        return _pagina_evento(
            request, db, usuario, id_evento, formulario=formulario, error=_mensaje_validacion(error),
            codigo=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except HTTPException as error:
        return _pagina_evento(request, db, usuario, id_evento, formulario=formulario, error=error.detail, codigo=error.status_code)
    return _pagina_evento(request, db, usuario, id_evento, mensaje="Evento actualizado")


@router.post("/admin/eventos/{evento_id}/cuotas")
def cargar_cuotas(
    request: Request,
    evento_id: str,
    cuota_local: str = Form(default=""),
    cuota_empate: str = Form(default=""),
    cuota_visitante: str = Form(default=""),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if (rechazo := _rechazar_si_no_admin(usuario)) is not None:
        return rechazo
    if (id_evento := _uuid_o_none(evento_id)) is None:
        return _no_encontrado(request, usuario)
    formulario = {"local": cuota_local, "empate": cuota_empate, "visitante": cuota_visitante}
    valores = [
        (TipoSeleccion.LOCAL, cuota_local),
        (TipoSeleccion.EMPATE, cuota_empate),
        (TipoSeleccion.VISITANTE, cuota_visitante),
    ]
    # La cuota de empate es opcional: en blanco significa que el deporte no tiene empate.
    pedidas = [{"seleccion": seleccion, "valor": valor} for seleccion, valor in valores if valor.strip() or seleccion != TipoSeleccion.EMPATE]
    try:
        cuotas = catalogo_service.crear_cuotas(db, id_evento, CuotasIn(cuotas=pedidas))
    except ValidationError as error:
        return _pagina_evento(
            request, db, usuario, id_evento, formulario_cuotas=formulario, error=_mensaje_validacion(error),
            codigo=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except HTTPException as error:
        return _pagina_evento(request, db, usuario, id_evento, formulario_cuotas=formulario, error=error.detail, codigo=error.status_code)
    return _pagina_evento(request, db, usuario, id_evento, mensaje=f"Se cargaron {len(cuotas)} cuotas")


@router.post("/admin/cuotas/{cuota_id}/editar")
def editar_cuota(
    request: Request,
    cuota_id: str,
    valor: str = Form(default=""),
    activa: str = Form(default=""),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if (rechazo := _rechazar_si_no_admin(usuario)) is not None:
        return rechazo
    if (id_cuota := _uuid_o_none(cuota_id)) is None:
        return _no_encontrado(request, usuario)
    try:
        evento_id = catalogo_service.obtener_cuota(db, id_cuota).evento_id
    except HTTPException:
        return _no_encontrado(request, usuario)
    try:
        datos = CuotaEditarIn(valor=valor.strip() or None, activa={"true": True, "false": False}.get(activa))
        cuota = catalogo_service.editar_cuota(db, id_cuota, datos)
    except ValidationError as error:
        return _pagina_evento(
            request, db, usuario, evento_id, error=_mensaje_validacion(error),
            codigo=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except HTTPException as error:
        return _pagina_evento(request, db, usuario, evento_id, error=error.detail, codigo=error.status_code)
    estado = "activada" if cuota.activa else "desactivada"
    texto = f"Cuota {estado}" if datos.valor is None else f"Cuota actualizada a {cuota.valor}"
    return _pagina_evento(request, db, usuario, evento_id, mensaje=texto)


def _cerrar_evento(request: Request, db: Session, usuario: Usuario, evento_id: UUID, operacion):
    """Ejecuta `operacion() -> mensaje` (resultado o cancelación) y re-renderiza la gestión del evento."""
    try:
        mensaje = operacion()
    except ValidationError as error:
        return _pagina_evento(
            request, db, usuario, evento_id, error=_mensaje_validacion(error),
            codigo=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except HTTPException as error:
        return _pagina_evento(request, db, usuario, evento_id, error=error.detail, codigo=error.status_code)
    except Exception:
        # El servicio ya hizo rollback: el evento sigue como estaba y nada quedó a medias.
        logger.exception("Falló el cierre del evento %s", evento_id)
        return _pagina_evento(
            request, db, usuario, evento_id,
            error="No se pudo completar la operación y no se guardó ningún cambio. Inténtalo de nuevo.",
            codigo=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return _pagina_evento(request, db, usuario, evento_id, mensaje=mensaje)


@router.post("/admin/eventos/{evento_id}/resultado")
def registrar_resultado(
    request: Request,
    evento_id: str,
    resultado: str = Form(default=""),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if (rechazo := _rechazar_si_no_admin(usuario)) is not None:
        return rechazo
    if (id_evento := _uuid_o_none(evento_id)) is None:
        return _no_encontrado(request, usuario)

    def operacion() -> str:
        datos = ResultadoIn(resultado=resultado)
        _, resumen = catalogo_service.registrar_resultado(db, id_evento, datos.resultado)
        return (
            f"Resultado registrado. Boletos ganados: {resumen['boletos_ganados']}, "
            f"perdidos: {resumen['boletos_perdidos']}, pendientes: {resumen['boletos_pendientes']}. "
            f"Premios acreditados: {resumen['premios_acreditados']}"
        )

    return _cerrar_evento(request, db, usuario, id_evento, operacion)


@router.post("/admin/eventos/{evento_id}/cancelar")
def cancelar_evento(
    request: Request,
    evento_id: str,
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    if (rechazo := _rechazar_si_no_admin(usuario)) is not None:
        return rechazo
    if (id_evento := _uuid_o_none(evento_id)) is None:
        return _no_encontrado(request, usuario)

    def operacion() -> str:
        _, resumen = catalogo_service.cancelar_evento(db, id_evento)
        return (
            f"Evento cancelado. Boletos reembolsados: {resumen['boletos_reembolsados']}. "
            f"Monto reembolsado: {resumen['monto_reembolsado']}"
        )

    return _cerrar_evento(request, db, usuario, id_evento, operacion)
