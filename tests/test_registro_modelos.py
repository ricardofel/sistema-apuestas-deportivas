import os
import subprocess
import sys

TABLAS = {"usuarios", "transacciones", "deportes", "eventos", "cuotas", "boletos", "selecciones"}


def test_usar_la_sesion_registra_todos_los_modelos():
    """En un proceso nuevo (como el servidor o un script) no debe faltar ninguna tabla."""
    codigo = (
        "import app.db.session\n"
        "from app.db.base import Base\n"
        "print(' '.join(sorted(Base.metadata.tables)))"
    )
    entorno = {**os.environ, "SECRET_KEY": "clave-de-prueba", "DATABASE_URL": "sqlite://"}
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], capture_output=True, text=True, env=entorno, check=True
    )
    assert set(resultado.stdout.split()) == TABLAS
