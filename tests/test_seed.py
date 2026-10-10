from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.modules.catalogo.models import Cuota, Deporte, Evento
from scripts import seed
from tests.factories import crear_boleto, crear_cuota


def _contar(db, modelo) -> int:
    return db.scalar(select(func.count()).select_from(modelo))


def test_carga_deportes_eventos_y_cuotas(db):
    assert seed.cargar(db) is True
    assert _contar(db, Deporte) >= 2
    assert _contar(db, Evento) >= 10
    assert all(c.valor > Decimal("1.00") for c in db.scalars(select(Cuota)))


def test_todos_los_eventos_son_futuros_y_tienen_cuotas(db):
    seed.cargar(db)
    ahora = datetime.now(UTC).replace(tzinfo=None)
    for evento in db.scalars(select(Evento)):
        assert evento.inicia_en > ahora
        assert len(evento.cuotas) >= 2


def test_es_idempotente(db):
    assert seed.cargar(db) is True
    eventos = _contar(db, Evento)
    assert seed.cargar(db) is False
    assert _contar(db, Evento) == eventos


def test_los_eventos_cargados_aparecen_en_la_pantalla(client, db):
    seed.cargar(db)
    html = client.get("/eventos").text
    for equipo in ("Barcelona SC", "Emelec", "Liga de Quito", "Independiente del Valle"):
        assert equipo in html
    assert "Fútbol" in html and "Tenis" in html


def test_reiniciar_vuelve_a_cargar_el_catalogo(db):
    seed.cargar(db)
    assert seed.reiniciar(db) is True
    assert _contar(db, Evento) == 0
    assert seed.cargar(db) is True
    assert _contar(db, Evento) == len(seed.PARTIDOS)


def test_reiniciar_no_borra_si_hay_boletos_que_dependen(db):
    from app.modules.apuestas.models import Seleccion
    from app.modules.usuarios import service as usuarios_service

    seed.cargar(db)
    cuota = db.scalars(select(Cuota)).first()
    usuario = usuarios_service.crear_usuario(db, "ana@correo.com", "ana", "secreta123")
    boleto = crear_boleto(db, usuario)
    db.add(Seleccion(boleto_id=boleto.id, cuota_id=cuota.id, evento_id=cuota.evento_id, cuota_congelada=cuota.valor))
    db.commit()

    assert seed.reiniciar(db) is False
    assert _contar(db, Evento) == len(seed.PARTIDOS)
