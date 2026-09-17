"""Relatório de problema: o que o usuário manda quando algo dá errado.

Três situações geram um relatório, e todas terminam no mesmo texto:

1. Um erro inesperado durante o uso (exceção que ninguém tratou).
2. O programa ter fechado sozinho na vez anterior — falha de segmentação e
   fim de processo não passam por exceção nenhuma, então são detectados na
   abertura seguinte, pela marca de sessão (ver `marcar_sessao_aberta`).
3. A pessoa querer relatar um problema por conta própria, sem erro nenhum na
   tela: algo que não bate, um botão que não faz o que devia.

Este módulo não importa Qt de propósito: montar o texto, decidir o assunto e
caber num mailto é lógica que precisa de teste, e testar isso não pode
depender de abrir janela.

Sobre o que NÃO entra aqui: nada de cadastro. O relatório leva versão,
sistema operacional e a pilha do erro — nunca nome de sócio, CPF ou valor.
A pilha do Python não carrega variáveis locais, e a mensagem do erro é
mostrada à pessoa antes de enviar, na tela que este módulo alimenta.
"""
from __future__ import annotations

import datetime as dt
import platform
import sys
import traceback
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

DESTINO = "hnd.lab.dev@gmail.com"

# O mailto: vira linha de comando no Windows, e passa por limites de tamanho
# que variam conforme o programa de e-mail. Acima disso o corpo chega cortado
# ao meio — ou o link simplesmente não abre. Então o que vai pelo mailto é uma
# versão curta, e o texto inteiro fica na tela pra copiar.
LIMITE_CORPO_MAILTO = 1500

ARQUIVO_MARCA = "sessao_aberta.txt"
ARQUIVO_FALHA = "ultima_falha.txt"


@dataclass
class Relatorio:
    """O que a tela mostra e o que vai pro e-mail."""

    assunto: str
    corpo: str
    resumo: str = ""
    anexo_sugerido: str = ""
    contexto: dict = field(default_factory=dict)

    def corpo_para_mailto(self) -> str:
        """O corpo encurtado, com aviso de que foi encurtado.

        Cortar em silêncio seria pior do que não mandar: quem recebe leria um
        relatório que termina no meio de uma linha sem saber que falta coisa."""
        if len(self.corpo) <= LIMITE_CORPO_MAILTO:
            return self.corpo
        cortado = self.corpo[:LIMITE_CORPO_MAILTO].rsplit("\n", 1)[0]
        return (
            f"{cortado}\n\n"
            "[...] A mensagem completa não coube no e-mail automático. "
            "Ela está na tela do programa, no botão \"Copiar mensagem\" — "
            "cole aqui antes de enviar."
        )


def informacoes_do_sistema() -> dict:
    """Só o que ajuda a reproduzir o problema."""
    from . import __version__

    return {
        "Programa": f"Controle de Distribuição de Lucros {__version__}",
        "Sistema": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "Python": platform.python_version(),
        "Empacotado": "sim" if getattr(sys, "frozen", False) else "não (rodando do código)",
    }


def _versao_do_qt() -> str:
    """Lida à parte, e tolerando falha: a versão do Qt é útil pra reproduzir,
    mas um relatório de erro que quebra ao ser montado não serve pra nada."""
    try:
        from PySide6 import __version__ as versao_pyside
        from PySide6.QtCore import qVersion

        return f"PySide6 {versao_pyside} / Qt {qVersion()}"
    except Exception:  # noqa: BLE001 — ver docstring
        return "não identificada"


def texto_da_excecao(erro: BaseException | None) -> str:
    if erro is None:
        return ""
    return "".join(traceback.format_exception(type(erro), erro, erro.__traceback__)).strip()


