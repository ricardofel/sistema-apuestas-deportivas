import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import settings


@pytest.fixture()
def url_base_temporal(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migraciones.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    return url


def _tablas(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_las_migraciones_suben_y_bajan_sin_errores(url_base_temporal):
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    assert _tablas(url_base_temporal) == {
        "usuarios",
        "transacciones",
        "deportes",
        "eventos",
        "cuotas",
        "boletos",
        "selecciones",
    }

    command.downgrade(config, "base")
    assert _tablas(url_base_temporal) == set()
