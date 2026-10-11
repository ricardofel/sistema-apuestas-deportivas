"""API JSON del catálogo: rutas públicas, rutas de administración y permisos."""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.security import crear_token_acceso
from app.db.enums import EstadoEvento, RolUsuario, TipoSeleccion
from app.modules.usuarios import service as usuarios_service
from tests.factories import crear_cuota, crear_deporte, crear_evento


def _futuro(horas: int = 24) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=horas)


def _cabecera(usuario) -> dict:
    return {"Authorization": f"Bearer {crear_token_acceso(usuario.id)}"}


@pytest.fixture()
def cab_admin(db):
    admin = usuarios_service.crear_usuario(db, "admin@correo.com", "admin", "clave-segura-1", RolUsuario.ADMIN)
    return _cabecera(admin)


@pytest.fixture()
def cab_usuario(db):
    return _cabecera(usuarios_service.crear_usuario(db, "uno@correo.com", "uno", "clave-segura-1"))


def _body_evento(deporte_id: int, **cambios) -> dict:
    cuerpo = {
        "deporte_id": deporte_id,
        "equipo_local": "Emelec",
        "equipo_visitante": "Aucas",
        "inicia_en": _futuro().isoformat(),
    }
    return {**cuerpo, **cambios}


def _body_cuotas(*pares) -> dict:
    return {"cuotas": [{"seleccion": s, "valor": v} for s, v in pares]}


class TestRutasPublicas:
    def test_deportes_solo_activos_por_nombre(self, client, db):
        crear_deporte(db, "Tenis")
        crear_deporte(db, "Fútbol")
        inactivo = crear_deporte(db, "Ajedrez")
        inactivo.activo = False
        db.commit()
        respuesta = client.get("/api/deportes")
        assert respuesta.status_code == 200
        assert [d["nombre"] for d in respuesta.json()] == ["Fútbol", "Tenis"]

    def test_eventos_devuelve_la_pagina(self, client, db):
        deporte = crear_deporte(db)
        for i in range(3):
            crear_evento(db, deporte, equipo_local=f"Equipo {i}", inicia_en=_futuro(i + 1))
        cuerpo = client.get("/api/eventos", params={"limite": 2, "desplazamiento": 1}).json()
        assert (cuerpo["total"], cuerpo["limite"], cuerpo["desplazamiento"]) == (3, 2, 1)
        assert [e["equipo_local"] for e in cuerpo["items"]] == ["Equipo 1", "Equipo 2"]

    def test_eventos_filtra_por_deporte_y_estado(self, client, db):
        futbol, tenis = crear_deporte(db, "Fútbol"), crear_deporte(db, "Tenis")
        crear_evento(db, futbol)
        buscado = crear_evento(db, tenis, estado=EstadoEvento.CANCELADO)
        cuerpo = client.get("/api/eventos", params={"deporte_id": tenis.id, "estado": "CANCELADO"}).json()
        assert [e["id"] for e in cuerpo["items"]] == [str(buscado.id)]

    @pytest.mark.parametrize("params", [{"limite": 0}, {"limite": 101}, {"desplazamiento": -1}, {"estado": "XX"}])
    def test_eventos_valida_los_parametros_422(self, client, params):
        assert client.get("/api/eventos", params=params).status_code == 422

    def test_cuota_se_serializa_como_texto_decimal(self, client, db):
        evento = crear_evento(db)
        crear_cuota(db, evento, TipoSeleccion.LOCAL, Decimal("2.10"))
        cuota = client.get(f"/api/eventos/{evento.id}").json()["cuotas"][0]
        assert cuota["valor"] == "2.10"

    def test_detalle_solo_con_cuotas_activas(self, client, db):
        evento = crear_evento(db)
        crear_cuota(db, evento, TipoSeleccion.LOCAL)
        apagada = crear_cuota(db, evento, TipoSeleccion.VISITANTE)
        apagada.activa = False
        db.commit()
        cuerpo = client.get(f"/api/eventos/{evento.id}").json()
        assert [c["seleccion"] for c in cuerpo["cuotas"]] == ["LOCAL"]
        assert cuerpo["deporte"]["nombre"] == "Fútbol"

    def test_detalle_inexistente_404(self, client):
        assert client.get(f"/api/eventos/{uuid.uuid4()}").status_code == 404


RUTAS_ADMIN = [
    ("post", "/api/admin/deportes", {"nombre": "Tenis"}),
    ("post", "/api/admin/eventos", {}),
    ("patch", f"/api/admin/eventos/{uuid.uuid4()}", {"equipo_local": "X"}),
    ("post", f"/api/admin/eventos/{uuid.uuid4()}/cuotas", {}),
    ("patch", f"/api/admin/cuotas/{uuid.uuid4()}", {"activa": False}),
]


