from datetime import UTC, datetime, timedelta
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

_contexto_password = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hashear_password(password: str) -> str:
    return _contexto_password.hash(password)


def verificar_password(password: str, password_hash: str) -> bool:
    return _contexto_password.verify(password, password_hash)


def crear_token_acceso(usuario_id: UUID, expira_en: timedelta | None = None) -> str:
    duracion = expira_en or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(usuario_id), "exp": datetime.now(UTC) + duracion}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def obtener_usuario_id_de_token(token: str) -> UUID | None:
    """Devuelve el id del usuario si el token es válido y no expiró; si no, None."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None
