"""Servicio de catálogo: deportes, eventos y cuotas."""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.db.enums import EstadoEvento, TipoSeleccion
from app.modules.apuestas.models import Seleccion
from app.modules.catalogo import service
from app.modules.catalogo.schemas import CuotaEditarIn, CuotasIn, EventoEditarIn, EventoIn
from app.modules.usuarios import service as usuarios_service
from tests.factories import crear_boleto, crear_cuota, crear_deporte, crear_evento


def _futuro(horas: int = 24) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=horas)


def _error(funcion, *args, **kwargs) -> HTTPException:
    with pytest.raises(HTTPException) as info:
        funcion(*args, **kwargs)
    return info.value


def _evento_in(deporte_id: int, **cambios) -> EventoIn:
    datos = {"deporte_id": deporte_id, "equipo_local": "Emelec", "equipo_visitante": "Aucas", "inicia_en": _futuro()}
    return EventoIn(**{**datos, **cambios})


class TestCrearDeporte:
    def test_crea_un_deporte_activo(self, db):
        deporte = service.crear_deporte(db, "Tenis")
        assert deporte.id is not None
        assert deporte.nombre == "Tenis" and deporte.activo is True

    def test_nombre_duplicado_409(self, db):
        service.crear_deporte(db, "Tenis")
        error = _error(service.crear_deporte, db, "Tenis")
        assert (error.status_code, error.detail) == (409, "Ya existe un deporte con ese nombre")

    def test_duplicado_sin_distinguir_mayusculas_409(self, db):
        service.crear_deporte(db, "Tenis")
        assert _error(service.crear_deporte, db, "tenis").status_code == 409


class TestListarEventosPaginado:
    def test_ordena_por_fecha_de_inicio(self, db):
        deporte = crear_deporte(db)
        tarde = crear_evento(db, deporte, equipo_local="Tarde", inicia_en=_futuro(48))
        pronto = crear_evento(db, deporte, equipo_local="Pronto", inicia_en=_futuro(2))
        eventos, total = service.listar_eventos_paginado(db, limite=20, desplazamiento=0)
        assert [e.id for e in eventos] == [pronto.id, tarde.id]
        assert total == 2

    def test_pagina_con_limite_y_desplazamiento(self, db):
        deporte = crear_deporte(db)
        for i in range(5):
            crear_evento(db, deporte, equipo_local=f"Equipo {i}", inicia_en=_futuro(i + 1))
        eventos, total = service.listar_eventos_paginado(db, limite=2, desplazamiento=2)
        assert [e.equipo_local for e in eventos] == ["Equipo 2", "Equipo 3"]
        assert total == 5

    def test_filtra_por_deporte_y_estado(self, db):
        futbol, tenis = crear_deporte(db, "Fútbol"), crear_deporte(db, "Tenis")
        crear_evento(db, futbol)
        buscado = crear_evento(db, tenis, estado=EstadoEvento.FINALIZADO)
        eventos, total = service.listar_eventos_paginado(
            db, deporte_id=tenis.id, estado=EstadoEvento.FINALIZADO, limite=20, desplazamiento=0
        )
        assert [e.id for e in eventos] == [buscado.id] and total == 1

    def test_incluye_todos_los_estados_si_no_se_filtra(self, db):
        deporte = crear_deporte(db)
        for estado in EstadoEvento:
            crear_evento(db, deporte, estado=estado)
        assert service.listar_eventos_paginado(db, limite=20, desplazamiento=0)[1] == 4

    def test_excluye_deportes_inactivos(self, db):
        activo, inactivo = crear_deporte(db, "Fútbol"), crear_deporte(db, "Esgrima")
        inactivo.activo = False
        db.commit()
        visible = crear_evento(db, activo)
        crear_evento(db, inactivo)
        eventos, total = service.listar_eventos_paginado(db, limite=20, desplazamiento=0)
        assert [e.id for e in eventos] == [visible.id] and total == 1

    def test_solo_trae_cuotas_activas_si_se_pide(self, db):
        evento = crear_evento(db)
        crear_cuota(db, evento, TipoSeleccion.LOCAL)
        apagada = crear_cuota(db, evento, TipoSeleccion.VISITANTE)
        apagada.activa = False
        db.commit()
        publico, _ = service.listar_eventos_paginado(db, limite=20, desplazamiento=0, solo_cuotas_activas=True)
        assert [c.seleccion for c in publico[0].cuotas] == [TipoSeleccion.LOCAL]
        admin, _ = service.listar_eventos_paginado(db, limite=20, desplazamiento=0, solo_cuotas_activas=False)
        assert len(admin[0].cuotas) == 2