class TestPermisos:
    @pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), RUTAS_ADMIN)
    def test_sin_token_401(self, client, metodo, ruta, cuerpo):
        assert getattr(client, metodo)(ruta, json=cuerpo).status_code == 401

    @pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), RUTAS_ADMIN)
    def test_usuario_comun_403(self, client, cab_usuario, metodo, ruta, cuerpo):
        assert getattr(client, metodo)(ruta, json=cuerpo, headers=cab_usuario).status_code == 403


class TestAdminDeportes:
    def test_crea_un_deporte(self, client, cab_admin):
        respuesta = client.post("/api/admin/deportes", json={"nombre": " Tenis "}, headers=cab_admin)
        assert respuesta.status_code == 201
        assert respuesta.json()["nombre"] == "Tenis" and respuesta.json()["activo"] is True

    def test_nombre_duplicado_409(self, client, db, cab_admin):
        crear_deporte(db, "Tenis")
        assert client.post("/api/admin/deportes", json={"nombre": "Tenis"}, headers=cab_admin).status_code == 409

    def test_nombre_vacio_422(self, client, cab_admin):
        assert client.post("/api/admin/deportes", json={"nombre": "  "}, headers=cab_admin).status_code == 422


class TestAdminEventos:
    def test_crea_un_evento(self, client, db, cab_admin):
        deporte = crear_deporte(db)
        respuesta = client.post("/api/admin/eventos", json=_body_evento(deporte.id), headers=cab_admin)
        assert respuesta.status_code == 201
        cuerpo = respuesta.json()
        assert cuerpo["estado"] == "PROGRAMADO" and cuerpo["resultado"] is None and cuerpo["cuotas"] == []

    def test_fecha_con_zona_se_guarda_en_utc(self, client, db, cab_admin):
        deporte = crear_deporte(db)
        utc = (_futuro(48)).replace(microsecond=0)
        hora_ecuador = (utc - timedelta(hours=5)).isoformat() + "-05:00"
        cuerpo = client.post(
            "/api/admin/eventos", json=_body_evento(deporte.id, inicia_en=hora_ecuador), headers=cab_admin
        ).json()
        assert cuerpo["inicia_en"] == utc.isoformat()

    def test_deporte_inexistente_404(self, client, cab_admin):
        assert client.post("/api/admin/eventos", json=_body_evento(999), headers=cab_admin).status_code == 404

    def test_deporte_inactivo_400(self, client, db, cab_admin):
        deporte = crear_deporte(db)
        deporte.activo = False
        db.commit()
        assert client.post("/api/admin/eventos", json=_body_evento(deporte.id), headers=cab_admin).status_code == 400

    def test_fecha_pasada_400(self, client, db, cab_admin):
        deporte = crear_deporte(db)
        cuerpo = _body_evento(deporte.id, inicia_en=_futuro(-2).isoformat())
        respuesta = client.post("/api/admin/eventos", json=cuerpo, headers=cab_admin)
        assert (respuesta.status_code, respuesta.json()["detail"]) == (400, "La fecha de inicio debe ser futura")

    def test_equipos_iguales_422(self, client, db, cab_admin):
        deporte = crear_deporte(db)
        cuerpo = _body_evento(deporte.id, equipo_local="LDU", equipo_visitante="ldu")
        assert client.post("/api/admin/eventos", json=cuerpo, headers=cab_admin).status_code == 422

    def test_edita_un_evento(self, client, db, cab_admin):
        evento = crear_evento(db)
        respuesta = client.patch(f"/api/admin/eventos/{evento.id}", json={"equipo_local": "Emelec"}, headers=cab_admin)
        assert respuesta.status_code == 200 and respuesta.json()["equipo_local"] == "Emelec"

    def test_editar_sin_campos_422(self, client, db, cab_admin):
        evento = crear_evento(db)
        assert client.patch(f"/api/admin/eventos/{evento.id}", json={}, headers=cab_admin).status_code == 422

    def test_editar_no_cambia_estado_ni_resultado(self, client, db, cab_admin):
        evento = crear_evento(db)
        cuerpo = {"equipo_local": "Emelec", "estado": "FINALIZADO", "resultado": "LOCAL"}
        respuesta = client.patch(f"/api/admin/eventos/{evento.id}", json=cuerpo, headers=cab_admin).json()
        assert respuesta["estado"] == "PROGRAMADO" and respuesta["resultado"] is None

    def test_editar_evento_cerrado_400(self, client, db, cab_admin):
        evento = crear_evento(db, estado=EstadoEvento.FINALIZADO)
        respuesta = client.patch(f"/api/admin/eventos/{evento.id}", json={"equipo_local": "X"}, headers=cab_admin)
        assert respuesta.status_code == 400

    def test_editar_inexistente_404(self, client, cab_admin):
        respuesta = client.patch(f"/api/admin/eventos/{uuid.uuid4()}", json={"equipo_local": "X"}, headers=cab_admin)
        assert respuesta.status_code == 404


