"""Importa no banco a planilha gerada por tratar_planilhas_distribuicao.py.

    python tools/importar_historico.py [planilha] [--limpar]

Usa o mesmo caminho da tela de Importação (formato "Completo"): lê a aba
"Cadastro", casa empresas e sócios com o que já existe, cadastra os sócios
novos (como o botão "Cadastrar todos como novos sócios" da revisão) e aplica
as linhas na ordem da planilha — que é cronológica, e é ela que monta o
histórico de cada participação. Depois lança a aba "Movimentações".

Por segurança só roda em banco com "teste" no nome, como o
dados_ficticios.py. Para o banco do escritório, use a tela de Importação.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controle_lucros import db, repositories as repo  # noqa: E402
from controle_lucros.models import Movimentacao, Socio  # noqa: E402
from controle_lucros.planilha import importar_cadastro  # noqa: E402

PLANILHA_PADRAO = Path("dados_tratados/Importacao_historico_2019_2025.xlsx")
TIPOS = {
    "Adiantamento de lucro": "adiantamento_lucro",
    "Empréstimo da empresa ao sócio": "emprestimo_empresa_para_socio",
    "Empréstimo do sócio à empresa": "emprestimo_socio_para_empresa",
    "Devolução de capital": "devolucao_capital",
}


def importar(conn, planilha: Path) -> dict:
    linhas = importar_cadastro(planilha)
    for ordem, linha in enumerate(linhas):
        linha["_ordem"] = ordem
    preparado = repo.preparar_importacao_cadastro(conn, linhas)

    # Sócios novos: um cadastro por CPF (ou nome, sem CPF), reaproveitado em
    # todas as linhas dele.
    criados: dict[str, int] = {}
    resolvidas = list(preparado["prontas"])
    erros = []
    for pendencia in preparado["pendencias"]:
        chave = repo.normalizar_documento(pendencia["socio_cpf"]) or repo.normalizar_nome(pendencia["socio_nome"])
        if chave not in criados:
            try:
                criados[chave] = repo.salvar_socio(conn, Socio(
                    id=None, nome=pendencia["socio_nome"], cpf=pendencia["socio_cpf"] or "",
                    tipo_pessoa=pendencia.get("tipo_pessoa") or "fisica",
                ))
            except ValueError as exc:
                erros.append(f"{pendencia['socio_nome']}: {exc}")
                continue
        resolvidas.append({**pendencia, "socio_id": criados[chave]})
    resolvidas.sort(key=lambda l: l["_ordem"])

    inicio = time.monotonic()

    def progresso(feitas, total):
        if feitas % 500 == 0 or feitas == total:
            print(f"  {feitas}/{total} linhas ({time.monotonic() - inicio:.0f}s)", flush=True)

    aplicado = repo.aplicar_importacao_cadastro(conn, resolvidas, progresso=progresso)

    # Movimentações (adiantamento, empréstimos, devolução de capital).
    empresas = {e.numero_chamada: e for e in repo.listar_empresas(conn)}
    socios = repo.listar_socios(conn)
    por_cpf = {repo.normalizar_documento(s.cpf): s for s in socios if s.cpf}
    por_nome = {s.nome: s for s in socios}
    movimentacoes = 0
    aba = openpyxl.load_workbook(planilha, read_only=True)["Movimentações"]
    for ano, numero, _empresa, nome, cpf, tipo, data, valor in aba.iter_rows(min_row=2, values_only=True):
        empresa = empresas.get(str(numero or ""))
        socio = por_cpf.get(repo.normalizar_documento(cpf)) or por_nome.get(repo.normalizar_nome(nome))
        if empresa is None or socio is None or not valor:
            erros.append(f"movimentação {ano} {nome}: empresa ou sócio não encontrado")
            continue
        repo.salvar_movimentacao(conn, Movimentacao(
            id=None, empresa_id=empresa.id, socio_id=socio.id, tipo=TIPOS[tipo], valor=float(valor), data=str(data)[:10],
        ))
        movimentacoes += 1
    return {**aplicado, "linhas": len(linhas), "socios_criados": len(criados),
            "conflitos": len(preparado["conflitos"]), "movimentacoes": movimentacoes, "erros": erros,
            "detalhe_conflitos": preparado["conflitos"]}


def main() -> None:
    argumentos = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    argumentos.add_argument("planilha", nargs="?", default=str(PLANILHA_PADRAO))
    argumentos.add_argument("--limpar", action="store_true",
                            help="apaga empresas, sócios e lançamentos (não os usuários) antes de importar")
    opcoes = argumentos.parse_args()

    parametros = db.conexao_configurada()
    if parametros is None:
        sys.exit("Nenhuma conexão configurada.")
    if "teste" not in parametros.banco.lower():
        sys.exit(f'Recusado: o banco "{parametros.banco}" não tem "teste" no nome.')
    conn = db.connect(parametros)
    db.init_schema(conn)
    if conn.execute("SELECT COUNT(*) FROM empresa").fetchone()[0]:
        if not opcoes.limpar:
            sys.exit("O banco já tem empresas. Use --limpar para apagar e importar de novo.")
        dados = [t for t in db.TABELAS if t not in ("usuario", "layout_importacao")]
        conn.execute(f"TRUNCATE {', '.join(dados)} RESTART IDENTITY CASCADE")
        conn.commit()

    print(f"Importando {opcoes.planilha} em {parametros.descricao()}…")
    resultado = importar(conn, Path(opcoes.planilha))
    for chave in ("linhas", "empresas_criadas", "socios_criados", "vinculos_criados", "vinculos_encerrados",
                  "vinculos_ja_existentes", "participacoes_atualizadas", "distribuicoes_lancadas",
                  "movimentacoes", "conflitos"):
        print(f"  {chave}: {resultado[chave]}")
    for conflito in resultado["detalhe_conflitos"][:10]:
        print("  conflito:", conflito.get("empresa_nome"), "/", conflito.get("socio_nome"), "—", conflito.get("aviso"))
    for erro in resultado["erros"][:20]:
        print("  erro:", erro)


if __name__ == "__main__":
    main()
