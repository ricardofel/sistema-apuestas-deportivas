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
```

## CSS de producción (Tailwind)

En desarrollo `base.html` usa el CDN de Tailwind. Para la entrega final se compila el CSS purgado y minificado y se enlaza `/static/css/app.css` en `base.html` en lugar del CDN:

```bash
npx tailwindcss@3.4.17 -i ./static/css/input.css -o ./static/css/app.css --minify
```

## Documentación

- [Diagrama de la base de datos](docs/diagrama-base-de-datos.md)
