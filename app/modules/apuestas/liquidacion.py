"""Liquidación y cancelación de boletos (contrato con el Integrante B).

Reglas del contrato:
- No hace commit: solo flush. Quien llama (catálogo) hace commit o rollback de todo.
- Idempotente: un boleto con `liquidado_en` ya no se vuelve a tocar, así nunca se paga dos veces.
- Importa catalogo.service a nivel de módulo; catálogo importa este módulo de forma perezosa
  (dentro de sus funciones) para evitar el import circular.
"""
from datetime import UTC, datetime
from decimal import Decimal
from math import prod
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.enums import EstadoBoleto, EstadoSeleccion, TipoTransaccion
from app.modules.apuestas.models import Boleto, Seleccion
from app.modules.apuestas.service import redondear
from app.modules.billetera import service as billetera_service
from app.modules.catalogo import service as catalogo_service


def _ahora() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def liquidar_evento(db: Session, evento_id: UUID) -> dict:
    """Marca las selecciones del evento y cierra los boletos que ya tienen desenlace."""
    evento = catalogo_service.obtener_evento(db, evento_id)
    if evento.resultado is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El evento no tiene resultado")

    # 1. Selecciones pendientes del evento -> ACERTADA o FALLIDA.
    selecciones = list(
        db.scalars(
            select(Seleccion).where(
                Seleccion.evento_id == evento_id, Seleccion.estado == EstadoSeleccion.PENDIENTE
            )
        )
    )
    cuotas = catalogo_service.obtener_cuotas(db, {s.cuota_id for s in selecciones})
    acertadas = fallidas = 0
    for seleccion in selecciones:
        if cuotas[seleccion.cuota_id].seleccion == evento.resultado:
            seleccion.estado = EstadoSeleccion.ACERTADA
            acertadas += 1
        else:
            seleccion.estado = EstadoSeleccion.FALLIDA
            fallidas += 1
    db.flush()

    # 2. Boletos afectados que aún no se liquidaron.
    resumen = {
        "selecciones_acertadas": acertadas,
        "selecciones_fallidas": fallidas,
        "boletos_ganados": 0,
        "boletos_perdidos": 0,
        "boletos_pendientes": 0,
        "premios_acreditados": Decimal("0.00"),
    }
    ahora = _ahora()
    for boleto in _boletos_sin_liquidar(db, {s.boleto_id for s in selecciones}):
        estado = cerrar_boleto_si_corresponde(db, boleto, ahora)
        if estado == EstadoBoleto.GANADO:
            resumen["boletos_ganados"] += 1
            resumen["premios_acreditados"] += boleto.ganancia_potencial
        elif estado == EstadoBoleto.PERDIDO:
            resumen["boletos_perdidos"] += 1
        else:
            resumen["boletos_pendientes"] += 1

    db.flush()
    return resumen


def procesar_cancelacion_evento(db: Session, evento_id: UUID) -> dict:
    """Anula las selecciones del evento cancelado y reembolsa o recalcula sus boletos.

    - Boleto con todas sus selecciones anuladas -> REEMBOLSADO y se devuelve el monto.
    - Boleto con selecciones vivas -> se recalcula cuota_total y ganancia_potencial sin
      las anuladas, y se aplica la regla de cierre (puede quedar GANADO o seguir PENDIENTE).
    """
    catalogo_service.obtener_evento(db, evento_id)  # 404 si no existe

    selecciones = list(
        db.scalars(
            select(Seleccion).where(
                Seleccion.evento_id == evento_id, Seleccion.estado == EstadoSeleccion.PENDIENTE
            )
        )
    )
    for seleccion in selecciones:
        seleccion.estado = EstadoSeleccion.ANULADA
    db.flush()

    resumen = {
        "selecciones_anuladas": len(selecciones),
        "boletos_recalculados": 0,
        "boletos_reembolsados": 0,
        "monto_reembolsado": Decimal("0.00"),
    }
    ahora = _ahora()
    for boleto in _boletos_sin_liquidar(db, {s.boleto_id for s in selecciones}):
        vivas = [s for s in boleto.selecciones if s.estado != EstadoSeleccion.ANULADA]
        if not vivas:
            boleto.estado = EstadoBoleto.REEMBOLSADO
            boleto.liquidado_en = ahora
            billetera_service.acreditar(
                db,
                boleto.usuario_id,
                boleto.monto,
                TipoTransaccion.REEMBOLSO,
                boleto.id,
                f"Reembolso boleto {str(boleto.id)[:8]}",
            )
            resumen["boletos_reembolsados"] += 1
            resumen["monto_reembolsado"] += boleto.monto
        else:
            # Se usan las cuotas congeladas: el contrato se respeta sin el evento cancelado.
            boleto.cuota_total = redondear(prod(s.cuota_congelada for s in vivas))
            boleto.ganancia_potencial = redondear(boleto.monto * boleto.cuota_total)
            cerrar_boleto_si_corresponde(db, boleto, ahora)
            resumen["boletos_recalculados"] += 1

    db.flush()
    return resumen


def cerrar_boleto_si_corresponde(db: Session, boleto: Boleto, ahora: datetime) -> EstadoBoleto:
    """Aplica la regla de cierre a un boleto sin liquidar y devuelve su estado.

    - Alguna selección FALLIDA -> PERDIDO (aunque otras sigan pendientes).
    - Todas las selecciones no anuladas ACERTADAS -> GANADO y se acredita el premio.
    - Si no, sigue PENDIENTE (espera otros eventos).
    """
    vivas = [s for s in boleto.selecciones if s.estado != EstadoSeleccion.ANULADA]

    if any(s.estado == EstadoSeleccion.FALLIDA for s in vivas):
        boleto.estado = EstadoBoleto.PERDIDO
        boleto.liquidado_en = ahora
    elif vivas and all(s.estado == EstadoSeleccion.ACERTADA for s in vivas):
        boleto.estado = EstadoBoleto.GANADO
        boleto.liquidado_en = ahora
        billetera_service.acreditar(
            db,
            boleto.usuario_id,
            boleto.ganancia_potencial,
            TipoTransaccion.PREMIO,
            boleto.id,
            f"Premio boleto {str(boleto.id)[:8]}",
        )
    return boleto.estado


def _boletos_sin_liquidar(db: Session, boleto_ids: set[UUID]) -> list[Boleto]:
    if not boleto_ids:
        return []
    consulta = (
        select(Boleto)
        .where(Boleto.id.in_(boleto_ids), Boleto.liquidado_en.is_(None))
        .options(selectinload(Boleto.selecciones))
    )
    return list(db.scalars(consulta))
