"""Crea un usuario administrador (con las migraciones ya aplicadas).

Uso: python -m scripts.crear_admin --email admin@correo.com --nombre admin
La contraseña se pide por teclado (no se muestra ni queda en el historial de la terminal).
"""
import argparse
import getpass
import sys

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.enums import RolUsuario
from app.db.session import SessionLocal
from app.modules.usuarios import service
from app.modules.usuarios.models import Usuario
from app.modules.usuarios.schemas import RegistroIn


def crear_admin(db: Session, email: str, nombre_usuario: str, password: str) -> Usuario:
    datos = RegistroIn(email=email, nombre_usuario=nombre_usuario, password=password)
    return service.crear_usuario(db, datos.email, datos.nombre_usuario, datos.password, RolUsuario.ADMIN)


def main() -> int:
    parser = argparse.ArgumentParser(description="Crea un usuario administrador.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--nombre", required=True, help="nombre de usuario")
    argumentos = parser.parse_args()

    password = getpass.getpass("Contraseña (mínimo 8 caracteres): ")
    if password != getpass.getpass("Repite la contraseña: "):
        print("Las contraseñas no coinciden.")
        return 1

    with SessionLocal() as db:
        try:
            admin = crear_admin(db, argumentos.email, argumentos.nombre, password)
        except ValidationError:
            print("Datos inválidos: revisa el email, el nombre (3 a 50 caracteres) y la contraseña (8 a 72 bytes).")
            return 1
        except HTTPException as error:
            print(error.detail)
            return 1
    print(f"Administrador creado: {admin.email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