class TestAdminCuotas:
    def test_carga_las_cuotas(self, client, db, cab_admin):
        evento = crear_evento(db)
        cuerpo = _body_cuotas(("LOCAL", "2.10"), ("EMPATE", "3.20"), ("VISITANTE", "3.40"))
        respuesta = client.post(f"/api/admin/eventos/{evento.id}/cuotas", json=cuerpo, headers=cab_admin)
        assert respuesta.status_code == 201
        assert {c["seleccion"]: c["valor"] for c in respuesta.json()} == {
            "LOCAL": "2.10",
            "EMPATE": "3.20",
            "VISITANTE": "3.40",
        }

    @pytest.mark.parametrize(
        "cuerpo",
        [
            _body_cuotas(("LOCAL", "2.00")),
            _body_cuotas(("LOCAL", "2.00"), ("LOCAL", "3.00")),
            _body_cuotas(("LOCAL", "2.00"), ("EMPATE", "3.00")),
            _body_cuotas(("LOCAL", "1.00"), ("VISITANTE", "3.00")),
        ],
    )
    def test_cuotas_invalidas_422(self, client, db, cab_admin, cuerpo):
        evento = crear_evento(db)
        assert client.post(f"/api/admin/eventos/{evento.id}/cuotas", json=cuerpo, headers=cab_admin).status_code == 422

    def test_seleccion_existente_409(self, client, db, cab_admin):
        evento = crear_evento(db)
        crear_cuota(db, evento, TipoSeleccion.LOCAL)
        cuerpo = _body_cuotas(("LOCAL", "2.00"), ("VISITANTE", "3.00"))
        assert client.post(f"/api/admin/eventos/{evento.id}/cuotas", json=cuerpo, headers=cab_admin).status_code == 409

    def test_evento_cerrado_400(self, client, db, cab_admin):
        evento = crear_evento(db, estado=EstadoEvento.CANCELADO)
        cuerpo = _body_cuotas(("LOCAL", "2.00"), ("VISITANTE", "3.00"))
        assert client.post(f"/api/admin/eventos/{evento.id}/cuotas", json=cuerpo, headers=cab_admin).status_code == 400

    def test_evento_inexistente_404(self, client, cab_admin):
        cuerpo = _body_cuotas(("LOCAL", "2.00"), ("VISITANTE", "3.00"))
        respuesta = client.post(f"/api/admin/eventos/{uuid.uuid4()}/cuotas", json=cuerpo, headers=cab_admin)
        assert respuesta.status_code == 404

    def test_edita_el_valor_y_solo_eso(self, client, db, cab_admin):
        evento = crear_evento(db)
        local = crear_cuota(db, evento, TipoSeleccion.LOCAL, Decimal("2.00"))
        visitante = crear_cuota(db, evento, TipoSeleccion.VISITANTE, Decimal("3.00"))
        respuesta = client.patch(f"/api/admin/cuotas/{local.id}", json={"valor": "2.50"}, headers=cab_admin)
        assert respuesta.status_code == 200
        assert respuesta.json()["valor"] == "2.50" and respuesta.json()["seleccion"] == "LOCAL"
        db.refresh(visitante)
        assert visitante.valor == Decimal("3.00")

    def test_desactiva_una_cuota(self, client, db, cab_admin):
        cuota = crear_cuota(db)
        respuesta = client.patch(f"/api/admin/cuotas/{cuota.id}", json={"activa": False}, headers=cab_admin)
        assert respuesta.json()["activa"] is False

    def test_valor_de_evento_cerrado_400(self, client, db, cab_admin):
        cuota = crear_cuota(db, crear_evento(db, estado=EstadoEvento.FINALIZADO))
        respuesta = client.patch(f"/api/admin/cuotas/{cuota.id}", json={"valor": "5.00"}, headers=cab_admin)
        assert respuesta.status_code == 400

    def test_valor_invalido_o_sin_campos_422(self, client, db, cab_admin):
        cuota = crear_cuota(db)
        ruta = f"/api/admin/cuotas/{cuota.id}"
        assert client.patch(ruta, json={"valor": "0.90"}, headers=cab_admin).status_code == 422
        assert client.patch(ruta, json={}, headers=cab_admin).status_code == 422

    def test_cuota_inexistente_404(self, client, cab_admin):
        respuesta = client.patch(f"/api/admin/cuotas/{uuid.uuid4()}", json={"activa": False}, headers=cab_admin)
        assert respuesta.status_code == 404
