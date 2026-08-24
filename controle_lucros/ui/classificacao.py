"""Rótulos e cores compartilhados para as classificações de distribuição
(proporcional / desproporcional / sem distribuição) — usado pelas telas de
dashboard e pelos exportadores de relatório."""
from __future__ import annotations

from .theme import INK_MUTED, SAIU_FG, SEAL_GREEN

LABEL = {
    "proporcional": "Proporcional",
    "desproporcional": "Desproporcional",
    "socio_sem_distribuicao": "Não recebeu",
    "empresa_sem_distribuicao": "Empresa não distribuiu",
}


def cor_classificacao(chave: str) -> str:
    """Função (não dict estático) porque as cores mudam com o tema
    claro/escuro — chamar de novo sempre pega a cor certa pro modo atual."""
    if chave == "proporcional":
        return SEAL_GREEN()
    if chave == "desproporcional":
        return SAIU_FG()
    return INK_MUTED()

CLASSE_PDF = {
    "proporcional": "badge-proporcional",
    "desproporcional": "badge-desproporcional",
    "socio_sem_distribuicao": "badge-neutro",
    "empresa_sem_distribuicao": "badge-neutro",
}
