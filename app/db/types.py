from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Integer, TypeDecorator

_CENTAVOS = Decimal(100)
_DOS_DECIMALES = Decimal("0.01")


class Dinero(TypeDecorator):
    """Decimal en Python, centavos enteros en la base.

    SQLite no tiene decimal nativo. Guardar enteros (en vez de texto) mantiene
    correctos los CHECK, el orden y las sumas. Por eso los CHECK se escriben en
    centavos: saldo >= 0, pero una cuota mayor a 1.00 es "valor > 100".
    """

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        centavos = Decimal(str(value)) * _CENTAVOS
        return int(centavos.to_integral_value(rounding=ROUND_HALF_UP))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (Decimal(value) / _CENTAVOS).quantize(_DOS_DECIMALES)
