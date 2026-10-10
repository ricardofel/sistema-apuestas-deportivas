from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.enums import TipoTransaccion
from app.modules.billetera.models import Transaccion
from app.modules.usuarios import service as usuarios_service


def debitar(
    db: Session, usuario_id: UUID, monto: Decimal, boleto_id: UUID, descripcion: str
) -> Transaccion:
    """Descuenta `monto` del saldo y registra la transacción APUESTA (con monto negativo).

    Lanza 400 si el saldo no alcanza. No hace commit: forma parte de la transacción de quien llama.
    """
    _validar_monto(monto)
    return _registrar(db, usuario_id, -monto, TipoTransaccion.APUESTA, boleto_id, descripcion)


def acreditar(
    db: Session,
    usuario_id: UUID,
    monto: Decimal,
    tipo: TipoTransaccion,
    boleto_id: UUID | None,
    descripcion: str,
) -> Transaccion:
    """Suma `monto` al saldo y registra la transacción (RECARGA, PREMIO o REEMBOLSO).

    No hace commit: forma parte de la transacción de quien llama.
    """
    _validar_monto(monto)
    if tipo == TipoTransaccion.APUESTA:
        raise ValueError("Una APUESTA descuenta saldo: usar debitar()")
    return _registrar(db, usuario_id, monto, tipo, boleto_id, descripcion)


def recargar_saldo(
    db: Session, usuario_id: UUID, monto: Decimal, descripcion: str | None = None
) -> Transaccion:
    transaccion = acreditar(
        db, usuario_id, monto, TipoTransaccion.RECARGA, None, descripcion or "Recarga de saldo"
    )
    db.commit()
    return transaccion


def listar_transacciones(
    db: Session, usuario_id: UUID, limite: int = 20, desplazamiento: int = 0
) -> tuple[list[Transaccion], int]:
    propias = Transaccion.usuario_id == usuario_id
    total = db.scalar(select(func.count()).select_from(Transaccion).where(propias))
    consulta = (
        select(Transaccion)
        .where(propias)
        .order_by(Transaccion.creado_en.desc())
        .limit(limite)
        .offset(desplazamiento)
    )
    return list(db.scalars(consulta)), total


def _validar_monto(monto: Decimal) -> None:
    if monto <= 0:
        raise ValueError("El monto debe ser mayor que cero")


def _registrar(
    db: Session,
    usuario_id: UUID,
    delta: Decimal,
    tipo: TipoTransaccion,
    boleto_id: UUID | None,
    descripcion: str,
) -> Transaccion:
    saldo_posterior = usuarios_service.modificar_saldo(db, usuario_id, delta)
    transaccion = Transaccion(
        usuario_id=usuario_id,
        boleto_id=boleto_id,
        tipo=tipo,
        monto=delta,
        saldo_posterior=saldo_posterior,
        descripcion=descripcion,
    )
    db.add(transaccion)
    db.flush()
    return transaccion
