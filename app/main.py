from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.modules.apuestas.router import router as apuestas_router
from app.modules.billetera.router import router as billetera_router
from app.modules.catalogo.router import router as catalogo_router
from app.modules.usuarios.router import router as usuarios_router
from app.web.router import router as web_router

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="Portal de Apuestas Deportivas")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

for router in (usuarios_router, billetera_router, catalogo_router, apuestas_router):
    app.include_router(router, prefix="/api")

app.include_router(web_router)