class TestDetalleEvento:
    def test_trae_solo_cuotas_activas_por_defecto(self, db):
        evento = crear_evento(db)
        crear_cuota(db, evento, TipoSeleccion.LOCAL)
        apagada = crear_cuota(db, evento, TipoSeleccion.VISITANTE)
        apagada.activa = False
        db.commit()
        detalle = service.obtener_detalle_evento(db, evento.id)
        assert [c.seleccion for c in detalle.cuotas] == [TipoSeleccion.LOCAL]
        assert detalle.deporte.nombre == "Fútbol"

    def test_admin_ve_todas_las_cuotas(self, db):
        evento = crear_evento(db)
        crear_cuota(db, evento, TipoSeleccion.LOCAL)
        apagada = crear_cuota(db, evento, TipoSeleccion.VISITANTE)
        apagada.activa = False
        db.commit()
        assert len(service.obtener_detalle_evento(db, evento.id, solo_cuotas_activas=False).cuotas) == 2

    def test_inexistente_404(self, db):
        error = _error(service.obtener_detalle_evento, db, uuid.uuid4())
        assert (error.status_code, error.detail) == (404, "Evento no encontrado")


class TestCrearEvento:
    def test_crea_un_evento_programado_sin_cuotas(self, db):
        deporte = crear_deporte(db)
        evento = service.crear_evento(db, _evento_in(deporte.id))
        assert evento.id is not None
        assert evento.estado == EstadoEvento.PROGRAMADO and evento.resultado is None
        assert evento.cuotas == [] and evento.deporte.id == deporte.id

    def test_deporte_inexistente_404(self, db):
        error = _error(service.crear_evento, db, _evento_in(999))
        assert (error.status_code, error.detail) == (404, "Deporte no encontrado")

    def test_deporte_inactivo_400(self, db):
        deporte = crear_deporte(db)
        deporte.activo = False
        db.commit()
        error = _error(service.crear_evento, db, _evento_in(deporte.id))
        assert (error.status_code, error.detail) == (400, "El deporte no está activo")

    def test_fecha_pasada_400(self, db):
        deporte = crear_deporte(db)
        error = _error(service.crear_evento, db, _evento_in(deporte.id, inicia_en=_futuro(-1)))
        assert (error.status_code, error.detail) == (400, "La fecha de inicio debe ser futura")


