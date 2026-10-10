from collections.abc import Generator
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.db.session import SessionLocal

if TYPE_CHECKING:
    from app.modules.usuarios.models import Usuario


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Los implementa el Integrante A. Los demás módulos ya pueden usarlos con Depends().
def get_usuario_actual() -> "Usuario":
    raise NotImplementedError("Pendiente: Integrante A")


def requiere_admin() -> "Usuario":
    raise NotImplementedError("Pendiente: Integrante A")
