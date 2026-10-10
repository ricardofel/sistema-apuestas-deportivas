# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Idioma: el usuario trabaja en español. Responder, comentar commits y documentar en español.

## Proyecto

Portal web de apuestas deportivas con **créditos virtuales** (sin dinero real). Proyecto académico de Arquitectura de Software, UTPL 2026, desarrollado por un equipo de **tres integrantes (A, B, C)**. Diagrama de la base de datos en [docs/diagrama-base-de-datos.md](docs/diagrama-base-de-datos.md).

**Estado actual:**
- **Hecho (Integrante A):** usuarios y autenticación (registro, login, JWT en header o cookie), billetera (libro mayor, `debitar`/`acreditar`, recarga del admin), pantallas de login, registro, billetera y recarga, menú con sección activa y hora de Ecuador.
- **Hecho (base compartida):** los **7 modelos** de las tres áreas, la **migración inicial** (`alembic/versions/8cdcfebad85d_esquema_inicial.py`), `scripts/seed.py` con eventos ecuatorianos y un listado público de eventos (`/eventos`).
- **Pendiente de B:** CRUD de catálogo para el admin, `obtener_cuota_para_apuesta`, resultado y cancelación de eventos, detalle del evento y panel de administración.
- **Pendiente de C:** `crear_boleto`, `liquidar_evento`, reembolsos y las pantallas de boletos.

Los archivos `[COMPARTIDO]` están completos: **no modificarlos sin avisar al equipo**, para evitar conflictos de merge.

### Alcance

- **Sí:** registro/login con roles (USUARIO, ADMIN); saldo en créditos que recarga el admin; el admin carga deportes, eventos y cuotas; el usuario arma boletos (simple o combinada) y los paga con su saldo; al registrar el resultado de un evento el sistema liquida los boletos automáticamente; todo movimiento de saldo queda en un libro mayor.
- **No (decisión deliberada):** dinero real o pasarelas de pago, APIs externas de resultados, apuestas en vivo con cuotas dinámicas, mercados distintos al resultado del partido (sin over/under ni hándicap).

## Stack

Python 3.11+, FastAPI, SQLAlchemy 2.0 (`Mapped[]`), Alembic, Pydantic v2, **SQLite**, Jinja2 + Tailwind CSS + HTMX (frontend renderizado por el mismo FastAPI), JWT (`python-jose`) + `passlib[bcrypt]`, Uvicorn, venv (sin contenedores).

`bcrypt` está fijado en `4.0.1` a propósito: `passlib 1.7.4` falla con versiones más nuevas de `bcrypt`. No actualizarlo sin probar el hash de contraseñas.

## Arquitectura

**Monolito modular con corte vertical por dominio** (no microservicios, a propósito). Cada módulo tiene `models.py`, `schemas.py`, `service.py`, `router.py`.

```
Router (HTTP)  ->  Service (lógica de negocio)  ->  Model (acceso a datos)
```

**Reglas:**
- El router **nunca** contiene lógica de negocio: valida con un schema, llama al servicio, devuelve la respuesta.
- Los servicios son funciones Python testeables que reciben `db: Session`.
- **Ningún módulo importa los modelos de otro; se importa el servicio.** Única excepción: llaves foráneas en la definición de modelos (por string, ej. `ForeignKey("boletos.id")`).
- **Los servicios lanzan `HTTPException`** directamente (409, 400, 404, 401...). El router no atrapa nada; las rutas HTML (`web/`) sí la atrapan para mostrar el error en el formulario.
- **Transacciones:** el servicio que cierra una operación hace `db.commit()`. Los que son piezas de otra operación (`debitar`, `acreditar`, `modificar_saldo`) **no hacen commit**: solo `flush`, y el commit lo hace quien llama. **No usar `with db.begin()`**: `get_usuario_actual` ya hizo una consulta y la sesión tiene una transacción abierta, así que `begin()` falla. Usar `db.commit()` / `db.rollback()` explícitos.
- **Rutas protegidas:** `Depends(get_usuario_actual)` (401 si no hay sesión) o `Depends(requiere_admin)` (403). El token se lee del header `Authorization: Bearer` o de la cookie `access_token`, así sirve para la API y para las pantallas.

