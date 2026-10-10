from fastapi import APIRouter, Depends, Query, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_usuario_actual, requiere_admin
from app.core.security import crear_token_acceso
from app.modules.usuarios import service
from app.modules.usuarios.models import Usuario
from app.modules.usuarios.schemas import RegistroIn, TokenOut, UsuarioOut

router = APIRouter(tags=["Usuarios"])


@router.post("/auth/registro", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def registro(datos: RegistroIn, db: Session = Depends(get_db)):
    return service.crear_usuario(db, datos.email, datos.nombre_usuario, datos.password)


@router.post("/auth/login", response_model=TokenOut)
def login(formulario: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """El campo `username` del formulario es el email."""
    usuario = service.autenticar(db, formulario.username, formulario.password)
    return TokenOut(access_token=crear_token_acceso(usuario.id))


@router.get("/usuarios/yo", response_model=UsuarioOut)
def perfil(usuario: Usuario = Depends(get_usuario_actual)):
    return usuario


@router.get(
    "/admin/usuarios",
    response_model=list[UsuarioOut],
    dependencies=[Depends(requiere_admin)],
)
def listar_usuarios(
    limite: int = Query(50, ge=1, le=200),
    desplazamiento: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return service.listar_usuarios(db, limite, desplazamiento)