class TestEditarEvento:
    def test_edita_solo_los_campos_enviados(self, db):
        evento = crear_evento(db, equipo_local="Barcelona", equipo_visitante="LDU")
        editado = service.editar_evento(db, evento.id, EventoEditarIn(equipo_local="Emelec"))
        assert (editado.equipo_local, editado.equipo_visitante) == ("Emelec", "LDU")

    def test_cambia_de_deporte_y_fecha(self, db):
        evento = crear_evento(db)
        tenis = crear_deporte(db, "Tenis")
        nueva = _futuro(72)
        editado = service.editar_evento(db, evento.id, EventoEditarIn(deporte_id=tenis.id, inicia_en=nueva))
        assert editado.deporte_id == tenis.id and editado.inicia_en == nueva

    @pytest.mark.parametrize("estado", [EstadoEvento.EN_VIVO, EstadoEvento.FINALIZADO, EstadoEvento.CANCELADO])
    def test_solo_si_esta_programado_400(self, db, estado):
        evento = crear_evento(db, estado=estado)
        error = _error(service.editar_evento, db, evento.id, EventoEditarIn(equipo_local="Emelec"))
        assert (error.status_code, error.detail) == (400, "Solo se puede editar un evento programado")

    def test_inexistente_404(self, db):
        error = _error(service.editar_evento, db, uuid.uuid4(), EventoEditarIn(equipo_local="Emelec"))
        assert error.status_code == 404

    def test_fecha_pasada_400(self, db):
        evento = crear_evento(db)
        error = _error(service.editar_evento, db, evento.id, EventoEditarIn(inicia_en=_futuro(-3)))
        assert (error.status_code, error.detail) == (400, "La fecha de inicio debe ser futura")

    def test_deporte_inexistente_404(self, db):
        evento = crear_evento(db)
        error = _error(service.editar_evento, db, evento.id, EventoEditarIn(deporte_id=999))
        assert (error.status_code, error.detail) == (404, "Deporte no encontrado")

    def test_equipos_iguales_tras_la_edicion_400(self, db):
        evento = crear_evento(db, equipo_local="Barcelona", equipo_visitante="LDU")
        error = _error(service.editar_evento, db, evento.id, EventoEditarIn(equipo_local="ldu"))
        assert (error.status_code, error.detail) == (400, "Los equipos deben ser distintos")

    def test_no_toca_estado_ni_resultado_ni_cuotas(self, db):
        evento = crear_evento(db)
        crear_cuota(db, evento, TipoSeleccion.LOCAL, Decimal("2.00"))
        editado = service.editar_evento(db, evento.id, EventoEditarIn(equipo_local="Emelec"))
        assert editado.estado == EstadoEvento.PROGRAMADO and editado.resultado is None
        assert [c.valor for c in editado.cuotas] == [Decimal("2.00")]


class TestCrearCuotas:
    @staticmethod
    def _cuotas_in(*pares) -> CuotasIn:
        return CuotasIn(cuotas=[{"seleccion": s, "valor": v} for s, v in pares])

    def test_carga_las_cuotas_del_evento(self, db):
        evento = crear_evento(db)
        creadas = service.crear_cuotas(
            db, evento.id, self._cuotas_in(("LOCAL", "2.10"), ("EMPATE", "3.20"), ("VISITANTE", "3.40"))
        )
        assert {c.seleccion: c.valor for c in creadas} == {
            TipoSeleccion.LOCAL: Decimal("2.10"),
            TipoSeleccion.EMPATE: Decimal("3.20"),
            TipoSeleccion.VISITANTE: Decimal("3.40"),
        }
        assert all(c.activa and c.evento_id == evento.id for c in creadas)

    def test_evento_inexistente_404(self, db):
        error = _error(service.crear_cuotas, db, uuid.uuid4(), self._cuotas_in(("LOCAL", "2"), ("VISITANTE", "2")))
        assert (error.status_code, error.detail) == (404, "Evento no encontrado")

    @pytest.mark.parametrize("estado", [EstadoEvento.EN_VIVO, EstadoEvento.FINALIZADO, EstadoEvento.CANCELADO])
    def test_solo_si_esta_programado_400(self, db, estado):
        evento = crear_evento(db, estado=estado)
        error = _error(service.crear_cuotas, db, evento.id, self._cuotas_in(("LOCAL", "2"), ("VISITANTE", "2")))
        assert (error.status_code, error.detail) == (400, "Solo se pueden cargar cuotas a un evento programado")

    def test_seleccion_ya_existente_409_y_no_guarda_nada(self, db):
        evento = crear_evento(db)
        crear_cuota(db, evento, TipoSeleccion.LOCAL)
        error = _error(service.crear_cuotas, db, evento.id, self._cuotas_in(("LOCAL", "2"), ("VISITANTE", "2")))
        assert (error.status_code, error.detail) == (409, "El evento ya tiene cuota para: LOCAL")
        assert [c.seleccion for c in service.obtener_detalle_evento(db, evento.id, False).cuotas] == [
            TipoSeleccion.LOCAL
        ]


