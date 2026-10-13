# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Idioma: el usuario trabaja en español. Responder, comentar commits y documentar en español.

## Proyecto

Portal web de apuestas deportivas con **créditos virtuales** (sin dinero real). Proyecto académico de Arquitectura de Software, Ingeniería en Ciencias de la Computación, UTPL 2026 — construido en un día por un equipo de tres, para practicar trabajo en equipo con ramas de Git y elegir una arquitectura ajustada a un plazo corto, no la más sofisticada posible. Contexto completo, README con capturas: [README.md](README.md).

**Estado: terminado y funcional.** Registro/login, billetera, catálogo administrable, apuestas simples y combinadas, y liquidación automática están implementados end-to-end. 567 tests pasan. Esta sección ya no describe trabajo pendiente — si encuentras un `NotImplementedError` o un comentario "por implementar", el código cambió desde que se escribió este archivo: confía en el código, no en este documento.

### Alcance

- **Sí:** registro/login con roles (USUARIO, ADMIN); saldo en créditos que recarga el admin; el admin carga deportes, eventos y cuotas; el usuario arma boletos (simple o combinada, hasta 10 selecciones) y los paga con su saldo; al registrar el resultado de un evento el sistema liquida los boletos automáticamente; cancelar un evento reembolsa o recalcula los boletos afectados; todo movimiento de saldo queda en un libro mayor inmutable.
- **No (decisión deliberada, no omisión):** dinero real o pasarelas de pago, APIs externas de resultados, apuestas en vivo con cuotas dinámicas, mercados distintos al resultado del partido (sin over/under ni hándicap).

## Stack

Python 3.11+, FastAPI 0.115, SQLAlchemy 2.0 (`Mapped[]`), Alembic, Pydantic v2, **SQLite**, Jinja2 + Tailwind CSS + HTMX 2.0 (frontend renderizado por el mismo FastAPI, sin build aparte), JWT (`python-jose`) + `passlib[bcrypt]`, Uvicorn, venv (sin contenedores).

`bcrypt` está fijado en `4.0.1` a propósito: `passlib 1.7.4` falla con versiones más nuevas de `bcrypt`. No actualizarlo sin probar el hash de contraseñas.

## Por qué esta arquitectura

