from decimal import ROUND_HALF_UP, Decimal
from math import prod
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.enums import EstadoBoleto, RolUsuario
from app.modules.apuestas.models import Boleto, Seleccion
from app.modules.apuestas.schemas import BoletoIn, BoletoOut, SeleccionOut
from app.modules.billetera import service as billetera_service
from app.modules.catalogo import service as catalogo_service
from app.modules.usuarios.models import Usuario

CENTAVO = Decimal("0.01")


def redondear(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def crear_boleto(db: Session, usuario: Usuario, datos: BoletoIn) -> tuple[Boleto, Decimal]:
    """Crea el boleto y cobra el monto, todo o nada.

    Devuelve el boleto y el saldo que le queda al usuario. Si algo falla (cuota no
    apostable, saldo insuficiente...), no queda ninguna fila nueva en la base.
    """
    # Catálogo valida cada cuota: existe, está activa y el evento sigue abierto.
    cuotas = [catalogo_service.obtener_cuota_para_apuesta(db, s.cuota_id) for s in datos.selecciones]
    if len({c.evento_id for c in cuotas}) != len(cuotas):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes apostar dos veces al mismo evento")

    cuota_total = redondear(prod(c.valor for c in cuotas))
    ganancia = redondear(datos.monto * cuota_total)

    try:
        boleto = Boleto(
            usuario_id=usuario.id,
            monto=datos.monto,
            cuota_total=cuota_total,
            ganancia_potencial=ganancia,
            # cuota_congelada copia el valor de ahora: el boleto es un contrato.
            selecciones=[
                Seleccion(cuota_id=c.id, evento_id=c.evento_id, cuota_congelada=c.valor) for c in cuotas
            ],
        )
        db.add(boleto)
        db.flush()  # el boleto debe existir antes de debitar (transacciones.boleto_id es FK)
        transaccion = billetera_service.debitar(
            db, usuario.id, datos.monto, boleto.id, f"Apuesta boleto {str(boleto.id)[:8]}"
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return boleto, transaccion.saldo_posterior


def obtener_boleto(db: Session, boleto_id: UUID, usuario: Usuario) -> Boleto:
    """Boleto del usuario (el admin puede ver cualquiera). 404 si no existe o es ajeno."""
    boleto = db.scalar(
        select(Boleto).where(Boleto.id == boleto_id).options(selectinload(Boleto.selecciones))
    )
    if boleto is None or (boleto.usuario_id != usuario.id and usuario.rol != RolUsuario.ADMIN):
        # Mismo 404 para "no existe" y "es ajeno": no revela qué ids existen.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Boleto no encontrado")
    return boleto


def listar_boletos(
    db: Session,
    usuario_id: UUID | None = None,
    estado: EstadoBoleto | None = None,
    limite: int = 20,
    desplazamiento: int = 0,
) -> tuple[list[Boleto], int]:
    """Boletos más recientes primero. Sin usuario_id lista los de todos (uso del admin)."""
    condiciones = []
    if usuario_id is not None:
        condiciones.append(Boleto.usuario_id == usuario_id)
    if estado is not None:
        condiciones.append(Boleto.estado == estado)

    total = db.scalar(select(func.count()).select_from(Boleto).where(*condiciones))
    consulta = (
        select(Boleto)
        .where(*condiciones)
        .options(selectinload(Boleto.selecciones))
        .order_by(Boleto.creado_en.desc(), Boleto.id)
        .limit(limite)
        .offset(desplazamiento)
    )
    return list(db.scalars(consulta)), total


def describir_boletos(db: Session, boletos: list[Boleto]) -> list[BoletoOut]:
    """Arma la respuesta de cada boleto con el partido y el resultado elegido.

    Pide todas las cuotas de golpe (una sola consulta para toda la lista).
    """
    ids = {s.cuota_id for b in boletos for s in b.selecciones}
    cuotas = catalogo_service.obtener_cuotas(db, ids) if ids else {}
    return [
        BoletoOut(
            id=b.id,
            monto=b.monto,
            cuota_total=b.cuota_total,
            ganancia_potencial=b.ganancia_potencial,
            estado=b.estado,
            creado_en=b.creado_en,
            liquidado_en=b.liquidado_en,
            selecciones=[_describir_seleccion(s, cuotas[s.cuota_id]) for s in b.selecciones],
        )
        for b in boletos
    ]


def describir_boleto(db: Session, boleto: Boleto) -> BoletoOut:
    return describir_boletos(db, [boleto])[0]


def _describir_seleccion(seleccion: Seleccion, cuota) -> SeleccionOut:
    evento = cuota.evento
    return SeleccionOut(
        evento_id=seleccion.evento_id,
        evento=f"{evento.equipo_local} vs {evento.equipo_visitante}",
        seleccion=cuota.seleccion,
        cuota_congelada=seleccion.cuota_congelada,
        estado=seleccion.estado,
    )