**Desviaciones respecto al documento de arquitectura original (hechas a propósito para evitar conflictos de Git):**
- `Base` vive en `db/base.py` y los imports de todos los modelos en `db/registry.py` (evita un import circular). `db/session.py` importa `registry`: así cualquier proceso que use la base (servidor, scripts) carga los 7 modelos y se resuelven las llaves foráneas entre módulos. Sin eso falla con `NoReferencedTableError`.
- Las rutas HTML están en `web/usuarios.py`, `web/catalogo.py` y `web/apuestas.py` (una por dueño) en vez de un único `web/router.py` compartido. `web/router.py` ya los incluye.
- `Dinero` guarda **centavos enteros**, no texto (ver reglas del modelo de datos).
- **Los modelos de B y C y todas las migraciones los hizo A**, para que nadie tenga que generar migraciones en paralelo. Si B o C necesitan cambiar un modelo, se lo piden a A.

Estructura:

```
app/
  main.py                # [COMPARTIDO] crea la app y registra los 4 routers bajo /api
  core/                  # config.py [COMPARTIDO]; security.py (hash bcrypt, JWT); dependencies.py (get_db, get_usuario_opcional, get_usuario_actual, requiere_admin)
  db/                    # [COMPARTIDO] base.py (Base), registry.py (importa todos los modelos), session.py, enums.py, types.py
  modules/
    usuarios/            # A
    billetera/           # A  (modelo Transaccion)
    catalogo/            # B  (Deporte, Evento, Cuota; modelos listos, servicio con listar_eventos y listar_deportes)
    apuestas/            # C  (Boleto, Seleccion; modelos listos; liquidacion.py por implementar)
  web/                   # [COMPARTIDO] router.py y templating.py (filtro hora_local); base.html [COMPARTIDO]
    usuarios.py          # A: rutas HTML de auth, billetera, recarga del admin y fragmento de saldo
    catalogo.py          # B: rutas HTML de eventos y admin (ya tiene /eventos)
    apuestas.py          # C: rutas HTML de boletos
    templates/           # auth, billetera -> A; eventos, admin -> B; boletos -> C
static/css/              # input.css; app.css generado (en .gitignore)
alembic/versions/        # migración inicial con las 7 tablas
tests/                   # factories.py (deporte, evento, cuota, boleto) para reutilizar en los tests
scripts/                 # seed.py (eventos ecuatorianos), crear_admin.py; se ejecutan con python -m scripts.<nombre>
```

### Contratos entre módulos

```python
# billetera/service.py  (implementado por A, consume C)
def debitar(db, usuario_id, monto: Decimal, boleto_id, descripcion) -> Transaccion
def acreditar(db, usuario_id, monto: Decimal, tipo: TipoTransaccion, boleto_id | None, descripcion) -> Transaccion
# catalogo/service.py  (B, consume C) - por implementar
def obtener_cuota_para_apuesta(db, cuota_id) -> Cuota
# apuestas/liquidacion.py  (C, consume B) - por implementar
def liquidar_evento(db, evento_id) -> dict
```

`debitar` ya es seguro ante concurrencia y devuelve 400 "Saldo insuficiente" por sí solo; C puede validar el saldo antes para dar un error más amable, pero no lo necesita. Ambas funciones exigen un `boleto_id` que exista en `boletos` (llave foránea), así que C debe insertar el boleto (`flush`) antes de llamarlas.

## Reglas del modelo de datos y SQLite (obligatorias)

