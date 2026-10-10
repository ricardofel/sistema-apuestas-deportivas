from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from fastapi.templating import Jinja2Templates

HORA_ECUADOR = timezone(timedelta(hours=-5))

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def hora_local(valor: datetime) -> str:
    """Fecha guardada en UTC (sin zona) mostrada en hora de Ecuador."""
    return valor.replace(tzinfo=UTC).astimezone(HORA_ECUADOR).strftime("%d/%m/%Y %H:%M")


templates.env.filters["hora_local"] = hora_local
