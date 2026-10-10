"""Carga deportes, eventos y cuotas de ejemplo (equipos ecuatorianos).

Uso, con las migraciones aplicadas:
    python -m scripts.seed               carga los datos si la base no tiene deportes
    python -m scripts.seed --reiniciar   borra el catálogo y lo carga de nuevo con fechas frescas
"""
import argparse
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.enums import TipoSeleccion
from app.db.session import SessionLocal
from app.modules.catalogo.models import Cuota, Deporte, Evento

UTC_EN_ECUADOR = timedelta(hours=-5)
HORARIOS = [time(15, 0), time(17, 30), time(19, 30), time(20, 0)]
PARTIDOS_POR_DIA = len(HORARIOS)

# (deporte, local, visitante, cuota local, cuota empate o None, cuota visitante)
PARTIDOS = [
    ("Fútbol", "Barcelona SC", "Emelec", "2.35", "3.10", "2.95"),
    ("Fútbol", "Liga de Quito", "Independiente del Valle", "2.45", "3.15", "2.80"),
    ("Fútbol", "Aucas", "El Nacional", "2.10", "3.20", "3.50"),
    ("Fútbol", "Deportivo Cuenca", "Macará", "2.20", "3.10", "3.30"),
    ("Fútbol", "Delfín SC", "Orense SC", "1.95", "3.30", "3.90"),
    ("Fútbol", "Universidad Católica", "Técnico Universitario", "2.30", "3.05", "3.10"),
    ("Fútbol", "Mushuc Runa", "Libertad FC", "2.60", "3.00", "2.75"),
    ("Fútbol", "Guayaquil City", "Cumbayá FC", "2.05", "3.20", "3.60"),
    ("Fútbol", "Emelec", "Liga de Quito", "3.10", "3.20", "2.25"),
    ("Fútbol", "Independiente del Valle", "Barcelona SC", "1.80", "3.40", "4.30"),
    ("Fútbol", "El Nacional", "Deportivo Cuenca", "2.55", "3.00", "2.85"),
    ("Fútbol", "Macará", "Aucas", "3.40", "3.25", "2.10"),
    ("Fútbol", "Ecuador", "Colombia", "2.50", "3.10", "2.90"),
    ("Fútbol", "Ecuador", "Perú", "1.70", "3.50", "5.00"),
    ("Tenis", "Emilio Gómez", "Roberto Quiroz", "1.45", None, "2.75"),
    ("Tenis", "Gonzalo Escobar", "Diego Hidalgo", "1.60", None, "2.30"),
]


def _inicio(numero: int) -> datetime:
    """Hora de inicio en UTC (naive) de un horario de Ecuador, desde mañana en adelante."""
    hoy_ecuador: date = (datetime.now(UTC) + UTC_EN_ECUADOR).date()
    dia = hoy_ecuador + timedelta(days=1 + numero // PARTIDOS_POR_DIA)
    hora_local = datetime.combine(dia, HORARIOS[numero % PARTIDOS_POR_DIA])
    return hora_local - UTC_EN_ECUADOR


def cargar(db: Session) -> bool:
    """Crea el catálogo de ejemplo. Devuelve False si ya había deportes y no hizo nada."""
    if db.scalar(select(Deporte.id).limit(1)) is not None:
        return False

    deportes: dict[str, Deporte] = {}
    for numero, (nombre_deporte, local, visitante, c_local, c_empate, c_visitante) in enumerate(PARTIDOS):
        if nombre_deporte not in deportes:
            deportes[nombre_deporte] = Deporte(nombre=nombre_deporte)
            db.add(deportes[nombre_deporte])
            db.flush()
        evento = Evento(
            deporte_id=deportes[nombre_deporte].id,
            equipo_local=local,
            equipo_visitante=visitante,
            inicia_en=_inicio(numero),
        )
        db.add(evento)
        db.flush()
        for seleccion, valor in (
            (TipoSeleccion.LOCAL, c_local),
            (TipoSeleccion.EMPATE, c_empate),
            (TipoSeleccion.VISITANTE, c_visitante),
        ):
            if valor is not None:
                db.add(Cuota(evento_id=evento.id, seleccion=seleccion, valor=Decimal(valor)))
    db.commit()
    return True


def reiniciar(db: Session) -> bool:
    """Borra el catálogo. Devuelve False si hay boletos que dependen de él."""
    try:
        db.execute(delete(Cuota))
        db.execute(delete(Evento))
        db.execute(delete(Deporte))
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga datos de ejemplo del catálogo deportivo.")
    parser.add_argument("--reiniciar", action="store_true", help="borra el catálogo antes de cargarlo")
    argumentos = parser.parse_args()

    with SessionLocal() as db:
        if argumentos.reiniciar and not reiniciar(db):
            print("No se puede reiniciar: ya hay boletos que usan estos eventos.")
            return
        if cargar(db):
            print(f"Catálogo cargado: {len(PARTIDOS)} eventos.")
        else:
            print("Ya hay deportes cargados: no se agregó nada (usa --reiniciar para recargar).")


if __name__ == "__main__":
    main()