1. **Activar `PRAGMA foreign_keys=ON` y `journal_mode=WAL`** en un listener `connect` de `app/db/session.py`; `connect_args={"check_same_thread": False, "timeout": 15}`. Sin esto las FK no se validan.
2. **Dinero = `Decimal`, nunca `float`.** SQLite no tiene decimal: usar el `TypeDecorator` `Dinero` (`app/db/types.py`) en `saldo`, `monto`, `cuota_total`, `ganancia_potencial`, `saldo_posterior`, `valor`, `cuota_congelada`. En Python es `Decimal`; en la base son **centavos enteros** (INTEGER). Se eligió así en vez de texto porque con texto los `CHECK`, el orden y los `SUM` comparan como cadenas y fallan (ej. `'1.00' > '1.0'` es verdadero). **Los `CHECK` se escriben en centavos:** `CheckConstraint("saldo >= 0")`, `CheckConstraint("monto > 0")`, pero `CheckConstraint("valor > 100")` para cuotas mayores a 1.00.
3. **El saldo se modifica solo con `usuarios.service.modificar_saldo`**, un único `UPDATE ... WHERE saldo + delta >= 0 RETURNING saldo`. Es atómico: dos peticiones simultáneas no pueden gastar el mismo saldo, ni en SQLite (que ignora `with_for_update()` y no abre transacción al leer) ni en PostgreSQL. No leer el saldo, calcular en Python y reasignarlo.
4. **Alembic con `render_as_batch=True`** en `alembic/env.py` y `op.batch_alter_table()` en las migraciones (SQLite no soporta `ALTER TABLE` completo).
5. **Libro mayor `transacciones` inmutable:** solo `INSERT`. `monto` lleva signo; la suma de montos de un usuario debe igualar `usuarios.saldo`; `saldo_posterior` sirve para auditar.
6. **`selecciones.cuota_congelada`** copia el valor de la cuota al apostar (el boleto es un contrato). `selecciones.evento_id` está desnormalizado a propósito para el `UNIQUE (boleto_id, evento_id)`.
7. Baja lógica en usuarios (`activo`), no borrado físico.

## Reglas de negocio clave

- **Crear boleto** (`apuestas/service.py`), todo en **una sola transacción**: bloquear usuario → validar activo, monto 1.00–500.00, 1–10 selecciones, sin eventos repetidos, cada cuota activa y evento `PROGRAMADO` con `inicia_en > ahora` → validar saldo → `cuota_total` = producto de cuotas, `ganancia_potencial` = monto × cuota_total → insertar boleto y selecciones con `cuota_congelada` → `billetera.debitar()` → commit.
- **Liquidar evento** (`apuestas/liquidacion.py`): selecciones PENDIENTES del evento → ACERTADA si `cuota.seleccion == evento.resultado`, si no FALLIDA. Boleto con alguna FALLIDA → PERDIDO; todas ACERTADAS → GANADO y acredita `ganancia_potencial`; alguna aún PENDIENTE → no tocar. **Idempotente:** si `boleto.liquidado_en` ya tiene fecha, se salta (no paga dos veces).
- **Cancelar evento:** evento CANCELADO, sus selecciones PENDIENTES → ANULADA. Simplificación aceptable si el plazo aprieta: reembolsar el boleto completo y documentarlo.
- **Códigos HTTP:** email duplicado 409; saldo insuficiente / evento iniciado / eventos repetidos 400; validación Pydantic 422 (contraseña ≥ 8 caracteres, monto fuera de rango); sin rol admin 403 (`requiere_admin`); token inválido/expirado 401 (`get_usuario_actual`).

## División del trabajo (A / B / C)

| Integrante | Módulos | Entregable que desbloquea a los demás |
|---|---|---|
| **A** – Identidad y billetera | `usuarios`, `billetera`, `core/security.py`, `templates/auth` y `billetera`, `test_usuarios.py` | Dependencias `get_usuario_actual` / `requiere_admin` (primeros días) |
| **B** – Catálogo | `catalogo`, `templates/eventos` y `admin`, `scripts/seed.py`, `test_catalogo.py` | `seed.py` con ≥ 10 eventos y sus cuotas |
| **C** – Apuestas | `apuestas` (incl. `liquidacion.py`), `templates/boletos`, `test_apuestas.py` | — (es el que más lógica de negocio concentra) |

**Ricardo es el Integrante A** y trabaja con Claude en esa parte (ver Estado actual).

Fases: 0) commit inicial conjunto (estructura, `db/*`, `main.py`, `alembic/env.py`, `base.html`, firmas de contratos) → 1) modelos y cimientos → 2) lógica de negocio → 3) interfaz → 4) integración, build de Tailwind y README.

Archivos **[COMPARTIDOS]** (zona de conflictos): `main.py`, `config.py`, `db/base.py`, `db/enums.py`, `db/types.py`, `web/router.py`, `base.html`, `requirements.txt`. Se escriben completos en la Fase 0.

## Git

