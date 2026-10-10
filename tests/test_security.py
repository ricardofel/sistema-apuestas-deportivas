from datetime import UTC, datetime, timedelta
from uuid import uuid4

from jose import jwt

from app.core.config import settings
from app.core.security import (
    crear_token_acceso,
    hashear_password,
    obtener_usuario_id_de_token,
    verificar_password,
)


def test_hash_no_guarda_la_contrasena_en_claro():
    assert hashear_password("secreta123") != "secreta123"


def test_verificar_password_correcta_e_incorrecta():
    password_hash = hashear_password("secreta123")
    assert verificar_password("secreta123", password_hash)
    assert not verificar_password("otra-clave", password_hash)


def test_mismo_password_genera_hashes_distintos():
    assert hashear_password("secreta123") != hashear_password("secreta123")


def test_token_devuelve_el_id_del_usuario():
    usuario_id = uuid4()
    assert obtener_usuario_id_de_token(crear_token_acceso(usuario_id)) == usuario_id


def test_token_expirado_es_invalido():
    token = crear_token_acceso(uuid4(), expira_en=timedelta(seconds=-1))
    assert obtener_usuario_id_de_token(token) is None


def test_token_alterado_es_invalido():
    token = crear_token_acceso(uuid4())
    assert obtener_usuario_id_de_token(token[:-2] + "xx") is None


def test_token_firmado_con_otra_clave_es_invalido():
    payload = {"sub": str(uuid4()), "exp": datetime.now(UTC) + timedelta(minutes=5)}
    token = jwt.encode(payload, "otra-clave", algorithm=settings.ALGORITHM)
    assert obtener_usuario_id_de_token(token) is None


def test_token_sin_sub_o_con_sub_invalido_es_invalido():
    exp = datetime.now(UTC) + timedelta(minutes=5)
    sin_sub = jwt.encode({"exp": exp}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    sub_malo = jwt.encode(
        {"sub": "no-es-uuid", "exp": exp}, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    assert obtener_usuario_id_de_token(sin_sub) is None
    assert obtener_usuario_id_de_token(sub_malo) is None
    assert obtener_usuario_id_de_token("basura") is None
