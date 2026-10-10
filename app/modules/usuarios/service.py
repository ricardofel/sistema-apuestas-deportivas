from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hashear_password, verificar_password
from app.db.enums import RolUsuario
from app.modules.usuarios.models import Usuario


def obtener_por_id(db: Session, usuario_id: UUID) -> Usuario | None:
    return db.get(Usuario, usuario_id)


def obtener_por_email(db: Session, email: str) -> Usuario | None:
    return db.scalar(select(Usuario).where(Usuario.email == email.strip().lower()))


def listar_usuarios(db: Session, limite: int = 50, desplazamiento: int = 0) -> list[Usuario]:
    consulta = select(Usuario).order_by(Usuario.creado_en, Usuario.email).limit(limite).offset(desplazamiento)
    return list(db.scalars(consulta))


def crear_usuario(
    db: Session,
    email: str,
    nombre_usuario: str,
    password: str,
    rol: RolUsuario = RolUsuario.USUARIO,
) -> Usuario:
    email = email.strip().lower()
    if obtener_por_email(db, email):
        raise HTTPException(status.HTTP_409_CONFLICT, "El email ya está registrado")
    if db.scalar(select(Usuario.id).where(Usuario.nombre_usuario == nombre_usuario)):
        raise HTTPException(status.HTTP_409_CONFLICT, "El nombre de usuario ya está en uso")

    usuario = Usuario(
        email=email,
        nombre_usuario=nombre_usuario,
        password_hash=hashear_password(password),
        rol=rol,
    )
    db.add(usuario)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "El email o el nombre de usuario ya existen")
    return usuario


def modificar_saldo(db: Session, usuario_id: UUID, delta: Decimal) -> Decimal:
    """Suma `delta` al saldo (negativo para restar) en un único UPDATE atómico.

    La condición `saldo + delta >= 0` va dentro del propio UPDATE, así dos peticiones
    simultáneas no pueden gastar el mismo saldo. No hace commit: lo hace quien llama.
    """
    nuevo_saldo = Usuario.saldo + delta
    saldo = db.execute(
        update(Usuario)
        .where(Usuario.id == usuario_id, nuevo_saldo >= 0)
        .values(saldo=nuevo_saldo)
        .returning(Usuario.saldo)
        .execution_options(synchronize_session="fetch")
    ).scalar_one_or_none()
    if saldo is None:
        if db.get(Usuario, usuario_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Saldo insuficiente")
    return saldo


def autenticar(db: Session, email: str, password: str) -> Usuario:
    usuario = obtener_por_email(db, email)
    if usuario is None or not verificar_password(password, usuario.password_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Credenciales inválidas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not usuario.activo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La cuenta está desactivada")
    return usuario