- Ramas: `main` (estable) ← `develop` ← `feat/usuarios-auth`, `feat/catalogo-eventos`, `feat/apuestas-boletos`. Sin commits directos a `main` ni `develop`; todo por pull request.
- Commits convencionales en español: `feat(usuarios): ...`, `fix(apuestas): ...`, `test`, `docs`, `refactor`, `chore`.
- **Migraciones de Alembic: las genera solo A** (evita historial bifurcado por `down_revision`). B y C no corren `alembic revision`; si necesitan cambiar un modelo, se lo piden a A.
- Tras cada `git pull`: `pip install -r requirements.txt` y `alembic upgrade head` (cada integrante tiene su propia `apuestas.db`).
- **Nunca commitear marcas de conflicto** (`<<<<<<<`, `=======`, `>>>>>>>`): ya pasó una vez y dejó la app sin arrancar. Resolver el conflicto, correr `pytest` y recién entonces commitear el merge.
- `.gitignore` ya cubre `*.db`, `*.db-wal`, `*.db-shm`, `.env`, `venv/`, `__pycache__/` y `static/css/app.css`. Nunca versionar la base SQLite.

## Comandos

Activar el entorno virtual (PowerShell): `.\venv\Scripts\Activate.ps1`

```bash
pip install -r requirements.txt
cp .env.example .env              # copy en PowerShell; variables: DATABASE_URL, SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
alembic upgrade head              # aplicar migraciones
alembic revision --autogenerate -m "mensaje"   # solo A
alembic check                     # verifica que los modelos y las migraciones coinciden
python -m scripts.seed            # eventos ecuatorianos de ejemplo (--reiniciar para recargarlos con fechas nuevas)
python -m scripts.crear_admin --email admin@correo.com --nombre admin   # pide la contraseña por teclado
uvicorn app.main:app --reload     # API en http://localhost:8000 (docs en /docs)
pytest                            # todos los tests
pytest tests/test_usuarios.py::test_nombre   # un solo test
```

Los scripts se ejecutan con `python -m scripts.<nombre>` desde la raíz; `python scripts/<nombre>.py` no encuentra el paquete `app`.

Reiniciar la base: borrar `apuestas.db*`, luego `alembic upgrade head` y `python -m scripts.seed`.

Tailwind: en desarrollo CDN (`<script src="https://cdn.tailwindcss.com"></script>`); para entrega compilar con minificado:
`npx tailwindcss -i ./static/css/input.css -o ./static/css/app.css --minify`

## Convenciones de frontend

Clases Tailwind acordadas (se fijan en `base.html`): contenedor `max-w-5xl mx-auto px-4 py-8`; tarjeta `bg-white rounded-xl shadow-sm border border-slate-200 p-6`; botón primario `bg-emerald-600 hover:bg-emerald-700 text-white font-medium px-4 py-2 rounded-lg transition`. Paleta: `slate` base, `emerald` acciones/positivo, `amber` pendiente, `rose` negativo. HTMX solo para: agregar selección al boleto, refrescar saldo en la navbar, filtrar eventos por deporte; el servidor devuelve fragmentos HTML, no JSON.

Reglas para las pantallas nuevas:
- Cada ruta HTML recibe `usuario: Usuario | None = Depends(get_usuario_opcional)` y lo pasa a la plantilla (la navbar lo necesita). Si la pantalla exige sesión y `usuario` es `None`, redirigir a `/login` (303).
- Las fechas se guardan en UTC y se muestran con el filtro `{{ valor | hora_local }}` (hora de Ecuador, UTC-5).
- El menú marca la sección activa solo: basta un `{{ enlace("/ruta", "Texto") }}` en `base.html`; también marca las subrutas (`/admin` queda activo en `/admin/billetera`).
- Después de apostar, C debe responder con el header `HX-Trigger: saldo-actualizado` para que la navbar refresque el saldo (el span `#saldo-nav` ya escucha ese evento).
- Para un fragmento HTMX, devolver solo el parcial cuando el request trae `HX-Request` (ver `web/catalogo.py`).

## Decisiones pendientes

- Nombres reales de los integrantes A, B, C.
- Fecha de entrega (ajusta las fases).
- Si el panel de administración se queda en B o pasa a C para equilibrar carga.
