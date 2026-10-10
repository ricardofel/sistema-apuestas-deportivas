"""Fábricas de datos para tests: crean filas válidas con valores por defecto y hacen commit."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.enums import TipoSeleccion
from app.modules.apuestas.models import Boleto
from app.modules.catalogo.models import Cuota, Deporte, Evento


def crear_deporte(db, nombre="Fútbol") -> Deporte:
    deporte = Deporte(nombre=nombre)
    db.add(deporte)
    db.commit()
    return deporte


def crear_evento(db, deporte=None, **campos) -> Evento:
    deporte = deporte or crear_deporte(db)
    datos = {
        "deporte_id": deporte.id,
        "equipo_local": "Barcelona",
        "equipo_visitante": "LDU",
        "inicia_en": datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
    }
    datos.update(campos)
    evento = Evento(**datos)
    db.add(evento)
    db.commit()
    return evento


def crear_cuota(db, evento=None, seleccion=TipoSeleccion.LOCAL, valor=Decimal("2.00")) -> Cuota:
    evento = evento or crear_evento(db)
    cuota = Cuota(evento_id=evento.id, seleccion=seleccion, valor=valor)
    db.add(cuota)
    db.commit()
    return cuota


def crear_boleto(db, usuario, monto=Decimal("10.00"), cuota_total=Decimal("2.00")) -> Boleto:
    boleto = Boleto(
        usuario_id=usuario.id,
        monto=monto,
        cuota_total=cuota_total,
        ganancia_potencial=monto * cuota_total,
    )
    db.add(boleto)
    db.commit()
    return boleto
