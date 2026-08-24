"""Quem está logado nesta instância do app — um processo, uma pessoa. Usado
pelo repositório pra saber de quem é a ação ao gravar o log de atividade."""
from __future__ import annotations

from .models import Usuario

_usuario_atual: Usuario | None = None


def definir_usuario_atual(usuario: Usuario | None) -> None:
    global _usuario_atual
    _usuario_atual = usuario


def usuario_atual() -> Usuario | None:
    return _usuario_atual