class TestEditarCuota:
    def test_cambia_el_valor(self, db):
        cuota = crear_cuota(db, valor=Decimal("2.00"))
        editada = service.editar_cuota(db, cuota.id, CuotaEditarIn(valor=Decimal("2.75")))
        assert editada.valor == Decimal("2.75") and editada.activa is True

    def test_desactiva_la_cuota(self, db):
        cuota = crear_cuota(db)
        assert service.editar_cuota(db, cuota.id, CuotaEditarIn(activa=False)).activa is False

    def test_puede_reactivarla(self, db):
        cuota = crear_cuota(db)
        service.editar_cuota(db, cuota.id, CuotaEditarIn(activa=False))
        assert service.editar_cuota(db, cuota.id, CuotaEditarIn(activa=True)).activa is True

    def test_inexistente_404(self, db):
        error = _error(service.editar_cuota, db, uuid.uuid4(), CuotaEditarIn(activa=False))
        assert (error.status_code, error.detail) == (404, "Cuota no encontrada")

    @pytest.mark.parametrize("estado", [EstadoEvento.EN_VIVO, EstadoEvento.FINALIZADO, EstadoEvento.CANCELADO])
    def test_no_cambia_el_valor_si_el_evento_no_esta_programado_400(self, db, estado):
        cuota = crear_cuota(db, crear_evento(db, estado=estado), valor=Decimal("2.00"))
        error = _error(service.editar_cuota, db, cuota.id, CuotaEditarIn(valor=Decimal("5.00")))
        assert (error.status_code, error.detail) == (400, "Solo se puede cambiar el valor de un evento programado")
        db.refresh(cuota)
        assert cuota.valor == Decimal("2.00")

    def test_activa_si_se_puede_cambiar_en_evento_cerrado(self, db):
        cuota = crear_cuota(db, crear_evento(db, estado=EstadoEvento.FINALIZADO))
        assert service.editar_cuota(db, cuota.id, CuotaEditarIn(activa=False)).activa is False

    def test_no_afecta_otras_cuotas_ni_boletos_ya_emitidos(self, db):
        evento = crear_evento(db)
        local = crear_cuota(db, evento, TipoSeleccion.LOCAL, Decimal("2.00"))
        visitante = crear_cuota(db, evento, TipoSeleccion.VISITANTE, Decimal("3.00"))
        usuario = usuarios_service.crear_usuario(db, "apostador@correo.com", "apostador", "clave-segura-1")
        boleto = crear_boleto(db, usuario)
        seleccion = Seleccion(
            boleto_id=boleto.id, cuota_id=local.id, evento_id=evento.id, cuota_congelada=Decimal("2.00")
        )
        db.add(seleccion)
        db.commit()

        service.editar_cuota(db, local.id, CuotaEditarIn(valor=Decimal("9.99")))
        db.refresh(seleccion)
        db.refresh(visitante)

        assert seleccion.cuota_congelada == Decimal("2.00")
        assert visitante.valor == Decimal("3.00")


class TestContadores:
    def test_cuenta_los_eventos_por_estado_con_ceros(self, db):
        deporte = crear_deporte(db)
        crear_evento(db, deporte)
        crear_evento(db, deporte)
        crear_evento(db, deporte, estado=EstadoEvento.CANCELADO)
        assert service.contar_eventos_por_estado(db) == {
            EstadoEvento.PROGRAMADO: 2,
            EstadoEvento.EN_VIVO: 0,
            EstadoEvento.FINALIZADO: 0,
            EstadoEvento.CANCELADO: 1,
        }

    def test_sin_eventos_todo_es_cero(self, db):
        assert set(service.contar_eventos_por_estado(db).values()) == {0}

    def test_cuenta_solo_los_deportes_activos(self, db):
        crear_deporte(db, "Fútbol")
        inactivo = crear_deporte(db, "Esgrima")
        inactivo.activo = False
        db.commit()
        assert service.contar_deportes(db) == 1