El ejercicio pedía elegir según los requerimientos reales (tres personas, un día), no la solución más elaborada. Tabla de decisiones y alternativas descartadas: [README.md § Decisiones de arquitectura](README.md#decisiones-de-arquitectura). Resumen: monolito modular (no microservicios) porque no había tiempo para orquestación distribuida; SQLite (no Postgres/Docker) porque cada integrante necesitaba correr el proyecto en minutos sin instalar nada; server-rendered Jinja2+HTMX (no SPA) porque evita un segundo build y un segundo despliegue; una sola persona generando las migraciones de Alembic porque tres personas generándolas en paralelo producen un historial bifurcado.

## Arquitectura

**Monolito modular con corte vertical por dominio** (no microservicios). Cada módulo tiene `models.py`, `schemas.py`, `service.py`, `router.py`, y es dueño de su propia tabla.

```
Router (HTTP)  ->  Service (lógica de negocio)  ->  Model (acceso a datos)
```

**Reglas que todo el código sigue:**
- El router **nunca** contiene lógica de negocio: valida con un schema, llama al servicio, devuelve la respuesta.
- Los servicios son funciones Python testeables que reciben `db: Session` y lanzan `HTTPException` directamente (409, 400, 404, 401...). El router JSON no atrapa nada; las rutas HTML (`app/web/`) sí la atrapan para mostrar el error en el formulario, con un `try/except` alrededor de la llamada al servicio.
- **Ningún módulo importa los modelos de otro; se importa el servicio** (ej. `from app.modules.catalogo import service as catalogo_service`). Única excepción: llaves foráneas en la definición de modelos, por string (`ForeignKey("boletos.id")`).
- **Transacciones:** el servicio que cierra una operación de negocio hace `db.commit()`. Las funciones que son una pieza de otra operación (`billetera.debitar`, `billetera.acreditar`, `usuarios.modificar_saldo`, `apuestas.liquidacion.*`) **no hacen commit**, solo `flush()` — el commit lo hace quien las llama, al final de su propia transacción. **No usar `with db.begin()`**: `get_usuario_actual` ya ejecutó una consulta y la sesión tiene una transacción abierta, así que `begin()` falla. Usar `db.commit()` y, ante error, `db.rollback()` explícitos.
- **Rutas protegidas:** `Depends(get_usuario_actual)` (401 si no hay sesión), `Depends(requiere_admin)` (403 si no es admin), o `Depends(get_usuario_opcional)` (devuelve `Usuario | None`, para páginas que cambian según haya o no sesión). El token se lee del header `Authorization: Bearer` o de la cookie `access_token` (`NOMBRE_COOKIE_TOKEN` en `app/core/dependencies.py`) — la misma dependencia sirve para la API y para las pantallas.

**Decisiones tomadas a propósito, que se apartan de un diseño "de libro" para evitar fricción en un equipo de tres trabajando en paralelo el mismo día:**
- `Base` vive en `app/db/base.py` y los imports de **todos** los modelos están centralizados en `app/db/registry.py` (evita un import circular entre módulos). `app/db/session.py` importa `registry` al final del archivo: así cualquier proceso que use `SessionLocal` (servidor, scripts, tests) carga los 7 modelos y las llaves foráneas entre módulos se resuelven. Sin esa importación, SQLAlchemy falla con `NoReferencedTableError` al primer `INSERT` que cruce módulos (ej. una transacción con `boleto_id`).
- Las rutas HTML están repartidas en `app/web/usuarios.py`, `app/web/catalogo.py` (+ `app/web/admin_catalogo.py`) y `app/web/apuestas.py` — una por módulo dueño, en vez de un único `web/router.py` gigante. `app/web/router.py` solo los incluye.
- `Dinero` (`app/db/types.py`) guarda **centavos enteros**, no texto ni flotante (ver más abajo).
- **Los 7 modelos y la única migración los generó una sola persona**, para que el equipo no tuviera que coordinar `alembic revision` en paralelo. Ver [Alembic](#alembic-y-migraciones).

### Estructura

```
app/
  main.py                  crea la app, monta /static y registra los 4 routers de API bajo /api + el router web
  core/
    config.py               Settings (.env): DATABASE_URL, SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
    security.py              hash de contraseñas (bcrypt) y JWT (crear/leer token)
    dependencies.py          get_db, get_usuario_opcional, get_usuario_actual, requiere_admin
  db/
    base.py                  Base declarativa
    registry.py               importa los 7 modelos (para Alembic, para resolver FKs entre módulos)
    session.py                engine + SessionLocal; PRAGMA foreign_keys=ON y journal_mode=WAL
    enums.py                  todos los Enum del dominio (RolUsuario, TipoTransaccion, EstadoEvento, TipoSeleccion, EstadoBoleto, EstadoSeleccion)
    types.py                  Dinero: TypeDecorator, Decimal en Python <-> centavos enteros en SQLite
  modules/
    usuarios/                 Usuario; registro, login, perfil, listado admin
    billetera/                 Transaccion (libro mayor); debitar()/acreditar() atómicos, recarga, historial
    catalogo/                  Deporte, Evento, Cuota; CRUD admin, resultado y cancelación con liquidación
    apuestas/                  Boleto, Seleccion; crear_boleto atómico; liquidacion.py (liquidar/cancelar)
  web/                       pantallas Jinja2 + HTMX (una por módulo dueño, ver arriba); router.py y templating.py (filtro hora_local) compartidos
    templates/
      auth/, billetera/        login, registro, billetera, recarga del admin
      eventos/, admin/          listado y detalle de eventos, panel de administración completo
      boletos/                  mis boletos, detalle, panel de armado del boleto (fragmentos HTMX)
static/
  css/                        input.css (fuente Tailwind) + portal.css (componentes y tokens propios)
  js/tema-tailwind.js          tema compartido entre el CDN de Tailwind (dev) y tailwind.config.js (build)
alembic/versions/            una sola migración: 8cdcfebad85d_esquema_inicial.py (las 7 tablas)
tests/                       30 archivos, 567 tests; factories.py (deporte, evento, cuota, boleto) y conftest.py (fixtures db, client)
scripts/
  seed.py                     carga 16 eventos de ejemplo (equipos ecuatorianos); --reiniciar para recargar
  crear_admin.py               crea un usuario ADMIN; pide la contraseña por teclado (getpass)
docs/
  diagrama-base-de-datos.md    modelo de datos completo, con las decisiones de diseño explicadas
  screenshots/                 capturas usadas en README.md
```

### Rutas principales

API JSON bajo `/api` (documentación interactiva en `/docs`): `POST /auth/registro`, `POST /auth/login`, `GET /usuarios/yo`, `GET /admin/usuarios`, `GET/POST /billetera/*`, `GET /deportes`, `GET/POST /eventos` y `/admin/eventos/*` (crear, editar, cuotas, resultado, cancelar), `POST /boletos`, `GET /boletos/mios`, `GET /boletos/{id}`, `GET /admin/boletos`.

Pantallas HTML (sin prefijo): `/`, `/login`, `/registro`, `/logout`, `/billetera`, `/admin/billetera` (recarga), `/eventos`, `/eventos/{id}`, `/admin`, `/admin/eventos*` (panel completo), `/mis-boletos`, `/boleto/{id}`, y los fragmentos HTMX `/web/saldo` y `/web/boleto/*` (panel de armado del boleto: agregar, quitar, confirmar).

### Contratos entre módulos (ya implementados, firmas estables)

```python
# billetera/service.py — no hacen commit; exigen que boleto_id ya exista en boletos (FK)
def debitar(db, usuario_id, monto: Decimal, boleto_id, descripcion) -> Transaccion
def acreditar(db, usuario_id, monto: Decimal, tipo: TipoTransaccion, boleto_id | None, descripcion) -> Transaccion

# catalogo/service.py
def obtener_cuota_para_apuesta(db, cuota_id) -> Cuota   # 404/400 si no es apostable; usada por apuestas al crear un boleto

# apuestas/liquidacion.py — no hacen commit; idempotentes; las llama catalogo/service.py al registrar resultado o cancelar
def liquidar_evento(db, evento_id) -> dict
def procesar_cancelacion_evento(db, evento_id) -> dict
```

`debitar()` ya es seguro ante peticiones simultáneas y devuelve 400 "Saldo insuficiente" por sí sola (ver `modificar_saldo` abajo). `liquidar_evento` y `procesar_cancelacion_evento` se llaman dentro de la misma transacción que cambia el estado del evento (`catalogo/service.py::registrar_resultado` / `cancelar_evento`): si la liquidación falla, el evento no queda a medio actualizar.

## Reglas del modelo de datos y SQLite (obligatorias)

1. **`PRAGMA foreign_keys=ON` y `journal_mode=WAL`**, activados en un listener `connect` de `app/db/session.py`; `connect_args={"check_same_thread": False, "timeout": 15}`.
2. **Dinero = `Decimal`, nunca `float`.** SQLite no tiene decimal nativo: el `TypeDecorator` `Dinero` (`app/db/types.py`) guarda `Decimal` en Python como **entero en centavos** en la base (no texto: con texto los `CHECK`, el orden y los `SUM` comparan como cadenas y fallan, ej. `'1.00' > '1.0'` da verdadero). **Los `CHECK` se escriben en centavos:** `CheckConstraint("saldo >= 0")`, `CheckConstraint("monto > 0")`, pero `CheckConstraint("valor > 100")` para una cuota mayor a 1.00.
3. **El saldo se modifica solo con `usuarios/service.py::modificar_saldo`**, un único `UPDATE usuarios SET saldo = saldo + :delta WHERE id = :id AND saldo + :delta >= 0 RETURNING saldo`. Atómico ante concurrencia sin necesitar `SELECT ... FOR UPDATE` (que SQLite ignora): si dos peticiones llegan a la vez, la segunda ve el saldo ya descontado por la primera. Portable a PostgreSQL sin cambios. Nunca leer el saldo, calcular en Python y reasignarlo.
4. **Alembic con `render_as_batch=True`** en `alembic/env.py` (SQLite no soporta `ALTER TABLE` completo).
5. **`transacciones` es un libro mayor inmutable:** solo `INSERT`, nunca `UPDATE`/`DELETE`. `monto` lleva signo; la suma de los montos de un usuario siempre debe igualar `usuarios.saldo`; `saldo_posterior` queda grabado para poder auditar.
6. **`selecciones.cuota_congelada`** copia el valor de la cuota en el momento de apostar — el boleto es un contrato, editar la cuota después no lo afecta. **`selecciones.evento_id`** está desnormalizado a propósito (se podría llegar vía `cuota_id`) para permitir el `UNIQUE(boleto_id, evento_id)` y que la liquidación encuentre las selecciones de un evento sin JOIN.
7. Baja lógica en `usuarios.activo` y `deportes.activo` / `cuotas.activa`, nunca borrado físico de filas con historia.

Modelo completo (7 tablas, diagrama ER, restricciones, ejemplo de datos): [docs/diagrama-base-de-datos.md](docs/diagrama-base-de-datos.md).

## Reglas de negocio (implementadas)

- **Crear boleto** (`apuestas/service.py::crear_boleto`), en una sola transacción: valida cada cuota con `catalogo_service.obtener_cuota_para_apuesta` (activa, evento `PROGRAMADO`, no iniciado); rechaza dos selecciones del mismo evento (más el `UNIQUE` de respaldo en la tabla); calcula `cuota_total` (producto de cuotas) y `ganancia_potencial = monto × cuota_total`; inserta el boleto y sus selecciones con `cuota_congelada`; llama a `billetera.debitar()`; `commit()`. Cualquier fallo hace `rollback()` — no quedan filas huérfanas.
- **Liquidar evento** (`apuestas/liquidacion.py::liquidar_evento`): las selecciones `PENDIENTE` de ese evento pasan a `ACERTADA` o `FALLIDA` según `cuota.seleccion == evento.resultado`. Por cada boleto afectado con `liquidado_en IS NULL`: alguna selección viva `FALLIDA` → `PERDIDO` de inmediato (aunque otras piernas sigan sin resolver); todas las vivas `ACERTADA` → `GANADO`, se acredita `ganancia_potencial`; si queda alguna `PENDIENTE`, el boleto no se toca. **Idempotente:** un boleto con `liquidado_en` ya puesto se salta, así que liquidar dos veces no paga el premio dos veces.
- **Cancelar evento** (`apuestas/liquidacion.py::procesar_cancelacion_evento`): las selecciones `PENDIENTE` de ese evento pasan a `ANULADA`. Boleto sin ninguna selección viva → `REEMBOLSADO`, se devuelve `monto`. Boleto con selecciones vivas → se recalculan `cuota_total`/`ganancia_potencial` solo con las que quedan y se le aplica la misma regla de cierre que a la liquidación normal.
- **Códigos HTTP:** email o nombre de usuario duplicado 409; saldo insuficiente / evento ya iniciado o cerrado / selecciones repetidas / cuota inactiva 400; validación Pydantic (contraseña ≥ 8 caracteres, monto fuera de 1.00–500.00, más de 10 selecciones) 422; sin rol admin 403; token inválido/expirado/ausente 401.

## Alembic y migraciones

Una sola migración, `alembic/versions/8cdcfebad85d_esquema_inicial.py`, con las 7 tablas. Si vas a cambiar un modelo: edítalo, corre `alembic revision --autogenerate -m "mensaje"`, revisa el archivo generado (Alembic no siempre acierta con `render_as_batch`) y corre `alembic check` para confirmar que no quedan diferencias. Verifica también que la migración suba y baje limpio (`alembic upgrade head` / `alembic downgrade -1` contra una base descartable) antes de dar el cambio por bueno.

## Git

- Flujo usado: una rama de feature por integrante (`RicardoE`, `ErickR`, `Danielão`), fusionadas a `main` por pull request. El repo no usa `develop`.
- Commits convencionales en español: `feat(módulo): ...`, `fix(módulo): ...`, `test`, `docs`, `refactor`, `chore`.
- Tras cada `git pull`: `pip install -r requirements.txt` y `alembic upgrade head` (cada integrante tiene su propia `apuestas.db` local, nunca versionada).
- **Nunca commitear marcas de conflicto** (`<<<<<<<`, `=======`, `>>>>>>>`). Resolver el conflicto, correr `pytest` y recién entonces commitear el merge.
- `.gitignore` cubre `*.db`, `*.db-wal`, `*.db-shm`, `.env`, `venv/`, `__pycache__/` y `static/css/app.css`.

## Comandos

Activar el entorno virtual (PowerShell): `.\venv\Scripts\Activate.ps1` · (bash) `source venv/bin/activate`

```bash
pip install -r requirements.txt
cp .env.example .env              # copy en PowerShell; variables: DATABASE_URL, SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
alembic upgrade head              # aplicar migraciones
alembic check                     # confirma que modelos y migraciones coinciden
python -m scripts.seed            # 16 eventos de ejemplo (--reiniciar para recargarlos con fechas nuevas)
python -m scripts.crear_admin --email admin@correo.com --nombre admin   # pide la contraseña por teclado
uvicorn app.main:app --reload     # servidor en http://localhost:8000 (docs interactivos en /docs)
pytest                            # las 567 pruebas
pytest tests/test_billetera.py::TestServicio::test_debitar_guarda_el_monto_negativo   # un solo test
```

Los scripts se ejecutan con `python -m scripts.<nombre>` desde la raíz; `python scripts/<nombre>.py` no encuentra el paquete `app`.

Reiniciar la base: borrar `apuestas.db*`, luego `alembic upgrade head` y `python -m scripts.seed`.

**Nota para automatizar `crear_admin`:** usa `getpass.getpass`, que en Windows se cuelga si la entrada viene por un pipe (`echo clave | python -m scripts.crear_admin ...`). Para crear usuarios sin interacción (demos, scripts), usa `app.modules.usuarios.service.crear_usuario(db, email, nombre, password, RolUsuario.ADMIN)` directamente en un script Python en vez de invocar el CLI.

Tailwind: en desarrollo, CDN (`<script src="https://cdn.tailwindcss.com">` en `base.html`). Para producción, compilar y quitar ese `<script>` junto con `static/js/tema-tailwind.js` de `base.html`:
`npx tailwindcss@3.4.17 -i ./static/css/input.css -o ./static/css/app.css --minify`

## Convenciones de frontend

Clases y tokens de diseño documentados en el comentario al inicio de `app/web/templates/base.html` (componentes propios en `static/css/portal.css`: `.hero`, `.ticket`, `.panel`, `.cuota`, badges de estado, etc.). Paleta: neutros con tinte verde, acento verde oscuro (acciones/"ganado"), ámbar pendiente, rojo perdido.

- Cada ruta HTML recibe `usuario: Usuario | None = Depends(get_usuario_opcional)` y lo pasa a la plantilla (la navbar lo necesita en cualquier página). Si la pantalla exige sesión y `usuario` es `None`, redirigir a `/login` (303).
- Las fechas se guardan en UTC sin zona; se muestran con el filtro `{{ valor | hora_local }}` (hora de Ecuador, UTC-5, definido en `app/web/templating.py`).
- El menú marca la sección activa sola, vía la macro `enlace(href, texto)` de `base.html`; también marca subrutas (`/admin` queda activo en `/admin/billetera`).
- HTMX se usa en tres sitios, no más: filtrar eventos por deporte, el panel de armado del boleto (`/web/boleto/*`, agrega/quita selecciones y confirma sin recargar), y el refresco del saldo en la navbar — toda ruta que cambie el saldo debe responder con el header `HX-Trigger: saldo-actualizado` (el span `#saldo-nav` ya escucha ese evento). Para servir solo el fragmento en una petición HTMX, comprobar el header `HX-Request` (ver `app/web/catalogo.py`).

## Pruebas

567 tests en 30 archivos bajo `tests/`. `tests/conftest.py` da las fixtures `db` (SQLite en memoria con llaves foráneas activas, vía `StaticPool`) y `client` (`TestClient` con `get_db` sobreescrito para compartir esa misma sesión). `tests/factories.py` tiene `crear_deporte`, `crear_evento`, `crear_cuota` y `crear_boleto` con valores por defecto razonables — reutilízalas en vez de construir filas a mano. Corre `pytest` antes de cualquier commit.
