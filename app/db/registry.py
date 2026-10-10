"""Importa todos los modelos para que queden registrados en Base.metadata.

Lo usan Alembic (autogenerate) y los tests. Está separado de base.py para evitar
un import circular: los modelos importan Base desde app.db.base.
"""
from app.modules.apuestas import models as _apuestas  # noqa: F401
from app.modules.billetera import models as _billetera  # noqa: F401
from app.modules.catalogo import models as _catalogo  # noqa: F401
from app.modules.usuarios import models as _usuarios  # noqa: F401
