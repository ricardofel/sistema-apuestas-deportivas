from decimal import Decimal
from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_usuario_opcional
from app.db.enums import EstadoBoleto
from app.modules.apuestas import service as apuestas_service
from app.modules.apuestas.schemas import BoletoIn, MontoApuesta, SeleccionIn
from app.modules.catalogo import service as catalogo_service
from app.modules.usuarios.models import Usuario
from app.web.templating import templates

router = APIRouter()

BOLETOS_POR_PAGINA = 10
COOKIE_BORRADOR = "boleto_borrador"
MAX_SELECCIONES = 10
_validar_monto = TypeAdapter(MontoApuesta).validate_python


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


# --- Panel de boleto (fragmentos HTMX) -------------------------------------------------------
# Las respuestas son trozos de HTML que HTMX inserta en <div id="panel-boleto">, dentro de las
# páginas de eventos. Los errores se devuelven con 200: HTMX no inserta respuestas 4xx/5xx.


def _leer_borrador(request: Request) -> list[UUID]:
    """Ids de cuota guardados en la cookie, sin repetidos; los mal formados se ignoran."""
    ids: list[UUID] = []
    for parte in request.cookies.get(COOKIE_BORRADOR, "").split(","):
        try:
            cuota_id = UUID(parte)
        except ValueError:
            continue
        if cuota_id not in ids:
            ids.append(cuota_id)
    return ids


def _cuotas_apostables(db: Session, ids: list[UUID]) -> list:
    """Cuotas del borrador que todavía se pueden apostar (una por evento)."""
    cuotas, eventos = [], set()
    for cuota_id in ids:
        try:
            cuota = catalogo_service.obtener_cuota_para_apuesta(db, cuota_id)
        except HTTPException:
            continue  # ya no es apostable (inactiva, evento iniciado...): se descarta en silencio
        if cuota.evento_id not in eventos:
            cuotas.append(cuota)
            eventos.add(cuota.evento_id)
    return cuotas


def _monto_o_none(texto: str | None) -> Decimal | None:
    try:
        return _validar_monto(texto) if texto else None
    except ValidationError:
        return None


def _panel(
    request: Request,
    db: Session,
    usuario: Usuario | None,
    ids: list[UUID],
    monto: str = "",
    error: str | None = None,
):
    """Pinta el panel con las cuotas válidas del borrador y deja la cookie limpia."""
    if usuario is None:
        return templates.TemplateResponse(request, "boletos/_panel_sin_sesion.html", {})

    cuotas = _cuotas_apostables(db, ids)
    cuota_total = ganancia = None
    if cuotas:
        cuota_total, _ = apuestas_service.cotizar((c.valor for c in cuotas), Decimal("1"))
        if (monto_valido := _monto_o_none(monto)) is not None:
            _, ganancia = apuestas_service.cotizar((c.valor for c in cuotas), monto_valido)

    contexto = {
        "cuotas": cuotas,
        "cuota_total": cuota_total,
        "ganancia": ganancia,
        "monto": monto,
        "error": error,
        "max_selecciones": MAX_SELECCIONES,
    }
    respuesta = templates.TemplateResponse(request, "boletos/_panel.html", contexto)
    _guardar_borrador(respuesta, [c.id for c in cuotas])
    return respuesta


def _guardar_borrador(respuesta, ids: list[UUID]) -> None:
    if ids:
        respuesta.set_cookie(
            COOKIE_BORRADOR, ",".join(str(i) for i in ids), httponly=True, samesite="lax"
        )
    else:
        respuesta.delete_cookie(COOKIE_BORRADOR)


@router.get("/web/boleto/panel")
def panel_boleto(
    request: Request,
    monto: str = Query(""),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    return _panel(request, db, usuario, _leer_borrador(request), monto)


@router.post("/web/boleto/agregar/{cuota_id}")
def agregar_seleccion(
    request: Request,
    cuota_id: UUID,
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    ids = _leer_borrador(request)
    if usuario is None:
        return _panel(request, db, usuario, ids)
    try:
        nueva = catalogo_service.obtener_cuota_para_apuesta(db, cuota_id)
    except HTTPException as error:
        return _panel(request, db, usuario, ids, error=error.detail)

    actuales = _cuotas_apostables(db, ids)
    # Una sola selección por evento: elegir otro resultado del mismo partido la reemplaza.
    restantes = [c.id for c in actuales if c.evento_id != nueva.evento_id]
    if len(restantes) >= MAX_SELECCIONES:
        return _panel(request, db, usuario, ids, error=f"Máximo {MAX_SELECCIONES} selecciones por boleto")
    return _panel(request, db, usuario, restantes + [nueva.id])


@router.post("/web/boleto/quitar/{cuota_id}")
def quitar_seleccion(
    request: Request,
    cuota_id: UUID,
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    ids = [i for i in _leer_borrador(request) if i != cuota_id]
    return _panel(request, db, usuario, ids)


@router.post("/web/boleto/confirmar")
def confirmar_boleto(
    request: Request,
    monto: str = Form(""),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    ids = _leer_borrador(request)
    if usuario is None:
        return _panel(request, db, usuario, ids)
    if not ids:
        return _panel(request, db, usuario, ids, monto, error="Agrega al menos una selección")
    try:
        # Se envían los ids tal cual: si una cuota dejó de ser apostable, crear_boleto
        # explica por qué (en vez de apostar en silencio un boleto distinto al que se vio).
        datos = BoletoIn(monto=monto, selecciones=[SeleccionIn(cuota_id=i) for i in ids])
        boleto, saldo = apuestas_service.crear_boleto(db, usuario, datos)
    except ValidationError as error:
        return _panel(request, db, usuario, ids, monto, error=_mensaje_validacion(error))
    except HTTPException as error:
        return _panel(request, db, usuario, ids, monto, error=error.detail)

    contexto = {"boleto": apuestas_service.describir_boleto(db, boleto), "saldo": saldo}
    respuesta = templates.TemplateResponse(request, "boletos/_confirmado.html", contexto)
    respuesta.delete_cookie(COOKIE_BORRADOR)
    respuesta.headers["HX-Trigger"] = "saldo-actualizado"  # la navbar refresca el saldo
    return respuesta


def _mensaje_validacion(error: ValidationError) -> str:
    if error.errors()[0]["loc"][0] == "monto":
        return "El monto debe estar entre 1.00 y 500.00, con hasta 2 decimales"
    return f"El boleto debe tener entre 1 y {MAX_SELECCIONES} selecciones"
