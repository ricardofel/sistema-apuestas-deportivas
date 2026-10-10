from enum import Enum


class RolUsuario(str, Enum):
    USUARIO = "USUARIO"
    ADMIN = "ADMIN"


class TipoTransaccion(str, Enum):
    RECARGA = "RECARGA"
    APUESTA = "APUESTA"
    PREMIO = "PREMIO"
    REEMBOLSO = "REEMBOLSO"


class EstadoEvento(str, Enum):
    PROGRAMADO = "PROGRAMADO"
    EN_VIVO = "EN_VIVO"
    FINALIZADO = "FINALIZADO"
    CANCELADO = "CANCELADO"


class TipoSeleccion(str, Enum):
    LOCAL = "LOCAL"
    EMPATE = "EMPATE"
    VISITANTE = "VISITANTE"


class EstadoBoleto(str, Enum):
    PENDIENTE = "PENDIENTE"
    GANADO = "GANADO"
    PERDIDO = "PERDIDO"
    REEMBOLSADO = "REEMBOLSADO"


class EstadoSeleccion(str, Enum):
    PENDIENTE = "PENDIENTE"
    ACERTADA = "ACERTADA"
    FALLIDA = "FALLIDA"
    ANULADA = "ANULADA"
