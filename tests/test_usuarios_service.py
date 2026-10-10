import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.db.enums import RolUsuario
from app.modules.usuarios import service
from app.modules.usuarios.schemas import RegistroIn


def _registro(**campos) -> dict:
    datos = {"email": "ana@correo.com", "nombre_usuario": "ana", "password": "secreta123"}
    datos.update(campos)
    return datos


def _crear(db, **campos):
    return service.crear_usuario(db, **_registro(**campos))


class TestSchemaRegistro:
    def test_datos_validos(self):
        datos = RegistroIn(**_registro(nombre_usuario="  ana  "))
        assert datos.nombre_usuario == "ana"

    @pytest.mark.parametrize(
        "campos",
        [
            {"email": "no-es-email"},
            {"nombre_usuario": "ab"},
            {"nombre_usuario": "x" * 51},
            {"password": "corta"},
            {"password": "ñ" * 37},
        ],
    )
    def test_datos_invalidos(self, campos):
        with pytest.raises(ValidationError):
            RegistroIn(**_registro(**campos))


class TestCrearUsuario:
    def test_crea_usuario_con_password_hasheada(self, db):
        usuario = _crear(db)
        assert usuario.rol == RolUsuario.USUARIO
        assert usuario.password_hash != "secreta123"

    def test_normaliza_el_email(self, db):
        usuario = _crear(db, email="  Ana@Correo.COM ")
        assert usuario.email == "ana@correo.com"

    def test_email_duplicado_devuelve_409(self, db):
        _crear(db)
        with pytest.raises(HTTPException) as error:
            _crear(db, email="ANA@correo.com", nombre_usuario="otra")
        assert error.value.status_code == 409

    def test_nombre_usuario_duplicado_devuelve_409(self, db):
        _crear(db)
        with pytest.raises(HTTPException) as error:
            _crear(db, email="otra@correo.com")
        assert error.value.status_code == 409

    def test_puede_crear_administrador(self, db):
        assert _crear(db, rol=RolUsuario.ADMIN).rol == RolUsuario.ADMIN


class TestAutenticar:
    def test_credenciales_correctas(self, db):
        creado = _crear(db)
        assert service.autenticar(db, "ANA@correo.com", "secreta123").id == creado.id

    @pytest.mark.parametrize(
        "email, password",
        [("ana@correo.com", "incorrecta"), ("nadie@correo.com", "secreta123")],
    )
    def test_credenciales_invalidas_devuelven_401(self, db, email, password):
        _crear(db)
        with pytest.raises(HTTPException) as error:
            service.autenticar(db, email, password)
        assert error.value.status_code == 401

    def test_cuenta_desactivada_devuelve_403(self, db):
        usuario = _crear(db)
        usuario.activo = False
        db.commit()
        with pytest.raises(HTTPException) as error:
            service.autenticar(db, "ana@correo.com", "secreta123")
        assert error.value.status_code == 403


class TestConsultas:
    def test_obtener_por_id_y_por_email(self, db):
        usuario = _crear(db)
        assert service.obtener_por_id(db, usuario.id).email == "ana@correo.com"
        assert service.obtener_por_email(db, "Ana@Correo.com").id == usuario.id
        assert service.obtener_por_email(db, "nadie@correo.com") is None

    def test_listar_con_paginacion(self, db):
        for numero in range(5):
            _crear(db, email=f"u{numero}@correo.com", nombre_usuario=f"usuario{numero}")
        assert len(service.listar_usuarios(db)) == 5
        assert len(service.listar_usuarios(db, limite=2)) == 2
        assert len(service.listar_usuarios(db, limite=10, desplazamiento=3)) == 2
