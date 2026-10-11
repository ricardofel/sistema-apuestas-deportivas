"""Tests del panel de boleto con HTMX (Integrante C): /web/boleto/*."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import cookies as http_cookies

from app.db.enums import TipoSeleccion
from app.modules.apuestas.models import Boleto
from tests.apuestas_utils import ana, catalogo_simulado, deporte  # noqa: F401
from tests.apuestas_utils import contar, headers, nueva_cuota
from tests.factories import crear_cuota

COOKIE = "boleto_borrador"


def _borrador(client) -> list[str]:
    """Ids guardados en la cookie, tal como los leería el servidor."""
    # La coma no puede ir suelta en una cookie: se guarda entre comillas como \054.
    for cookie in client.cookies.jar:
        if cookie.name == COOKIE:
            return http_cookies._unquote(cookie.value).split(",")
    return []


def _poner_borrador(client, *valores) -> None:
    """Simula una cookie previa; se usa el mismo dominio que pone el servidor de pruebas."""
    client.cookies.set(COOKIE, ",".join(str(v) for v in valores), domain="testserver.local")


def _agregar(client, usuario, cuota):
    return client.post(f"/web/boleto/agregar/{cuota.id}", headers=headers(usuario))


class TestPanel:
    def test_sin_sesion_invita_a_iniciar_sesion(self, client):
        respuesta = client.get("/web/boleto/panel")
        assert respuesta.status_code == 200
        assert "Inicia sesión para apostar" in respuesta.text
        assert 'href="/login"' in respuesta.text

    def test_devuelve_solo_el_fragmento(self, client, ana):
        texto = client.get("/web/boleto/panel", headers=headers(ana)).text
        assert "<html" not in texto
        assert "Elige una cuota" in texto

    def test_descarta_en_silencio_las_cuotas_no_apostables(self, client, db, ana, deporte):
        viva = nueva_cuota(db, deporte, equipo_local="Vivo FC")
        inactiva = nueva_cuota(db, deporte, equipo_local="Inactivo FC")
        inactiva.activa = False
        db.commit()
        _poner_borrador(client, viva.id, inactiva.id, "basura")

        respuesta = client.get("/web/boleto/panel", headers=headers(ana))

        assert "Vivo FC" in respuesta.text
        assert "Inactivo FC" not in respuesta.text
        assert _borrador(client) == [str(viva.id)]  # la cookie queda limpia

    def test_calcula_la_ganancia_en_el_servidor(self, client, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, "1.85")
        c2 = nueva_cuota(db, deporte, "2.10")
        _poner_borrador(client, c1.id, c2.id)

        texto = client.get("/web/boleto/panel?monto=10", headers=headers(ana)).text

        assert "3.89" in texto  # cuota total
        assert "38.90" in texto  # ganancia potencial

    def test_monto_invalido_no_muestra_ganancia(self, client, db, ana, deporte):
        _poner_borrador(client, nueva_cuota(db, deporte, "2.00").id)
        texto = client.get("/web/boleto/panel?monto=0.50", headers=headers(ana)).text
        assert "—" in texto


class TestAgregarYQuitar:
    def test_agrega_una_seleccion(self, client, db, ana, deporte):
        cuota = nueva_cuota(db, deporte, "2.00", equipo_local="Barcelona SC", equipo_visitante="Emelec")

        respuesta = _agregar(client, ana, cuota)

        assert respuesta.status_code == 200
        assert "Barcelona SC vs Emelec" in respuesta.text
        assert f'hx-post="/web/boleto/quitar/{cuota.id}"' in respuesta.text
        assert _borrador(client) == [str(cuota.id)]

    def test_combinada_muestra_la_cuota_total(self, client, db, ana, deporte):
        _agregar(client, ana, nueva_cuota(db, deporte, "2.00"))
        respuesta = _agregar(client, ana, nueva_cuota(db, deporte, "1.50"))
        assert len(_borrador(client)) == 2
        assert "3.00" in respuesta.text

    def test_mismo_evento_reemplaza_la_seleccion(self, client, db, ana, deporte):
        local = nueva_cuota(db, deporte, "2.00", TipoSeleccion.LOCAL)
        visitante = crear_cuota(db, evento=local.evento, seleccion=TipoSeleccion.VISITANTE, valor=Decimal("3.50"))
        _agregar(client, ana, local)

        respuesta = _agregar(client, ana, visitante)

        assert _borrador(client) == [str(visitante.id)]
        assert "Visitante" in respuesta.text and "3.50" in respuesta.text

    def test_maximo_diez_selecciones(self, client, db, ana, deporte):
        for _ in range(10):
            _agregar(client, ana, nueva_cuota(db, deporte, "1.10"))

        respuesta = _agregar(client, ana, nueva_cuota(db, deporte, "1.10"))

        assert respuesta.status_code == 200  # HTMX solo inserta respuestas 2xx
        assert "Máximo 10 selecciones por boleto" in respuesta.text
        assert len(_borrador(client)) == 10

    def test_cuota_no_apostable_muestra_el_error(self, client, db, ana, deporte):
        ayer = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        respuesta = _agregar(client, ana, nueva_cuota(db, deporte, inicia_en=ayer))
        assert respuesta.status_code == 200
        assert "El evento ya inició" in respuesta.text
        assert _borrador(client) == []

    def test_quitar_una_seleccion(self, client, db, ana, deporte):
        c1 = nueva_cuota(db, deporte, equipo_local="Queda FC")
        c2 = nueva_cuota(db, deporte, equipo_local="Sale FC")
        _agregar(client, ana, c1)
        _agregar(client, ana, c2)

        respuesta = client.post(f"/web/boleto/quitar/{c2.id}", headers=headers(ana))

        assert "Queda FC" in respuesta.text and "Sale FC" not in respuesta.text
        assert _borrador(client) == [str(c1.id)]

    def test_sin_sesion_no_agrega(self, client, db, deporte):
        respuesta = client.post(f"/web/boleto/agregar/{nueva_cuota(db, deporte).id}")
        assert "Inicia sesión para apostar" in respuesta.text
        assert _borrador(client) == []


class TestConfirmar:
    def _confirmar(self, client, usuario, monto):
        return client.post("/web/boleto/confirmar", data={"monto": monto}, headers=headers(usuario))

    def test_crea_el_boleto_y_avisa_a_la_navbar(self, client, db, ana, deporte):
        _agregar(client, ana, nueva_cuota(db, deporte, "2.00"))

        respuesta = self._confirmar(client, ana, "10.00")

        assert respuesta.status_code == 200
        assert respuesta.headers["HX-Trigger"] == "saldo-actualizado"
        boleto = db.query(Boleto).one()
        assert boleto.ganancia_potencial == Decimal("20.00")
        assert f'href="/boleto/{boleto.id}"' in respuesta.text
        assert "90.00" in respuesta.text  # saldo restante
        assert _borrador(client) == []  # el borrador se vacía
        db.refresh(ana)
        assert ana.saldo == Decimal("90.00")

    def test_saldo_insuficiente_conserva_el_borrador(self, client, db, ana, deporte):
        cuota = nueva_cuota(db, deporte, "2.00")
        _agregar(client, ana, cuota)

        respuesta = self._confirmar(client, ana, "150.00")

        assert respuesta.status_code == 200
        assert "Saldo insuficiente" in respuesta.text
        assert 'value="150.00"' in respuesta.text  # el monto escrito se conserva
        assert "HX-Trigger" not in respuesta.headers
        assert _borrador(client) == [str(cuota.id)]
        assert contar(db, Boleto) == 0

    def test_monto_fuera_de_rango(self, client, db, ana, deporte):
        _agregar(client, ana, nueva_cuota(db, deporte))
        respuesta = self._confirmar(client, ana, "0.99")
        assert "El monto debe estar entre 1.00 y 500.00" in respuesta.text
        assert contar(db, Boleto) == 0

    def test_borrador_vacio(self, client, ana):
        respuesta = self._confirmar(client, ana, "10.00")
        assert "Agrega al menos una selección" in respuesta.text

    def test_cuota_que_dejo_de_ser_apostable_explica_el_motivo(self, client, db, ana, deporte):
        cuota = nueva_cuota(db, deporte)
        _agregar(client, ana, cuota)
        cuota.evento.inicia_en = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        db.commit()

        respuesta = self._confirmar(client, ana, "10.00")

        assert "El evento ya inició" in respuesta.text
        assert contar(db, Boleto) == 0

    def test_sin_sesion_no_confirma(self, client, db, deporte):
        _poner_borrador(client, nueva_cuota(db, deporte).id)
        respuesta = client.post("/web/boleto/confirmar", data={"monto": "10.00"})
        assert "Inicia sesión para apostar" in respuesta.text
        assert contar(db, Boleto) == 0