def montar(
    erro: BaseException | None = None,
    *,
    o_que_fazia: str = "",
    tela: str = "",
    detalhes_extras: str = "",
    origem: str = "erro",
    quando: dt.datetime | None = None,
) -> Relatorio:
    """O relatório pronto, em texto corrido.

    `origem` diz de onde ele veio ("erro", "fechamento" ou "manual") e muda o
    assunto e a primeira linha — quem recebe precisa distinguir de relance um
    programa que fechou sozinho de uma dúvida enviada à mão."""
    quando = quando or dt.datetime.now()
    pilha = texto_da_excecao(erro)

    if origem == "fechamento":
        titulo = "Programa fechou sozinho"
        abertura = (
            "O programa foi encerrado de forma inesperada e este relatório foi "
            "montado na abertura seguinte."
        )
    elif origem == "manual":
        titulo = "Relato de problema"
        abertura = "Relato enviado pelo usuário, sem erro na tela."
    else:
        titulo = f"Erro: {type(erro).__name__}" if erro else "Erro inesperado"
        abertura = "Um erro inesperado apareceu durante o uso."

    linhas = [
        abertura,
        "",
        f"Quando: {quando.strftime('%d/%m/%Y às %H:%M:%S')}",
    ]
    if tela:
        linhas.append(f"Tela: {tela}")

    linhas.append("")
    linhas.append("O que eu estava fazendo:")
    linhas.append(o_que_fazia.strip() or "(não informado)")

    linhas.append("")
    linhas.append("--- informações técnicas ---")
    for chave, valor in informacoes_do_sistema().items():
        linhas.append(f"{chave}: {valor}")
    linhas.append(f"Interface: {_versao_do_qt()}")

    if pilha:
        linhas.append("")
        linhas.append("--- detalhe do erro ---")
        linhas.append(pilha)

    if detalhes_extras.strip():
        linhas.append("")
        linhas.append("--- registro do encerramento ---")
        linhas.append(detalhes_extras.strip())

    resumo = f"{type(erro).__name__}: {erro}" if erro else titulo
    return Relatorio(
        assunto=f"[Controle de Lucros] {titulo}",
        corpo="\n".join(linhas),
        resumo=resumo,
        contexto={"origem": origem, "tela": tela},
    )


def url_mailto(relatorio: Relatorio, destino: str = DESTINO) -> str:
    """O link que abre o programa de e-mail já com tudo preenchido.

    `quote` com safe vazio: assunto e corpo levam acento, quebra de linha e
    "&", e qualquer um deles sem escapar quebra o resto do link — o corpo
    chegaria cortado no primeiro "&" sem ninguém notar."""
    parametros = urllib.parse.urlencode(
        {"subject": relatorio.assunto, "body": relatorio.corpo_para_mailto()},
        quote_via=urllib.parse.quote,
    )
    return f"mailto:{destino}?{parametros}"


def nome_de_arquivo(relatorio: Relatorio, quando: dt.datetime | None = None) -> str:
    quando = quando or dt.datetime.now()
    origem = relatorio.contexto.get("origem", "erro")
    return f"problema_{origem}_{quando.strftime('%Y%m%d_%H%M%S')}.txt"


# ----------------------------------------------------- marca de sessão --
#
# Falha de segmentação e processo morto não levantam exceção: não há o que
# capturar de dentro do programa. O que dá pra saber é depois — se a marca
# de "sessão aberta" continua lá na abertura seguinte, a anterior não
# terminou pelo caminho normal.


def _caminho_marca(pasta: Path) -> Path:
    return Path(pasta) / ARQUIVO_MARCA


def caminho_falha(pasta: Path) -> Path:
    return Path(pasta) / ARQUIVO_FALHA


def marcar_sessao_aberta(pasta: Path, quando: dt.datetime | None = None) -> None:
    quando = quando or dt.datetime.now()
    marca = _caminho_marca(pasta)
    marca.parent.mkdir(parents=True, exist_ok=True)
    marca.write_text(
        f"aberta em {quando.isoformat(timespec='seconds')}\n", encoding="utf-8"
    )


def encerrar_sessao(pasta: Path) -> None:
    """Apaga a marca — o encerramento normal. O que sobrar de marca na
    próxima abertura é fechamento que não passou por aqui."""
    _caminho_marca(pasta).unlink(missing_ok=True)


def sessao_anterior_caiu(pasta: Path) -> bool:
    return _caminho_marca(pasta).exists()


def detalhes_do_fechamento(pasta: Path) -> str:
    """O que sobrou da sessão que caiu: quando abriu e, se o faulthandler
    conseguiu escrever, a pilha de quem estava executando na hora."""
    partes = []
    marca = _caminho_marca(pasta)
    if marca.exists():
        try:
            partes.append(f"Sessão anterior: {marca.read_text(encoding='utf-8').strip()}")
        except OSError:
            pass

    falha = caminho_falha(pasta)
    if falha.exists():
        try:
            conteudo = falha.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            conteudo = ""
        if conteudo:
            # Só o fim interessa: o arquivo acumula as sessões anteriores, e o
            # que explica o fechamento são as últimas linhas.
            partes.append("\n".join(conteudo.splitlines()[-40:]))
    return "\n\n".join(partes)


def limpar_falha(pasta: Path) -> None:
    caminho_falha(pasta).unlink(missing_ok=True)
