# Portal de Apuestas Deportivas

Proyecto de Arquitectura de Software, UTPL 2026. Portal web de apuestas con créditos virtuales, hecho con FastAPI, SQLAlchemy 2.0, SQLite, Jinja2, Tailwind y HTMX.

## Puesta en marcha

Windows (PowerShell):

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Linux / macOS:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Editar `.env` y poner una `SECRET_KEY` propia:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

La aplicación corre en http://localhost:8000 y la documentación de la API en http://localhost:8000/docs.

## Datos de ejemplo y administrador

Con las migraciones aplicadas, carga los eventos de ejemplo (equipos ecuatorianos) y crea un administrador. Los scripts se ejecutan desde la raíz del proyecto con `python -m`:

```bash
python -m scripts.seed
python -m scripts.crear_admin --email admin@correo.com --nombre admin
```

`crear_admin` pide la contraseña por teclado. Las fechas del seeder son relativas a hoy; cuando los eventos ya hayan pasado, vuelve a cargarlos con `python -m scripts.seed --reiniciar`.

Flujo para probar: regístrate en `/registro`, entra como administrador, recarga saldo al usuario en `/admin/billetera` y revisa la billetera del usuario en `/billetera`.

## Rutina diaria

```bash
git pull origin develop
pip install -r requirements.txt   # por si alguien añadió dependencias
alembic upgrade head              # obligatorio: cada integrante tiene su propia base SQLite
uvicorn app.main:app --reload
```

## Tests

```bash
pytest
pytest tests/test_base.py::test_check_rechaza_monto_negativo   # un solo test
```

## Base limpia

```bash
rm apuestas.db apuestas.db-wal apuestas.db-shm
alembic upgrade head
python -m scripts.seed
```

## Migraciones

Las migraciones las genera una sola persona (Integrante A) para mantener un historial lineal. Si necesitas cambiar un modelo, avísale; no corras `alembic revision`.

## CSS de producción (Tailwind)

En desarrollo `base.html` usa el CDN de Tailwind. Para la entrega final se compila el CSS purgado y minificado y se enlaza `/static/css/app.css` en `base.html` en lugar del CDN:

```bash
npx tailwindcss@3.4.17 -i ./static/css/input.css -o ./static/css/app.css --minify
```

## Documentación

- [Diagrama de la base de datos](docs/diagrama-base-de-datos.md)
