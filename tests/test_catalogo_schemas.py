"""Validaciones de los schemas del catálogo (lo que la API responde con 422)."""
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.enums import TipoSeleccion
from app.modules.catalogo.schemas import (
    CuotaEditarIn,
    CuotaIn,
    CuotasIn,
    DeporteIn,
    EventoEditarIn,
    EventoIn,
)

FECHA = datetime(2030, 1, 1, 20, 0)
ECUADOR = timezone(timedelta(hours=-5))


def _cuota(seleccion, valor="2.00"):
    return {"seleccion": seleccion, "valor": valor}


class TestDeporteIn:
    def test_recorta_espacios(self):
        assert DeporteIn(nombre="  Tenis ").nombre == "Tenis"

    @pytest.mark.parametrize("nombre", ["", "   ", "x" * 51])
    def test_rechaza_nombres_invalidos(self, nombre):
        with pytest.raises(ValidationError):
            DeporteIn(nombre=nombre)


class TestCuotaIn:
    def test_acepta_valor_mayor_a_uno(self):
        assert CuotaIn(seleccion="LOCAL", valor="1.01").valor == Decimal("1.01")

    @pytest.mark.parametrize("valor", ["1", "1.00", "0.50", "-2", "2.123", "10000.00"])
    def test_rechaza_valores_invalidos(self, valor):
        with pytest.raises(ValidationError):
            CuotaIn(seleccion="LOCAL", valor=valor)

    def test_seleccion_es_enum(self):
        assert CuotaIn(seleccion="EMPATE", valor="3.10").seleccion is TipoSeleccion.EMPATE


class TestCuotasIn:
    def test_acepta_local_y_visitante(self):
        datos = CuotasIn(cuotas=[_cuota("LOCAL"), _cuota("VISITANTE")])
        assert len(datos.cuotas) == 2

    def test_acepta_las_tres_selecciones(self):
        datos = CuotasIn(cuotas=[_cuota("LOCAL"), _cuota("EMPATE"), _cuota("VISITANTE")])
        assert len(datos.cuotas) == 3

    def test_rechaza_una_sola_cuota(self):
        with pytest.raises(ValidationError):
            CuotasIn(cuotas=[_cuota("LOCAL")])

    def test_rechaza_selecciones_repetidas(self):
        with pytest.raises(ValidationError, match="repetidas"):
            CuotasIn(cuotas=[_cuota("LOCAL"), _cuota("LOCAL"), _cuota("VISITANTE")])

    def test_exige_local_y_visitante(self):
        with pytest.raises(ValidationError, match="obligatorias"):
            CuotasIn(cuotas=[_cuota("LOCAL"), _cuota("EMPATE")])


class TestCuotaEditarIn:
    def test_exige_al_menos_un_campo(self):
        with pytest.raises(ValidationError):
            CuotaEditarIn()

    def test_acepta_solo_activa(self):
        assert CuotaEditarIn(activa=False).activa is False

    def test_valida_el_valor(self):
        with pytest.raises(ValidationError):
            CuotaEditarIn(valor="1.00")


class TestEventoIn:
    @staticmethod
    def _datos(**cambios):
        datos = {"deporte_id": 1, "equipo_local": "Barcelona", "equipo_visitante": "LDU", "inicia_en": FECHA}
        return {**datos, **cambios}

    def test_rechaza_equipos_iguales_sin_distinguir_mayusculas(self):
        with pytest.raises(ValidationError, match="distintos"):
            EventoIn(**self._datos(equipo_local="LDU", equipo_visitante=" ldu "))

    @pytest.mark.parametrize("campo", ["equipo_local", "equipo_visitante"])
    @pytest.mark.parametrize("valor", ["", "x" * 101])
    def test_rechaza_equipos_vacios_o_largos(self, campo, valor):
        with pytest.raises(ValidationError):
            EventoIn(**self._datos(**{campo: valor}))

    def test_fecha_sin_zona_se_asume_utc(self):
        assert EventoIn(**self._datos()).inicia_en == FECHA

    def test_fecha_con_zona_se_convierte_a_utc_sin_zona(self):
        datos = EventoIn(**self._datos(inicia_en=datetime(2030, 1, 1, 15, 0, tzinfo=ECUADOR)))
        assert datos.inicia_en == FECHA
        assert datos.inicia_en.tzinfo is None

    def test_fecha_utc_explicita_pierde_la_zona(self):
        datos = EventoIn(**self._datos(inicia_en=datetime(2030, 1, 1, 20, 0, tzinfo=UTC)))
        assert datos.inicia_en == FECHA


class TestEventoEditarIn:
    def test_exige_al_menos_un_campo(self):
        with pytest.raises(ValidationError):
            EventoEditarIn()

    def test_acepta_un_solo_campo(self):
        assert EventoEditarIn(equipo_local="Emelec").equipo_local == "Emelec"

    def test_rechaza_equipos_iguales_si_vienen_los_dos(self):
        with pytest.raises(ValidationError, match="distintos"):
            EventoEditarIn(equipo_local="Emelec", equipo_visitante="EMELEC")

    def test_normaliza_la_fecha(self):
        datos = EventoEditarIn(inicia_en=datetime(2030, 1, 1, 15, 0, tzinfo=ECUADOR))
        assert datos.inicia_en == FECHA

    def test_ignora_estado_y_resultado(self):
        datos = EventoEditarIn(equipo_local="Emelec", estado="FINALIZADO", resultado="LOCAL")
        assert "estado" not in datos.model_dump() and "resultado" not in datos.model_dump()
