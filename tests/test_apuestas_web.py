"""Tests de las pantallas de boletos (Integrante C): /mis-boletos y /boleto/{id}."""
from decimal import Decimal
from uuid import uuid4

from app.db.enums import EstadoBoleto
from app.modules.apuestas import service
from app.modules.billetera import service as billetera_service
from app.modules.catalogo import service as catalogo_service
from tests.apuestas_utils import admin, ana, beto, catalogo_simulado, deporte  # noqa: F401
from tests.apuestas_utils import datos_boleto, headers, nueva_cuota


def _apostar(db, usuario, monto, *cuotas):
    boleto, _ = service.crear_boleto(db, usuario, datos_boleto(monto, *cuotas))
    return boleto


class TestMisBoletos:
    def test_sin_sesion_redirige_al_login(self, client):
        respuesta = client.get("/mis-boletos", follow_redirects=False)
        assert respuesta.status_code == 303
        assert respuesta.headers["location"] == "/login"

    def test_sin_boletos_muestra_mensaje(self, client, ana):
        respuesta = client.get("/mis-boletos", headers=headers(ana))
        assert respuesta.status_code == 200
        assert "Todavía no tienes boletos" in respuesta.text

    def test_lista_vacia_no_depende_de_catalogo(self, client, ana, monkeypatch):
        # En main obtener_cuotas aún no existe: la lista vacía no debe llamarla.
        monkeypatch.delattr(catalogo_service, "obtener_cuotas", raising=False)
        assert client.get("/mis-boletos", headers=headers(ana)).status_code == 200

    def test_muestra_los_propios_con_su_estado(self, client, db, ana, beto, deporte):
        propia = nueva_cuota(db, deporte, "2.00", equipo_local="Barcelona SC", equipo_visitante="Emelec")
        ajena = nueva_cuota(db, deporte, "2.00", equipo_local="Aucas", equipo_visitante="Macará")
        boleto = _apostar(db, ana, "10.00", propia)
        _apostar(db, beto, "5.00", ajena)

        texto = client.get("/mis-boletos", headers=headers(ana)).text

        assert "Barcelona SC vs Emelec" in texto
        assert "Aucas" not in texto
        assert f"/boleto/{boleto.id}" in texto
        assert "bg-amber-100 text-amber-800" in texto  # badge pendiente
        assert "20.00" in texto  # ganancia potencial

    def test_filtra_por_estado(self, client, db, ana, deporte):
        ganado = _apostar(db, ana, "10.00", nueva_cuota(db, deporte, equipo_local="Ganador FC"))
        _apostar(db, ana, "10.00", nueva_cuota(db, deporte, equipo_local="Pendiente FC"))
        ganado.estado = EstadoBoleto.GANADO
        db.commit()

        texto = client.get("/mis-boletos?estado=GANADO", headers=headers(ana)).text

        assert "Ganador FC" in texto
        assert "Pendiente FC" not in texto
        assert "bg-emerald-100 text-emerald-800" in texto

    def test_estado_desconocido_se_ignora(self, client, db, ana, deporte):
        _apostar(db, ana, "10.00", nueva_cuota(db, deporte, equipo_local="Pendiente FC"))
        respuesta = client.get("/mis-boletos?estado=INVENTADO", headers=headers(ana))
        assert respuesta.status_code == 200
        assert "Pendiente FC" in respuesta.text

    def test_pagina_de_diez_en_diez_y_conserva_el_filtro(self, client, db, ana, deporte):
        billetera_service.recargar_saldo(db, ana.id, Decimal("100.00"))
        for i in range(12):
            _apostar(db, ana, "1.00", nueva_cuota(db, deporte, equipo_local=f"Equipo {i:02d}"))

        primera = client.get("/mis-boletos?estado=PENDIENTE", headers=headers(ana)).text
        segunda = client.get("/mis-boletos?pagina=2&estado=PENDIENTE", headers=headers(ana)).text

        assert "Página 1 de 2" in primera
        assert "Equipo 11" in primera and "Equipo 00" not in primera  # más recientes primero
        assert "/mis-boletos?pagina=2&amp;estado=PENDIENTE" in primera
        assert "Equipo 00" in segunda and "Equipo 01" in segunda


class TestDetalle:
    def test_sin_sesion_redirige_al_login(self, client):
        respuesta = client.get(f"/boleto/{uuid4()}", follow_redirects=False)
        assert respuesta.status_code == 303
        assert respuesta.headers["location"] == "/login"

    def test_muestra_selecciones_con_cuota_congelada(self, client, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "1.85", equipo_local="Barcelona SC", equipo_visitante="Emelec")
        c2 = nueva_cuota(db, deporte, "2.10", equipo_local="LDU", equipo_visitante="Independiente")
        boleto = _apostar(db, ana, "10.00", c1, c2)

        respuesta = client.get(f"/boleto/{boleto.id}", headers=headers(ana))

        assert respuesta.status_code == 200
        for texto in ("Barcelona SC vs Emelec", "LDU vs Independiente", "1.85", "2.10", "3.89", "38.90"):
            assert texto in respuesta.text

    def test_boleto_ajeno_da_404(self, client, db, ana, beto, deporte):
        boleto = _apostar(db, ana, "10.00", nueva_cuota(db, deporte))
        respuesta = client.get(f"/boleto/{boleto.id}", headers=headers(beto))
        assert respuesta.status_code == 404
        assert "Boleto no encontrado" in respuesta.text

    def test_boleto_inexistente_da_404(self, client, ana):
        assert client.get(f"/boleto/{uuid4()}", headers=headers(ana)).status_code == 404

    def test_id_mal_escrito_da_404(self, client, ana):
        assert client.get("/boleto/no-es-un-uuid", headers=headers(ana)).status_code == 404

    def test_admin_puede_ver_cualquier_boleto(self, client, db, ana, admin, deporte):
        boleto = _apostar(db, ana, "10.00", nueva_cuota(db, deporte))
        assert client.get(f"/boleto/{boleto.id}", headers=headers(admin)).status_code == 200
