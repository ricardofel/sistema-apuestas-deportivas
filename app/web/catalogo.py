from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_usuario_opcional
from app.db.enums import EstadoEvento
from app.modules.catalogo import service as catalogo_service
from app.modules.usuarios.models import Usuario
from app.web import admin_catalogo
from app.web.templating import HORA_ECUADOR, templates

router = APIRouter()
router.include_router(admin_catalogo.router)

MAS_PARTIDOS = 5

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip


PALABRAS_SIN_INICIAL = {"de", "del", "la", "el", "los", "las", "fc", "sc", "cd", "cf"}
COLORES_EQUIPO = 8


def iniciales_equipo(nombre: str) -> str:
    """Dos letras para el monograma: 'Universidad Católica' -> 'UC', 'Barcelona SC' -> 'BA'."""
    palabras = [p for p in nombre.split() if p.lower() not in PALABRAS_SIN_INICIAL] or nombre.split() or ["?"]
    if len(palabras) >= 2:
        return (palabras[0][0] + palabras[1][0]).upper()
    return palabras[0][:2].upper()


def color_equipo(nombre: str) -> int:
    """Índice 0..7 estable para el color del monograma (no usa hash(), que cambia en cada arranque)."""
    return sum(ord(letra) for letra in nombre.casefold()) % COLORES_EQUIPO


templates.env.globals["iniciales_equipo"] = iniciales_equipo
templates.env.globals["color_equipo"] = color_equipo


def _etiqueta_dia(dia: date, hoy: date) -> str:
    """'Hoy, martes 13 de octubre', 'Mañana, ...' o 'Jueves 15 de octubre'."""
    texto = f"{DIAS[dia.weekday()]} {dia.day} de {MESES[dia.month - 1]}"
    diferencia = (dia - hoy).days
    if diferencia == 0:
        return f"Hoy, {texto}"
    if diferencia == 1:
        return f"Mañana, {texto}"
    return texto.capitalize()


def _separar_destacado(grupos: list[dict]) -> tuple[dict | None, list[dict]]:
    """El primer partido (el más próximo) sale de la lista y va al bloque destacado; no se repite abajo."""
    if not grupos:
        return None, []
    primero, *resto = grupos
    (evento, hora), *demas = primero["partidos"]
    destacado = {
        "evento": evento,
        "hora": hora,
        "dia": primero["etiqueta"],
        "con_empate": any(c.activa and c.seleccion.value == "EMPATE" for c in evento.cuotas),
    }
    if demas:
        resto = [{**primero, "partidos": demas}, *resto]
    return destacado, resto


def _agrupar_por_dia(eventos: list) -> list[dict]:
    """Agrupa los eventos (ya ordenados por inicio) por día de Ecuador, con la hora local de cada uno."""
    hoy = datetime.now(UTC).astimezone(HORA_ECUADOR).date()
    grupos: dict[date, list] = {}
    for evento in eventos:
        inicio = evento.inicia_en.replace(tzinfo=UTC).astimezone(HORA_ECUADOR)
        grupos.setdefault(inicio.date(), []).append((evento, inicio.strftime("%H:%M")))
    return [
        {
            "etiqueta": _etiqueta_dia(dia, hoy),
            "partidos": partidos,
            "con_empate": any(
                c.activa and c.seleccion.value == "EMPATE" for evento, _ in partidos for c in evento.cuotas
            ),
        }
        for dia, partidos in grupos.items()
    ]


@router.get("/eventos")
def lista_eventos(
    request: Request,
    deporte: int | None = Query(None),
    usuario: Usuario | None = Depends(get_usuario_opcional),
    db: Session = Depends(get_db),
):
    eventos = catalogo_service.listar_eventos(db, deporte)
    destacado, grupos = _separar_destacado(_agrupar_por_dia(eventos))
    contexto = {
        "usuario": usuario,
        "deportes": catalogo_service.listar_deportes(db),
        "eventos": eventos,
        "destacado": destacado,
        "grupos": grupos,
        "deporte_activo": deporte,
        "resultados": catalogo_service.listar_ultimos_resultados(db),
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
    # Próximos partidos abiertos del mismo deporte, para seguir navegando sin volver a la lista.
    otros = [e for e in catalogo_service.listar_eventos(db, evento.deporte_id) if e.id != evento.id]
    contexto = {
        "usuario": usuario,
        "evento": evento,
        "apostable": evento.estado == EstadoEvento.PROGRAMADO and evento.inicia_en > ahora,
        "otros_grupos": _agrupar_por_dia(otros[:MAS_PARTIDOS]),
    }
    return templates.TemplateResponse(request, "eventos/detalle.html", contexto)
