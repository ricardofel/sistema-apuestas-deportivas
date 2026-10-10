import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.db.enums import RolUsuario
from app.modules.usuarios import service
from scripts.crear_admin import crear_admin


def test_crea_un_usuario_con_rol_admin_que_puede_iniciar_sesion(db):
    admin = crear_admin(db, "Admin@Correo.com", "admin", "clave-segura-1")
    assert admin.rol == RolUsuario.ADMIN
    assert admin.email == "admin@correo.com"
    assert service.autenticar(db, "admin@correo.com", "clave-segura-1").id == admin.id


def test_no_permite_duplicar_el_email(db):
    crear_admin(db, "admin@correo.com", "admin", "clave-segura-1")
    with pytest.raises(HTTPException) as error:
        crear_admin(db, "admin@correo.com", "otro", "clave-segura-1")
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    "email, nombre, password",
    [("no-es-email", "admin", "clave-segura-1"), ("a@correo.com", "ab", "clave-segura-1"), ("a@correo.com", "admin", "corta")],
)
def test_rechaza_datos_invalidos(db, email, nombre, password):
    with pytest.raises(ValidationError):
        crear_admin(db, email, nombre, password)
