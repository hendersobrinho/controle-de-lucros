"""Atualização automática: vê no GitHub se há uma release mais nova que a
instalada, baixa o instalador dela e o executa.

Quem publica só precisa criar a release no GitHub com o instalador anexo
(ControleDeLucros_Setup_<versão>.exe, o que o Inno Setup gera). O programa
instalado pergunta ao abrir; se houver versão nova, mostra as notas da
release e, com o "sim" da pessoa, baixa, confere e roda o instalador — que
fecha o programa, troca os arquivos e abre de novo. O banco não é tocado
pelo instalador (ver controle_lucros.iss).

Sem Qt aqui: a tela (ui/atualizacao.py) chama estas funções numa thread.

Segurança: só fala com o repositório e os endereços do GitHub, só aceita um
instalador com o nome esperado e, quando a release traz o sha256 do arquivo
(o GitHub calcula), o download tem que bater com ele."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from . import __version__

REPOSITORIO = "hendersobrinho/controle-de-lucros"
URL_ULTIMA_RELEASE = f"https://api.github.com/repos/{REPOSITORIO}/releases/latest"
URL_RELEASES = f"https://github.com/{REPOSITORIO}/releases"

_NOME_DO_INSTALADOR = re.compile(r"^ControleDeLucros_Setup_(\d+(?:\.\d+){1,3})\.exe$")
_HOSTS_DO_GITHUB = ("github.com", "githubusercontent.com")
ESPERA_S = 8
# Parâmetros do Inno Setup: janela de progresso (a pessoa vê que está
# atualizando), sem perguntas e sem reiniciar o Windows.
PARAMETROS_DO_INSTALADOR = "/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS"


class ErroDeAtualizacao(Exception):
    """Algo impediu de verificar ou baixar — a mensagem serve para mostrar."""


@dataclass(frozen=True)
class Atualizacao:
    versao: str
    notas: str
    url: str
    nome: str
    tamanho: int
    sha256: str | None


def versao_como_tupla(texto: str) -> tuple[int, ...]:
    """"v2.1.0" -> (2, 1, 0). ValueError se não for uma versão numérica."""
    partes = str(texto).strip().lstrip("vV").split(".")
    if not partes or not all(p.isdigit() for p in partes):
        raise ValueError(f"Versão inválida: {texto!r}")
    return tuple(int(p) for p in partes)


def _host_do_github(url: str) -> bool:
    partes = urlparse(url)
    host = (partes.hostname or "").lower()
    return partes.scheme == "https" and any(host == h or host.endswith("." + h) for h in _HOSTS_DO_GITHUB)


def _abrir(url: str, espera: float, aceita: str = "application/vnd.github+json"):
    pedido = urllib.request.Request(url, headers={"User-Agent": f"ControleDeLucros/{__version__}", "Accept": aceita})
    try:
        resposta = urllib.request.urlopen(pedido, timeout=espera)  # noqa: S310 - https do GitHub, conferido acima
    except (urllib.error.URLError, OSError, TimeoutError) as erro:
        raise ErroDeAtualizacao(f"Não consegui falar com o GitHub ({erro}).") from erro
    if not _host_do_github(resposta.geturl()):
        resposta.close()
        raise ErroDeAtualizacao("O endereço de download não é do GitHub.")
    return resposta


def interpretar_release(dados: dict, versao_instalada: str = __version__) -> Atualizacao | None:
    """A atualização que a release representa, ou None se a instalada já é
    igual ou mais nova, ou se a release não traz um instalador utilizável."""
    try:
        nova = versao_como_tupla(dados.get("tag_name", ""))
        atual = versao_como_tupla(versao_instalada)
    except ValueError:
        return None
    if dados.get("draft") or dados.get("prerelease") or nova <= atual:
        return None
    for anexo in dados.get("assets") or []:
        nome = anexo.get("name", "")
        casou = _NOME_DO_INSTALADOR.match(nome)
        url = anexo.get("browser_download_url", "")
        if not casou or not _host_do_github(url):
            continue
        digest = str(anexo.get("digest") or "")
        sha = digest.split(":", 1)[1].lower() if digest.lower().startswith("sha256:") else None
        return Atualizacao(
            versao=".".join(str(n) for n in nova),
            notas=str(dados.get("body") or "").strip(),
            url=url,
            nome=nome,
            tamanho=int(anexo.get("size") or 0),
            sha256=sha,
        )
    return None


def procurar(versao_instalada: str = __version__, espera: float = ESPERA_S) -> Atualizacao | None:
    """Pergunta ao GitHub pela última release. None = já está atualizado.
    ErroDeAtualizacao = não deu para saber (sem internet, GitHub fora)."""
    with _abrir(URL_ULTIMA_RELEASE, espera) as resposta:
        try:
            dados = json.load(resposta)
        except ValueError as erro:
            raise ErroDeAtualizacao("A resposta do GitHub veio ilegível.") from erro
    return interpretar_release(dados, versao_instalada)


def pasta_de_downloads() -> Path:
    return Path(tempfile.gettempdir()) / "ControleDeLucros_Atualizacao"


def baixar(atualizacao: Atualizacao, progresso=None, cancelado=None) -> Path:
    """Baixa o instalador para uma pasta temporária e confere o arquivo.
    progresso(baixado, total) é opcional; cancelado() -> bool interrompe.
    Devolve o caminho do instalador pronto para executar."""
    pasta = pasta_de_downloads()
    shutil.rmtree(pasta, ignore_errors=True)  # instaladores de versões anteriores
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / atualizacao.nome
    parcial = destino.with_suffix(".parte")
    soma = hashlib.sha256()
    baixado = 0
    try:
        with _abrir(atualizacao.url, ESPERA_S * 4, "application/octet-stream") as resposta, \
                open(parcial, "wb") as saida:
            total = atualizacao.tamanho or int(resposta.headers.get("Content-Length") or 0)
            while True:
                if cancelado is not None and cancelado():
                    raise ErroDeAtualizacao("Download cancelado.")
                bloco = resposta.read(256 * 1024)
                if not bloco:
                    break
                saida.write(bloco)
                soma.update(bloco)
                baixado += len(bloco)
                if progresso is not None:
                    progresso(baixado, total)
    except ErroDeAtualizacao:
        parcial.unlink(missing_ok=True)
        raise
    except (OSError, TimeoutError) as erro:
        parcial.unlink(missing_ok=True)
        raise ErroDeAtualizacao(f"O download foi interrompido ({erro}).") from erro
    if atualizacao.tamanho and baixado != atualizacao.tamanho:
        parcial.unlink(missing_ok=True)
        raise ErroDeAtualizacao("O arquivo baixado veio incompleto. Tente de novo.")
    if atualizacao.sha256 and soma.hexdigest().lower() != atualizacao.sha256:
        parcial.unlink(missing_ok=True)
        raise ErroDeAtualizacao("O arquivo baixado não confere com o publicado no GitHub. Nada foi instalado.")
    parcial.replace(destino)
    return destino


def executar_instalador(caminho: Path) -> None:
    """Abre o instalador (o Windows pede a permissão de administrador, que o
    instalador exige). Quem chama fecha o programa logo depois, para os
    arquivos não ficarem em uso."""
    if sys.platform != "win32":
        raise ErroDeAtualizacao("A atualização automática só funciona no Windows.")
    try:
        os.startfile(str(caminho), arguments=PARAMETROS_DO_INSTALADOR)  # type: ignore[attr-defined]
    except OSError as erro:
        raise ErroDeAtualizacao(f"Não consegui abrir o instalador ({erro}).") from erro


def verificacao_automatica_ligada() -> bool:
    """Só o programa instalado (o .exe) se atualiza sozinho: rodando do
    código-fonte, versão e release não têm relação. CONTROLE_LUCROS_SEM_ATUALIZACAO
    desliga (testes, ou quem não quer a consulta ao GitHub)."""
    return bool(getattr(sys, "frozen", False)) and not os.environ.get("CONTROLE_LUCROS_SEM_ATUALIZACAO")
