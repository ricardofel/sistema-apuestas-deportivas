from decimal import Decimal

import pytest
from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import Dinero


class _Base(DeclarativeBase):
    pass


class _Padre(_Base):
    __tablename__ = "padre"
    id: Mapped[int] = mapped_column(primary_key=True)
    monto: Mapped[Decimal] = mapped_column(Dinero)
    __table_args__ = (CheckConstraint("monto >= 0"),)


class _Hijo(_Base):
    __tablename__ = "hijo"
    id: Mapped[int] = mapped_column(primary_key=True)
    padre_id: Mapped[int] = mapped_column(ForeignKey("padre.id"))


@pytest.fixture()
def tablas(db):
    _Base.metadata.create_all(db.get_bind())
    return db


def test_portada_y_openapi(client):
    assert client.get("/").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_dinero_no_pierde_precision(tablas):
    tablas.add(_Padre(id=1, monto=Decimal("0.1") + Decimal("0.2")))
    tablas.commit()
    assert tablas.get(_Padre, 1).monto == Decimal("0.30")


def test_dinero_acepta_float_y_str(tablas):
    tablas.add_all([_Padre(id=1, monto=1.15), _Padre(id=2, monto="2.50")])
    tablas.commit()
    assert tablas.get(_Padre, 1).monto == Decimal("1.15")
    assert tablas.get(_Padre, 2).monto == Decimal("2.50")


def test_check_rechaza_monto_negativo(tablas):
    tablas.add(_Padre(id=1, monto=Decimal("-0.01")))
    with pytest.raises(IntegrityError):
        tablas.commit()


def test_claves_foraneas_activas(tablas):
    tablas.add(_Hijo(id=1, padre_id=999))
    with pytest.raises(IntegrityError):
        tablas.commit()
