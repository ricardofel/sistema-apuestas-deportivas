from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.enums import RolUsuario
from app.modules.usuarios.models import Usuario


def _usuario(**campos) -> Usuario:
    datos = {"email": "ana@correo.com", "nombre_usuario": "ana", "password_hash": "hash"}
    datos.update(campos)
    return Usuario(**datos)


def test_valores_por_defecto(db):
    usuario = _usuario()
    db.add(usuario)
    db.commit()
    db.refresh(usuario)

    assert usuario.id is not None
    assert usuario.rol == RolUsuario.USUARIO
    assert usuario.saldo == Decimal("0.00")
    assert usuario.activo is True
    assert usuario.creado_en is not None


def test_email_unico(db):
    db.add(_usuario())
    db.commit()
    db.add(_usuario(nombre_usuario="otro"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_nombre_usuario_unico(db):
    db.add(_usuario())
    db.commit()
    db.add(_usuario(email="otro@correo.com"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_saldo_negativo_rechazado(db):
    db.add(_usuario(saldo=Decimal("-0.01")))
    with pytest.raises(IntegrityError):
        db.commit()


def test_saldo_conserva_decimales(db):
    usuario = _usuario(saldo=Decimal("10.55"))
    db.add(usuario)
    db.commit()
    db.expire_all()
    assert db.get(Usuario, usuario.id).saldo == Decimal("10.55")
