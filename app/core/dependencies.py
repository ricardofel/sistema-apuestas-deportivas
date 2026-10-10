from collections.abc import Generator

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import obtener_usuario_id_de_token
from app.db.enums import RolUsuario
from app.db.session import SessionLocal
from app.modules.usuarios import service as usuarios_service
from app.modules.usuarios.models import Usuario

NOMBRE_COOKIE_TOKEN = "access_token"

_esquema_bearer = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_usuario_opcional(
    db: Session = Depends(get_db),
    token_header: str | None = Depends(_esquema_bearer),
    token_cookie: str | None = Cookie(default=None, alias=NOMBRE_COOKIE_TOKEN),
) -> Usuario | None:
    """Usuario del token (header Bearer o cookie), o None si no hay sesión válida."""
    token = token_header or token_cookie
    if not token:
        return None
    usuario_id = obtener_usuario_id_de_token(token)
    if usuario_id is None:
        return None
    usuario = usuarios_service.obtener_por_id(db, usuario_id)
    if usuario is None or not usuario.activo:
        return None
    return usuario


def get_usuario_actual(usuario: Usuario | None = Depends(get_usuario_opcional)) -> Usuario:
    if usuario is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "No autenticado o sesión expirada",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return usuario


def requiere_admin(usuario: Usuario = Depends(get_usuario_actual)) -> Usuario:
    if usuario.rol != RolUsuario.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acceso solo para administradores")
    return usuario
