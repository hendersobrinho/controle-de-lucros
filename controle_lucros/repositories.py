"""Operações de CRUD e consultas, uma função por caso de uso."""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets
import unicodedata

import psycopg

from . import fiscal, sessao
from .db import Conexao, Linha
from .auth import gerar_hash_senha, senha_confere
from .layout_importacao import LayoutImportacao, de_json, garantir_valido, limpar_colunas, para_json
from .models import (
    CAMPOS_COTAS_INFORME,
    CAMPOS_VALOR_INFORME,
    TIPOS_MOVIMENTACAO_LABEL,
    TRIMESTRES,
    AlteracaoContratual,
    DistribuicaoLucro,
    DistribuicaoTrimestral,
    Empresa,
    InformeRendimento,
    LogAtividade,
    Movimentacao,
    Socio,
    Usuario,
    VinculoSocietario,
    periodo_trimestre,
)


def _registrar_log(conn: Conexao, acao: str, entidade: str, entidade_id: int | None, detalhes: str) -> None:
    """Grava uma linha de auditoria com o usuário da sessão atual — chamado
    de dentro das próprias funções de gravação, na mesma transação."""
    usuario = sessao.usuario_atual()
    conn.execute(
        """INSERT INTO log_atividade (usuario_id, usuario_nome, data_hora, acao, entidade, entidade_id, detalhes)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (
            usuario.id if usuario else None,
            usuario.nome if usuario else "Sistema",
            dt.datetime.now().isoformat(timespec="seconds"),
            acao,
            entidade,
            entidade_id,
            detalhes,
        ),
    )


def normalizar_documento(valor: str | None) -> str:
    """CPF/CNPJ só com dígitos (e letras, no CNPJ novo), sem pontuação —
    pra "111.222.333-44" e "11122233344" casarem como o mesmo documento.
    Sem isso, um CPF cadastrado com máscara nunca bate contra o mesmo CPF
    vindo sem formatação de uma planilha (ou de outro cadastro)."""
    return re.sub(r"[^0-9A-Za-z]", "", valor or "").upper()


# ---------------------------------------------------------------- Empresa --


def listar_empresas(conn: Conexao) -> list[Empresa]:
    rows = conn.execute("SELECT * FROM empresa ORDER BY nome").fetchall()
    return [Empresa(**dict(r)) for r in rows]


def buscar_empresa(conn: Conexao, empresa_id: int) -> Empresa | None:
    row = conn.execute("SELECT * FROM empresa WHERE id=%s", (empresa_id,)).fetchone()
    return Empresa(**dict(row)) if row else None


def normalizar_nome(texto: str | None) -> str:
    """Nome de empresa ou sócio como o sistema guarda: MAIÚSCULO, sem espaço
    sobrando. Sem isso, "Clínica Ammare" digitado à mão e "CLÍNICA AMMARE"
    vindo da importação viram cadastros que parecem diferentes — e a busca,
    a ordem da lista e a conferência com o relatório tropeçam nisso. Os
    acentos ficam: são parte do nome."""
    return re.sub(r"\s+", " ", texto or "").strip().upper()


def salvar_empresa(conn: Conexao, e: Empresa) -> int:
    e.nome = normalizar_nome(e.nome)
    e.numero_chamada = (e.numero_chamada or "").strip()
    if e.id is None:
        cur = conn.execute(
            """INSERT INTO empresa (numero_chamada, nome, cnpj, capital_social, quantidade_cotas, valor_cota)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (e.numero_chamada, e.nome, e.cnpj, e.capital_social, e.quantidade_cotas, e.valor_cota),
        )
        novo_id = cur.fetchone()[0]
        _registrar_log(conn, "criar", "empresa", novo_id, f"{e.nome} (nº {e.numero_chamada})")
        conn.commit()
        return novo_id
    conn.execute(
        """UPDATE empresa SET numero_chamada=%s, nome=%s, cnpj=%s, capital_social=%s, quantidade_cotas=%s,
           valor_cota=%s WHERE id=%s""",
        (e.numero_chamada, e.nome, e.cnpj, e.capital_social, e.quantidade_cotas, e.valor_cota, e.id),
    )
    _registrar_log(conn, "atualizar", "empresa", e.id, f"{e.nome} (nº {e.numero_chamada})")
    conn.commit()
    return e.id


# Tudo o que pertence a uma empresa, na ordem em que pode ser apagado sem
# ferir chave estrangeira: o vínculo aponta pra alteração, então sai antes dela.
_DADOS_DA_EMPRESA = (
    ("informe_rendimento", "informe(s) de rendimentos"),
    ("distribuicao_trimestral", "lançamento(s) trimestral(is)"),
    ("distribuicao_lucro", "distribuição(ões) anual(is)"),
    ("periodo_distribuicao", "período(s) de distribuição"),
    ("movimentacao", "movimentação(ões)"),
    ("vinculo_societario", "vínculo(s) de sócio"),
    ("alteracao_contratual", "alteração(ões) contratual(is)"),
)


def resumo_exclusao_empresa(conn: Conexao, empresa_id: int) -> list[str]:
    """O que vai junto ao excluir a empresa, em frases pra tela de
    confirmação ("3 vínculo(s) de sócio") — só o que existe."""
    resumo = []
    for tabela, rotulo in _DADOS_DA_EMPRESA:
        total = conn.execute(f"SELECT COUNT(*) FROM {tabela} WHERE empresa_id=%s", (empresa_id,)).fetchone()[0]
        if total:
            resumo.append(f"{total} {rotulo}")
    fechados = conn.execute(
        "SELECT COUNT(*) FROM periodo_distribuicao WHERE empresa_id=%s AND fechado=1", (empresa_id,)
    ).fetchone()[0]
    if fechados:
        resumo.append(f"inclusive {fechados} ano(s) com período FECHADO")
    return resumo


def excluir_empresa(conn: Conexao, empresa_id: int) -> None:
    """Apaga a empresa com tudo o que é dela (ver _DADOS_DA_EMPRESA), numa
    transação só: ou some tudo, ou nada muda. Os sócios ficam — o cadastro
    deles é do escritório, e podem estar em outras empresas.

    Quem chama confirma antes, mostrando resumo_exclusao_empresa: sem a
    cascata, apagar uma empresa exigia desfazer vínculo por vínculo na aba
    Sócios, e o erro de chave estrangeira não dizia nem por onde começar."""
    empresa = buscar_empresa(conn, empresa_id)
    resumo = resumo_exclusao_empresa(conn, empresa_id)
    for tabela, _rotulo in _DADOS_DA_EMPRESA:
        conn.execute(f"DELETE FROM {tabela} WHERE empresa_id=%s", (empresa_id,))
    conn.execute("DELETE FROM empresa WHERE id=%s", (empresa_id,))
    detalhes = empresa.nome if empresa else ""
    if resumo:
        detalhes += " — junto: " + ", ".join(resumo)
    _registrar_log(conn, "excluir", "empresa", empresa_id, detalhes)
    conn.commit()


# ------------------------------------------------------------------ Socio --


def listar_socios(conn: Conexao) -> list[Socio]:
    rows = conn.execute("SELECT * FROM socio ORDER BY nome").fetchall()
    return [Socio(**dict(r)) for r in rows]


def chave_nome(valor: str | None) -> str:
    """Nome sem acento, sem caixa e sem espaço sobrando — "João da Silva" e
    "JOAO  DA SILVA" viram a mesma chave. Serve pra comparar, nunca pra
    gravar: o nome fica no banco como foi digitado."""
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    sem_acento = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(sem_acento.split()).upper()


def socios_semelhantes(
    conn: Conexao, nome: str, documento: str = "", ignorar_id: int | None = None
) -> list[tuple[Socio, str]]:
    """Sócios já cadastrados que podem ser a mesma pessoa que está sendo
    digitada, cada um com o motivo. Existe pra avisar ANTES de duplicar: um
    sócio repetido se espalha por todas as empresas dele e só aparece na hora
    de emitir informe, quando já é tarde.

    Não bloqueia nada — quem cadastra decide. Homônimo de verdade existe."""
    alvo_documento = normalizar_documento(documento)
    alvo_nome = chave_nome(nome)
    if not alvo_documento and len(alvo_nome) < 3:
        return []

    achados: list[tuple[Socio, str]] = []
    for socio in listar_socios(conn):
        if socio.id == ignorar_id:
            continue
        if alvo_documento and normalizar_documento(socio.cpf) == alvo_documento:
            achados.append((socio, "mesmo CPF/CNPJ"))
            continue
        if len(alvo_nome) < 3:
            continue
        chave = chave_nome(socio.nome)
        if chave == alvo_nome:
            achados.append((socio, "mesmo nome"))
        elif alvo_nome in chave or chave in alvo_nome:
            achados.append((socio, "nome parecido"))
    # Documento igual é indício mais forte que nome; vem primeiro na lista.
    ordem = {"mesmo CPF/CNPJ": 0, "mesmo nome": 1, "nome parecido": 2}
    achados.sort(key=lambda item: (ordem[item[1]], item[0].nome))
    return achados


def salvar_socio(conn: Conexao, s: Socio) -> int:
    s.nome = normalizar_nome(s.nome)
    cpf_normalizado = normalizar_documento(s.cpf)
    if cpf_normalizado:
        outros = conn.execute("SELECT id, nome, cpf FROM socio WHERE id IS DISTINCT FROM %s", (s.id,)).fetchall()
        outro = next((o for o in outros if normalizar_documento(o["cpf"]) == cpf_normalizado), None)
        if outro is not None:
            raise ValueError(f'Já existe um sócio cadastrado com esse CPF/CNPJ: "{outro["nome"]}".')
    if s.id is None:
        cur = conn.execute(
            "INSERT INTO socio (nome, cpf, tipo_pessoa) VALUES (%s, %s, %s) RETURNING id", (s.nome, s.cpf, s.tipo_pessoa)
        )
        novo_id = cur.fetchone()[0]
        _registrar_log(conn, "criar", "socio", novo_id, s.nome)
        conn.commit()
        return novo_id
    conn.execute("UPDATE socio SET nome=%s, cpf=%s, tipo_pessoa=%s WHERE id=%s", (s.nome, s.cpf, s.tipo_pessoa, s.id))
    _registrar_log(conn, "atualizar", "socio", s.id, s.nome)
    conn.commit()
    return s.id


def excluir_socio(conn: Conexao, socio_id: int) -> None:
    socio = conn.execute("SELECT nome FROM socio WHERE id=%s", (socio_id,)).fetchone()
    try:
        conn.execute("DELETE FROM socio WHERE id=%s", (socio_id,))
    except psycopg.IntegrityError:
        raise ValueError(
            "Não é possível excluir este sócio: há vínculos societários, distribuições ou movimentações "
            "registradas para ele. Remova-os primeiro."
        ) from None
    _registrar_log(conn, "excluir", "socio", socio_id, socio["nome"] if socio else "")
    conn.commit()


# ------------------------------------------------------- AlteracaoContratual --


def listar_alteracoes(conn: Conexao, empresa_id: int) -> list[AlteracaoContratual]:
    rows = conn.execute(
        "SELECT * FROM alteracao_contratual WHERE empresa_id=%s ORDER BY numero",
        (empresa_id,),
    ).fetchall()
    return [AlteracaoContratual(**{**dict(r), "fechada": bool(r["fechada"])}) for r in rows]


def buscar_alteracao(conn: Conexao, alteracao_id: int) -> AlteracaoContratual | None:
    row = conn.execute(
        "SELECT * FROM alteracao_contratual WHERE id=%s", (alteracao_id,)
    ).fetchone()
    if row is None:
        return None
    return AlteracaoContratual(**{**dict(row), "fechada": bool(row["fechada"])})


def proximo_numero_alteracao(conn: Conexao, empresa_id: int) -> int:
    maior = conn.execute(
        "SELECT MAX(numero) AS m FROM alteracao_contratual WHERE empresa_id=%s",
        (empresa_id,),
    ).fetchone()["m"]
    return (maior or 0) + 1


def estado_atual_empresa(conn: Conexao, empresa_id: int) -> dict:
    """Snapshot vigente: da alteração contratual mais recente *por data*
    (não por número) — um registro retroativo (nº mais alto, mas com data
    efetiva anterior a uma alteração já existente) não pode virar o estado
    "atual" só por ter sido cadastrado depois. Mesmo critério de ordenação
    de estado_empresa_no_periodo, pra nunca divergirem sobre o que é o
    estado vigente da empresa. Sem nenhuma alteração ainda, usa a
    empresa-base."""
    ultima = conn.execute(
        """SELECT nome_empresa AS nome, capital_social, quantidade_cotas
           FROM alteracao_contratual WHERE empresa_id=%s ORDER BY data DESC, numero DESC LIMIT 1""",
        (empresa_id,),
    ).fetchone()
    if ultima is not None:
        return dict(ultima)
    empresa = buscar_empresa(conn, empresa_id)
    return {
        "nome": empresa.nome,
        "capital_social": empresa.capital_social,
        "quantidade_cotas": empresa.quantidade_cotas,
    }


def numero_alteracao_em_uso(conn: Conexao, empresa_id: int, numero: int, ignorar_id: int | None = None) -> bool:
    return conn.execute(
        "SELECT 1 FROM alteracao_contratual WHERE empresa_id=%s AND numero=%s AND id IS DISTINCT FROM %s",
        (empresa_id, numero, ignorar_id),
    ).fetchone() is not None


def _validar_numero_alteracao(conn: Conexao, a: AlteracaoContratual) -> None:
    """O número é o do contrato de verdade, e quem começa a usar o sistema
    hoje não cadastra o passado: a primeira alteração registrada pode muito
    bem ser a Nº 7. Por isso o número é livre — só não pode repetir na
    mesma empresa, nem ser zero ou negativo."""
    if a.numero is None or int(a.numero) < 1:
        raise ValueError("O número da alteração contratual precisa ser 1 ou maior.")
    if numero_alteracao_em_uso(conn, a.empresa_id, int(a.numero), a.id):
        raise ValueError(
            f"Esta empresa já tem a alteração contratual Nº {a.numero}. Escolha outro número."
        )


def salvar_alteracao(conn: Conexao, a: AlteracaoContratual) -> int:
    a.nome_empresa = normalizar_nome(a.nome_empresa)
    existente = None
    if a.id is not None:
        existente = buscar_alteracao(conn, a.id)
        if existente is not None and existente.fechada:
            raise ValueError("Esta alteração contratual está fechada. Destranque-a para editar.")
    _validar_numero_alteracao(conn, a)
    _garantir_periodo_aberto(conn, a.empresa_id, a.data)
    if a.id is None:
        cur = conn.execute(
            """INSERT INTO alteracao_contratual
               (empresa_id, numero, data, nome_empresa, capital_social, quantidade_cotas, descricao, fechada)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 0) RETURNING id""",
            (a.empresa_id, a.numero, a.data, a.nome_empresa, a.capital_social, a.quantidade_cotas, a.descricao),
        )
        novo_id = cur.fetchone()[0]
        _registrar_log(
            conn, "criar", "alteracao_contratual", novo_id, f"Nº {a.numero} — {a.nome_empresa} — {a.descricao}"
        )
        conn.commit()
        return novo_id
    try:
        conn.execute(
            """UPDATE alteracao_contratual SET numero=%s, data=%s, nome_empresa=%s, capital_social=%s,
               quantidade_cotas=%s, descricao=%s WHERE id=%s""",
            (a.numero, a.data, a.nome_empresa, a.capital_social, a.quantidade_cotas, a.descricao, a.id),
        )
        # Mudou a data (ou o número, que ordena as do mesmo dia): os
        # movimentos desta alteração andam junto, e o quadro é refeito.
        if existente is not None and (existente.data, existente.numero) != (a.data, a.numero):
            recompor_quadro(conn, a.empresa_id)
        _registrar_log(
            conn, "atualizar", "alteracao_contratual", a.id, f"Nº {a.numero} — {a.nome_empresa} — {a.descricao}"
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return a.id


def fechar_alteracao(conn: Conexao, alteracao_id: int) -> None:
    conn.execute("UPDATE alteracao_contratual SET fechada=1 WHERE id=%s", (alteracao_id,))
    _registrar_log(conn, "fechar", "alteracao_contratual", alteracao_id, "")
    conn.commit()


def reabrir_alteracao(conn: Conexao, alteracao_id: int) -> None:
    conn.execute("UPDATE alteracao_contratual SET fechada=0 WHERE id=%s", (alteracao_id,))
    _registrar_log(conn, "reabrir", "alteracao_contratual", alteracao_id, "")
    conn.commit()


def _movimentos_da_alteracao(conn: Conexao, alteracao_id: int) -> tuple[list[Linha], list[Linha]]:
    """Vínculos que entraram e que saíram por esta alteração, com o nome do sócio."""
    def buscar(coluna: str) -> list[Linha]:
        return conn.execute(
            f"""SELECT v.*, s.nome AS socio_nome FROM vinculo_societario v
                JOIN socio s ON s.id = v.socio_id
                WHERE v.{coluna}=%s ORDER BY s.nome""",
            (alteracao_id,),
        ).fetchall()

    entradas = buscar("alteracao_entrada_id")
    ids_entrada = {v["id"] for v in entradas}
    # Vínculo que entrou E saiu pela mesma alteração já some como entrada.
    saidas = [v for v in buscar("alteracao_saida_id") if v["id"] not in ids_entrada]
    return entradas, saidas


def resumo_exclusao_alteracao(conn: Conexao, alteracao_id: int) -> dict:
    """Quem é afetado ao excluir a alteração: os nomes dos sócios cujo
    vínculo entrou por ela (e será apagado) e dos que saíram por ela (e
    voltam a ficar ativos)."""
    entradas, saidas = _movimentos_da_alteracao(conn, alteracao_id)
    return {
        "entradas": [v["socio_nome"] for v in entradas],
        "saidas": [v["socio_nome"] for v in saidas],
    }


def excluir_alteracao(conn: Conexao, alteracao_id: int) -> None:
    """Exclui a alteração DESFAZENDO o que ela registrou: os movimentos dela
    saem e o quadro é refeito — quem entrou por ela deixa de ter entrado,
    quem saiu por ela volta a ser sócio, e quem teve participação nova volta
    à de antes. As outras alterações continuam com o que registraram.

    Alteração trancada, ou movimento em período fechado, continua
    protegido: é preciso destrancar antes."""
    existente = buscar_alteracao(conn, alteracao_id)
    if existente is None:
        return
    if existente.fechada:
        raise ValueError("Esta alteração contratual está fechada. Destranque-a para excluir.")
    _garantir_periodo_aberto(conn, existente.empresa_id, existente.data)
    entradas, saidas = _movimentos_da_alteracao(conn, alteracao_id)
    try:
        conn.execute("DELETE FROM alteracao_movimento WHERE alteracao_id = %s", (alteracao_id,))
        recompor_quadro(conn, existente.empresa_id)
        for coluna in ("alteracao_entrada_id", "alteracao_saida_id"):
            conn.execute(f"UPDATE vinculo_societario SET {coluna} = NULL WHERE {coluna} = %s", (alteracao_id,))
        conn.execute("DELETE FROM alteracao_contratual WHERE id=%s", (alteracao_id,))
        detalhes = f"Nº {existente.numero}"
        if entradas:
            detalhes += f" — {len(entradas)} entrada(s) desfeita(s)"
        if saidas:
            detalhes += f" — {len(saidas)} saída(s) desfeita(s)"
        _registrar_log(conn, "excluir", "alteracao_contratual", alteracao_id, detalhes)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


# ----------------------------------------------- Movimentos da alteração --
#
# Uma alteração contratual é um documento: o número, a data, o capital e as
# cotas daquele momento, e o que ela registrou de cada sócio — quem entrou,
# quem saiu, quem continuou com participação nova. Isso fica em
# alteracao_movimento, que é dado DA alteração.
#
# O vínculo (a participação de um sócio na empresa, com entrada e saída) é o
# histórico do sócio, e sai dos movimentos: recompor_quadro passa por todas as
# alterações da empresa na ordem das datas e monta os vínculos. Antes eram os
# vínculos que guardavam tudo, e um mesmo vínculo era a entrada numa
# alteração e a saída na outra — mexer nele por uma mudava a outra.
#
# Vínculo sem alteração de entrada é história anterior ao controle por
# alteração (planilha importada, sócio de anos atrás): fica como está, e as
# alterações seguem a partir dele.

TIPOS_MOVIMENTO = {"entrada": "Entrou", "saida": "Saiu", "participacao": "Participação nova"}

# Descrições das alterações que o próprio sistema abre ao lançar entrada,
# saída ou mudança fora da tela de alterações. Só elas são juntadas sozinhas
# quando caem no mesmo dia (ver _juntar_alteracoes_do_mesmo_dia).
_MARCAS_DE_AUTOMATICA = (
    "(registrado pela aba de sócios)", "(registrada pelo claude)", "(editado na distribuição anual)",
    "importação de relatório",
)


def _e_automatica(descricao: str | None) -> bool:
    texto = (descricao or "").lower()
    return any(marca in texto for marca in _MARCAS_DE_AUTOMATICA)


def listar_movimentos(conn: Conexao, alteracao_id: int) -> list[dict]:
    """O que a alteração registrou, sócio por sócio, com a data efetiva de
    cada movimento (a da própria alteração, quando não tem data própria)."""
    alteracao = buscar_alteracao(conn, alteracao_id)
    if alteracao is None:
        return []
    ordem = {"entrada": 0, "participacao": 1, "saida": 2}
    linhas = [
        {**dict(r), "data_efetiva": r["data"] or alteracao.data}
        for r in conn.execute(
            """SELECT m.*, s.nome AS socio_nome, s.cpf AS socio_cpf FROM alteracao_movimento m
               JOIN socio s ON s.id = m.socio_id WHERE m.alteracao_id = %s""",
            (alteracao_id,),
        ).fetchall()
    ]
    linhas.sort(key=lambda m: (ordem[m["tipo"]], m["socio_nome"]))
    return linhas


def _movimento(conn: Conexao, alteracao_id: int, socio_id: int) -> dict | None:
    linha = conn.execute(
        "SELECT * FROM alteracao_movimento WHERE alteracao_id = %s AND socio_id = %s", (alteracao_id, socio_id)
    ).fetchone()
    return dict(linha) if linha else None


def _gravar_movimento(
    conn: Conexao,
    alteracao: AlteracaoContratual,
    socio_id: int,
    tipo: str,
    *,
    data: str | None = None,
    percentual: float | None = None,
    cotas: float | None = None,
    capital: float | None = None,
    fim: str | None = None,
    saida_nesta: bool = False,
) -> None:
    """Grava (ou substitui) o movimento do sócio nesta alteração. Não confere
    nem recompõe — quem chama faz as duas coisas."""
    if tipo not in TIPOS_MOVIMENTO:
        raise ValueError(f"Movimento inválido: {tipo}.")
    data = None if not data or data == alteracao.data else data
    if tipo == "saida" or not fim:
        fim, saida_nesta = None, False
    conn.execute(
        """INSERT INTO alteracao_movimento
           (alteracao_id, socio_id, tipo, data, percentual_capital, quantidade_cotas, valor_capital, fim, saida_nesta)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (alteracao_id, socio_id) DO UPDATE SET tipo = EXCLUDED.tipo, data = EXCLUDED.data,
               percentual_capital = EXCLUDED.percentual_capital, quantidade_cotas = EXCLUDED.quantidade_cotas,
               valor_capital = EXCLUDED.valor_capital, fim = EXCLUDED.fim, saida_nesta = EXCLUDED.saida_nesta""",
        (alteracao.id, socio_id, tipo, data, percentual, cotas, capital, fim, bool(saida_nesta)),
    )


def _plano_do_quadro(conn: Conexao, empresa_id: int, antes_de: AlteracaoContratual | None = None):
    """Monta, sem gravar, os vínculos que os movimentos dão: a história sem
    alteração (base) e, por cima dela, cada movimento na ordem das datas.
    Com antes_de, para no ponto imediatamente anterior àquela alteração — é
    o quadro que ela encontrou.

    Devolve (vínculos gravados hoje, como deve ficar cada vínculo da base,
    vínculos que os movimentos abrem, quem está aberto no fim)."""
    vinculos = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM vinculo_societario WHERE empresa_id = %s ORDER BY data_entrada, id", (empresa_id,)
        ).fetchall()
    ]
    alteracoes = {a.id: a for a in listar_alteracoes(conn, empresa_id)}
    movimentos = [
        dict(r)
        for r in conn.execute(
            """SELECT m.* FROM alteracao_movimento m JOIN alteracao_contratual a ON a.id = m.alteracao_id
               WHERE a.empresa_id = %s""",
            (empresa_id,),
        ).fetchall()
    ]

    limite = (antes_de.data, antes_de.data, antes_de.numero) if antes_de is not None else None
    eventos = []
    base: dict[int, dict] = {}
    for v in vinculos:
        if v["alteracao_entrada_id"] is not None:
            continue
        # Fechamento feito por alteração é refeito pelo movimento de saída;
        # o fechamento "de história" (sem alteração) fica. A história entra
        # na linha do tempo como as alterações — no mesmo dia, antes delas.
        fim = None if v["alteracao_saida_id"] is not None else v["data_saida"]
        base[v["id"]] = {**v, "data_saida": fim, "alteracao_saida_id": None}
        for quando, evento in ((v["data_entrada"], "base"), (fim, "base_fim")):
            if quando and (limite is None or (quando, "", -1) < limite):
                eventos.append(((quando, "", -1, 0 if evento == "base" else 1), evento, base[v["id"]], None))
    for m in movimentos:
        a = alteracoes.get(m["alteracao_id"])
        if a is None:
            continue
        quando = m["data"] or a.data
        if limite is not None and (m["alteracao_id"] == antes_de.id or (quando, a.data, a.numero) >= limite):
            continue
        eventos.append(((quando, a.data, a.numero, 0), "movimento", m, a))
        if m["fim"] and m["tipo"] != "saida" and (limite is None or (m["fim"], a.data, a.numero) < limite):
            eventos.append(((m["fim"], a.data, a.numero, 1), "fim", m, a))
    eventos.sort(key=lambda e: e[0])

    def fechar(vinculo: dict, quando: str, alteracao_id: int | None) -> None:
        vinculo["data_saida"] = max(quando, vinculo["data_entrada"])
        vinculo["alteracao_saida_id"] = alteracao_id

    novos: list[dict] = []
    abertos: dict[int, dict] = {}
    for (quando, *_resto), evento, m, a in eventos:
        socio = m["socio_id"]
        atual = abertos.get(socio)
        if evento == "base":
            abertos[socio] = m
            continue
        if evento == "base_fim":
            if atual is m:
                abertos.pop(socio)
            continue
        if evento == "fim":
            if atual is not None and atual.get("_movimento") == m["id"]:
                fechar(atual, quando, a.id if m["saida_nesta"] else None)
                abertos.pop(socio)
            continue
        if m["tipo"] == "saida":
            if atual is not None:
                fechar(atual, quando, a.id)
                abertos.pop(socio)
            continue
        if atual is not None:
            fechar(atual, quando, a.id)
        # Participação nova que não informa um valor fica com o de antes. O
        # capital só acompanha se as cotas também ficaram: cotas novas com o
        # capital antigo seria um número que ninguém conferiu.
        herda = atual if atual is not None else {}
        cotas = m["quantidade_cotas"] if m["quantidade_cotas"] is not None else herda.get("quantidade_cotas")
        if m["valor_capital"] is not None:
            capital = m["valor_capital"]
        elif m["quantidade_cotas"] is None:
            capital = herda.get("valor_capital")
        else:
            capital = None
        novo = {
            "empresa_id": empresa_id,
            "socio_id": socio,
            "percentual_capital": (m["percentual_capital"] if m["percentual_capital"] is not None
                                   else herda.get("percentual_capital") or 0.0),
            "quantidade_cotas": cotas,
            "valor_capital": capital,
            "data_entrada": quando,
            "data_saida": None,
            "alteracao_entrada_id": a.id,
            "alteracao_saida_id": None,
            "_movimento": m["id"],
        }
        novos.append(novo)
        abertos[socio] = novo
    return vinculos, base, novos, abertos


_CAMPOS_RECOMPOSTOS = (
    "percentual_capital", "quantidade_cotas", "valor_capital", "data_entrada", "data_saida", "alteracao_saida_id",
)


def _diferente(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            return a is not b
        return round(float(a), 6) != round(float(b), 6)
    return a != b


def recompor_quadro(conn: Conexao, empresa_id: int) -> int:
    """Deixa os vínculos da empresa como os movimentos das alterações dizem,
    mexendo só no que mudou — vínculo igual não é regravado, e a observação
    de quem já existia fica. Tudo é conferido antes de gravar: um período
    trancado no caminho barra a mudança inteira. Não faz commit."""
    vinculos, base, novos, _abertos = _plano_do_quadro(conn, empresa_id)
    atuais = {v["id"]: v for v in vinculos}
    comandos: list[tuple[str, tuple]] = []
    datas: set[str] = set()

    for vid, desejado in base.items():
        v = atuais[vid]
        if _diferente(v["data_saida"], desejado["data_saida"]) or v["alteracao_saida_id"] != desejado["alteracao_saida_id"]:
            datas |= {v["data_saida"], desejado["data_saida"]}
            comandos.append((
                "UPDATE vinculo_societario SET data_saida = %s, alteracao_saida_id = %s WHERE id = %s",
                (desejado["data_saida"], desejado["alteracao_saida_id"], vid),
            ))

    por_chave: dict[tuple, list[dict]] = {}
    for v in vinculos:
        if v["alteracao_entrada_id"] is not None:
            por_chave.setdefault((v["socio_id"], v["alteracao_entrada_id"]), []).append(v)
    for novo in novos:
        existentes = por_chave.get((novo["socio_id"], novo["alteracao_entrada_id"]))
        if existentes:
            v = existentes.pop(0)
            if any(_diferente(v[c], novo[c]) for c in _CAMPOS_RECOMPOSTOS):
                datas |= {v["data_entrada"], v["data_saida"], novo["data_entrada"], novo["data_saida"]}
                comandos.append((
                    """UPDATE vinculo_societario SET percentual_capital = %s, quantidade_cotas = %s,
                       valor_capital = %s, data_entrada = %s, data_saida = %s, alteracao_saida_id = %s
                       WHERE id = %s""",
                    tuple(novo[c] for c in _CAMPOS_RECOMPOSTOS) + (v["id"],),
                ))
        else:
            datas |= {novo["data_entrada"], novo["data_saida"]}
            comandos.append((
                """INSERT INTO vinculo_societario
                   (empresa_id, socio_id, percentual_capital, quantidade_cotas, valor_capital, data_entrada,
                    data_saida, alteracao_entrada_id, alteracao_saida_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (empresa_id, novo["socio_id"], novo["percentual_capital"], novo["quantidade_cotas"],
                 novo["valor_capital"], novo["data_entrada"], novo["data_saida"],
                 novo["alteracao_entrada_id"], novo["alteracao_saida_id"]),
            ))
    for sobras in por_chave.values():
        for v in sobras:
            datas |= {v["data_entrada"], v["data_saida"]}
            comandos.append(("DELETE FROM vinculo_societario WHERE id = %s", (v["id"],)))

    for data in sorted(d for d in datas if d):
        _garantir_periodo_aberto(conn, empresa_id, data)
    for sql, parametros in comandos:
        conn.execute(sql, parametros)
    return len(comandos)


def quadro_antes_da_alteracao(conn: Conexao, alteracao_id: int) -> dict[int, dict]:
    """Quem era sócio logo antes desta alteração, com a participação de
    então: socio_id -> vínculo. É de quem esta alteração pode registrar a
    saída ou a participação nova."""
    alteracao = buscar_alteracao(conn, alteracao_id)
    if alteracao is None:
        return {}
    _v, _b, _n, abertos = _plano_do_quadro(conn, alteracao.empresa_id, antes_de=alteracao)
    return abertos


def salvar_movimento(
    conn: Conexao,
    alteracao_id: int,
    socio_id: int,
    tipo: str,
    *,
    data: str | None = None,
    percentual: float | None = None,
    cotas: float | None = None,
    capital: float | None = None,
    fim: str | None = None,
    saida_nesta: bool = False,
) -> None:
    """Registra na alteração a entrada, a saída ou a participação nova de um
    sócio — substituindo o que ela tinha dele — e recompõe o quadro.

    Entrada é de quem não era sócio antes dela; saída e participação nova,
    de quem era. Desfeito por inteiro se algo barrar (período trancado,
    alteração trancada). saida_nesta: o fim é a saída por esta mesma
    alteração (entrou e saiu por ela)."""
    try:
        alteracao = buscar_alteracao(conn, alteracao_id)
        if alteracao is None:
            raise ValueError("A alteração contratual não existe mais.")
        if alteracao.fechada:
            raise ValueError(f"A alteração contratual Nº {alteracao.numero} está trancada. Destranque-a para mudar.")
        ja = _movimento(conn, alteracao_id, socio_id)
        if tipo == "participacao" and ja is not None and ja["tipo"] == "entrada":
            # Entrou por esta mesma alteração: a participação nova é a da
            # entrada corrigida (valor não informado fica com o dela).
            if capital is None and cotas is None:
                capital = ja["valor_capital"]
            percentual = ja["percentual_capital"] if percentual is None else percentual
            cotas = ja["quantidade_cotas"] if cotas is None else cotas
            tipo, data, fim, saida_nesta = "entrada", ja["data"], ja["fim"], bool(ja["saida_nesta"])
        quando = data or alteracao.data
        _garantir_periodo_aberto(conn, alteracao.empresa_id, quando)
        if fim is not None and fim < quando:
            raise ValueError("A data de saída não pode ser anterior à data de entrada.")
        antes = quadro_antes_da_alteracao(conn, alteracao_id)
        socio = conn.execute("SELECT nome FROM socio WHERE id = %s", (socio_id,)).fetchone()
        nome = socio["nome"] if socio else "O sócio"
        if tipo == "saida" and ja is not None and ja["tipo"] != "saida":
            # Entrou (ou teve participação nova) por esta mesma alteração e
            # sai por ela também: a saída fica no próprio movimento.
            if quando < (ja["data"] or alteracao.data):
                raise ValueError("A data de saída não pode ser anterior à data de entrada.")
            conn.execute("UPDATE alteracao_movimento SET fim = %s, saida_nesta = 1 WHERE id = %s",
                         (quando, ja["id"]))
            recompor_quadro(conn, alteracao.empresa_id)
            _registrar_log(conn, "movimentar", "alteracao_contratual", alteracao_id,
                           f"Nº {alteracao.numero} — {TIPOS_MOVIMENTO['saida']}: {nome}")
            conn.commit()
            return
        if tipo == "entrada" and socio_id in antes:
            raise ValueError(
                f"{nome} já é sócio antes desta alteração. Para mudar a participação dele, use "
                "\"Participação nova\"."
            )
        if tipo in ("saida", "participacao") and socio_id not in antes:
            raise ValueError(f"{nome} não é sócio na data desta alteração.")
        if tipo in ("saida", "participacao") and quando < antes[socio_id]["data_entrada"]:
            raise ValueError("A data não pode ser anterior à entrada do sócio.")
        _gravar_movimento(conn, alteracao, socio_id, tipo, data=quando, percentual=percentual, cotas=cotas,
                          capital=capital, fim=fim, saida_nesta=saida_nesta)
        recompor_quadro(conn, alteracao.empresa_id)
        _registrar_log(conn, "movimentar", "alteracao_contratual", alteracao_id,
                       f"Nº {alteracao.numero} — {TIPOS_MOVIMENTO[tipo]}: {nome}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def remover_movimento(conn: Conexao, alteracao_id: int, socio_id: int) -> None:
    """Tira da alteração o que ela registrou de um sócio, e recompõe."""
    try:
        alteracao = buscar_alteracao(conn, alteracao_id)
        if alteracao is None:
            return
        if alteracao.fechada:
            raise ValueError(f"A alteração contratual Nº {alteracao.numero} está trancada. Destranque-a para mudar.")
        movimento = _movimento(conn, alteracao_id, socio_id)
        if movimento is None:
            return
        _garantir_periodo_aberto(conn, alteracao.empresa_id, movimento["data"] or alteracao.data)
        conn.execute("DELETE FROM alteracao_movimento WHERE id = %s", (movimento["id"],))
        recompor_quadro(conn, alteracao.empresa_id)
        socio = conn.execute("SELECT nome FROM socio WHERE id = %s", (socio_id,)).fetchone()
        _registrar_log(conn, "movimentar", "alteracao_contratual", alteracao_id,
                       f"Nº {alteracao.numero} — removido: {socio['nome'] if socio else '?'}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def alteracao_do_dia(conn: Conexao, empresa_id: int, data: str, descricao: str) -> int:
    """A alteração da empresa naquele dia — a que já existe, ou uma nova.

    Entrada, saída e participação nova lançadas fora da tela de alterações
    (aba Sócios, Claude, importação) vão para a alteração do mesmo dia: dez
    sócios entrando juntos são UMA alteração com dez entradas, e não dez
    alterações. Não faz commit: quem chama grava o movimento junto."""
    existentes = [a for a in listar_alteracoes(conn, empresa_id) if a.data == data]
    abertas = [a for a in existentes if not a.fechada]
    if abertas:
        return min(abertas, key=lambda a: a.numero).id
    if existentes:
        raise ValueError(
            f"A alteração contratual Nº {existentes[0].numero}, desse dia, está trancada. Destranque-a para "
            "lançar a movimentação nela."
        )
    estado = estado_atual_empresa(conn, empresa_id)
    numero = proximo_numero_alteracao(conn, empresa_id)
    nova = conn.execute(
        """INSERT INTO alteracao_contratual
           (empresa_id, numero, data, nome_empresa, capital_social, quantidade_cotas, descricao, fechada)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 0) RETURNING id""",
        (empresa_id, numero, data, normalizar_nome(estado["nome"]), estado["capital_social"],
         estado["quantidade_cotas"], descricao),
    ).fetchone()[0]
    _registrar_log(conn, "criar", "alteracao_contratual", nova, f"Nº {numero} — {estado['nome']} — {descricao}")
    return nova


def _vinculo_do_movimento(conn: Conexao, alteracao_id: int, socio_id: int) -> int | None:
    linha = conn.execute(
        "SELECT id FROM vinculo_societario WHERE alteracao_entrada_id = %s AND socio_id = %s ORDER BY id DESC",
        (alteracao_id, socio_id),
    ).fetchone()
    return linha["id"] if linha else None


# -- arrumação dos dados de antes --


def _movimentos_tirados_dos_vinculos(conn: Conexao, alteracao: AlteracaoContratual) -> int:
    """Os movimentos de uma alteração gravada antes desta versão, lidos dos
    vínculos que apontam para ela — sem mexer nos vínculos."""
    linhas = [
        dict(r)
        for r in conn.execute(
            """SELECT * FROM vinculo_societario WHERE alteracao_entrada_id = %s OR alteracao_saida_id = %s
               ORDER BY data_entrada, id""",
            (alteracao.id, alteracao.id),
        ).fetchall()
    ]
    entraram = {v["socio_id"]: v for v in linhas if v["alteracao_entrada_id"] == alteracao.id}
    sairam = {v["socio_id"]: v for v in linhas if v["alteracao_saida_id"] == alteracao.id}
    for socio_id in set(entraram) | set(sairam):
        if socio_id in entraram:
            v = entraram[socio_id]
            # Outro vínculo saindo por ela = participação refeita; o mesmo
            # vínculo saindo por ela = entrou e saiu por esta alteração.
            refeita = socio_id in sairam and sairam[socio_id]["id"] != v["id"]
            saiu_nesta = v["alteracao_saida_id"] == alteracao.id
            fim = v["data_saida"] if v["data_saida"] and (v["alteracao_saida_id"] is None or saiu_nesta) else None
            _gravar_movimento(
                conn, alteracao, socio_id, "participacao" if refeita else "entrada",
                data=v["data_entrada"], percentual=v["percentual_capital"], cotas=v["quantidade_cotas"],
                capital=v["valor_capital"], fim=fim, saida_nesta=saiu_nesta,
            )
        else:
            _gravar_movimento(conn, alteracao, socio_id, "saida", data=sairam[socio_id]["data_saida"])
    return len(set(entraram) | set(sairam))


def _juntar_alteracoes_do_mesmo_dia(conn: Conexao) -> list[str]:
    """Junta numa só as alterações que o sistema abriu sozinho no mesmo dia
    para a mesma empresa (uma por sócio, como fazia antes). Ficam de fora os
    dias com alteração trancada ou com mais de uma cadastrada à mão — essas
    são decisão de quem as cadastrou."""
    feitas = []
    grupos = conn.execute(
        """SELECT empresa_id, data FROM alteracao_contratual GROUP BY empresa_id, data HAVING COUNT(*) > 1"""
    ).fetchall()
    for grupo in grupos:
        do_dia = [a for a in listar_alteracoes(conn, grupo["empresa_id"]) if a.data == grupo["data"]]
        manuais = [a for a in do_dia if not _e_automatica(a.descricao)]
        if any(a.fechada for a in do_dia) or len(manuais) > 1:
            continue
        destino = manuais[0] if manuais else min(do_dia, key=lambda a: a.numero)
        outras = sorted((a for a in do_dia if a.id != destino.id), key=lambda a: a.numero)
        try:
            for outra in outras:
                for m in conn.execute(
                    "SELECT * FROM alteracao_movimento WHERE alteracao_id = %s", (outra.id,)
                ).fetchall():
                    ja = _movimento(conn, destino.id, m["socio_id"])
                    if ja is not None and ja["tipo"] == "entrada" and m["tipo"] == "saida":
                        # Entrou e saiu no mesmo dia: não chegou a ser sócio.
                        conn.execute("DELETE FROM alteracao_movimento WHERE id = %s", (ja["id"],))
                    else:
                        tipo = "entrada" if ja is not None and ja["tipo"] == "entrada" else m["tipo"]
                        _gravar_movimento(conn, destino, m["socio_id"], tipo, data=m["data"] or outra.data,
                                          percentual=m["percentual_capital"], cotas=m["quantidade_cotas"],
                                          capital=m["valor_capital"], fim=m["fim"],
                                          saida_nesta=bool(m["saida_nesta"]))
                for coluna in ("alteracao_entrada_id", "alteracao_saida_id"):
                    conn.execute(f"UPDATE vinculo_societario SET {coluna} = %s WHERE {coluna} = %s",
                                 (destino.id, outra.id))
                conn.execute("DELETE FROM alteracao_contratual WHERE id = %s", (outra.id,))
            recompor_quadro(conn, destino.empresa_id)
            numeros = ", ".join(f"Nº {a.numero}" for a in outras)
            _registrar_log(conn, "juntar", "alteracao_contratual", destino.id,
                           f"Nº {destino.numero} — juntadas as do mesmo dia: {numeros}")
            conn.commit()
            feitas.append(f"{destino.nome_empresa}: {numeros} → Nº {destino.numero}")
        except Exception:
            # Período trancado no caminho, ou dado antigo que não fecha:
            # aquele dia fica como estava.
            conn.rollback()
    return feitas


def arrumar_alteracoes(conn: Conexao) -> None:
    """Chamado ao abrir o banco (db.init_schema). Dá movimentos às
    alterações gravadas antes de eles existirem e junta as que o sistema
    abria em duplicidade. Quando não há o que fazer, são duas consultas."""
    sem_movimento = conn.execute(
        """SELECT a.id FROM alteracao_contratual a
           WHERE NOT EXISTS (SELECT 1 FROM alteracao_movimento m WHERE m.alteracao_id = a.id)
             AND EXISTS (SELECT 1 FROM vinculo_societario v
                         WHERE v.alteracao_entrada_id = a.id OR v.alteracao_saida_id = a.id)"""
    ).fetchall()
    for linha in sem_movimento:
        # Uma por vez: dado antigo que não fecha deixa aquela alteração como
        # estava, e não impede o programa de abrir.
        try:
            _movimentos_tirados_dos_vinculos(conn, buscar_alteracao(conn, linha["id"]))
            conn.commit()
        except Exception:
            conn.rollback()
    _juntar_alteracoes_do_mesmo_dia(conn)


# ------------------------------------------------------ Período de distribuição --


def periodo_esta_fechado(conn: Conexao, empresa_id: int, ano_base: int) -> bool:
    row = conn.execute(
        "SELECT fechado FROM periodo_distribuicao WHERE empresa_id=%s AND ano_base=%s",
        (empresa_id, ano_base),
    ).fetchone()
    return bool(row["fechado"]) if row else False


def fechar_periodo(conn: Conexao, empresa_id: int, ano_base: int) -> None:
    """Tranca todo dado ligado a esse ano/empresa — distribuição, pró-labore,
    IRRF, movimentações, e qualquer mudança de sócio ou cotas datada dentro
    do ano. Nada disso pode ser alterado enquanto o período não for
    destrancado de novo."""
    existente = conn.execute(
        "SELECT id FROM periodo_distribuicao WHERE empresa_id=%s AND ano_base=%s", (empresa_id, ano_base)
    ).fetchone()
    hoje = dt.date.today().isoformat()
    if existente is not None:
        conn.execute("UPDATE periodo_distribuicao SET fechado=1, fechado_em=%s WHERE id=%s", (hoje, existente["id"]))
    else:
        conn.execute(
            "INSERT INTO periodo_distribuicao (empresa_id, ano_base, fechado, fechado_em) VALUES (%s, %s, 1, %s)",
            (empresa_id, ano_base, hoje),
        )
    _registrar_log(conn, "fechar", "periodo_distribuicao", empresa_id, f"Ano {ano_base}")
    conn.commit()


def reabrir_periodo(conn: Conexao, empresa_id: int, ano_base: int) -> None:
    conn.execute(
        "UPDATE periodo_distribuicao SET fechado=0 WHERE empresa_id=%s AND ano_base=%s", (empresa_id, ano_base)
    )
    _registrar_log(conn, "reabrir", "periodo_distribuicao", empresa_id, f"Ano {ano_base}")
    conn.commit()


def _garantir_periodo_aberto(conn: Conexao, empresa_id: int, data_ou_ano) -> None:
    """Barreira usada por toda função que grava algo datado — distribuição,
    movimentação, vínculo, alteração contratual. Aceita um ano (int) ou uma
    data ISO ("AAAA-MM-DD"), pra cada chamador poder passar o que já tem à
    mão sem precisar converter."""
    ano = data_ou_ano if isinstance(data_ou_ano, int) else int(str(data_ou_ano)[:4])
    if periodo_esta_fechado(conn, empresa_id, ano):
        raise ValueError(
            f"O período de {ano} desta empresa está trancado. Destranque-o na tela de Distribuição "
            "anual para poder alterar esses dados."
        )


# -------------------------------------------------------- VinculoSocietario --


def listar_vinculos_empresa(conn: Conexao, empresa_id: int) -> list[VinculoSocietario]:
    rows = conn.execute(
        "SELECT * FROM vinculo_societario WHERE empresa_id=%s ORDER BY data_entrada",
        (empresa_id,),
    ).fetchall()
    return [VinculoSocietario(**dict(r)) for r in rows]


def vinculos_movimentados_na_alteracao(
    conn: Conexao, alteracao_id: int
) -> list[VinculoSocietario]:
    """Vínculos que entraram e/ou saíram nesta alteração contratual específica."""
    rows = conn.execute(
        """SELECT * FROM vinculo_societario
           WHERE alteracao_entrada_id=%s OR alteracao_saida_id=%s""",
        (alteracao_id, alteracao_id),
    ).fetchall()
    return [VinculoSocietario(**dict(r)) for r in rows]


def _garantir_alteracao_editavel(conn: Conexao, alteracao_id: int | None) -> None:
    if alteracao_id is None:
        return
    alteracao = buscar_alteracao(conn, alteracao_id)
    if alteracao is not None and alteracao.fechada:
        raise ValueError("A alteração contratual associada está fechada. Destranque-a para editar.")


def _garantir_alteracao_da_empresa(conn: Conexao, alteracao_id: int | None, empresa_id: int) -> None:
    """Alteração escolhida pra um vínculo tem que ser da empresa dele — senão
    o sócio apareceria entrando numa empresa pela alteração de outra."""
    if alteracao_id is None:
        return
    alteracao = buscar_alteracao(conn, alteracao_id)
    if alteracao is None:
        raise ValueError("A alteração contratual escolhida não existe mais.")
    if alteracao.empresa_id != empresa_id:
        raise ValueError("A alteração contratual escolhida é de outra empresa.")


def salvar_vinculo(conn: Conexao, v: VinculoSocietario) -> int:
    if v.data_saida is not None and v.data_saida < v.data_entrada:
        raise ValueError("A data de saída não pode ser anterior à data de entrada.")
    anterior_ligado = None
    if v.id is not None:
        anterior_ligado = buscar_vinculo(conn, v.id)
    if (v.alteracao_entrada_id or v.alteracao_saida_id
            or (anterior_ligado is not None
                and (anterior_ligado.alteracao_entrada_id or anterior_ligado.alteracao_saida_id))):
        return _salvar_vinculo_de_alteracao(conn, v, anterior_ligado)
    _garantir_periodo_aberto(conn, v.empresa_id, v.data_entrada)
    if v.data_saida is not None:
        _garantir_periodo_aberto(conn, v.empresa_id, v.data_saida)
    _garantir_alteracao_da_empresa(conn, v.alteracao_entrada_id, v.empresa_id)
    _garantir_alteracao_da_empresa(conn, v.alteracao_saida_id, v.empresa_id)
    _garantir_alteracao_editavel(conn, v.alteracao_entrada_id)
    _garantir_alteracao_editavel(conn, v.alteracao_saida_id)
    if v.id is not None:
        # Tirar o vínculo de uma alteração trancada também é mexer nela: sem
        # isto, trocar a alteração de entrada por "nenhuma" passava, porque só
        # a alteração NOVA era conferida.
        anterior = buscar_vinculo(conn, v.id)
        if anterior is not None:
            _garantir_periodo_aberto(conn, anterior.empresa_id, anterior.data_entrada)
            if anterior.data_saida is not None:
                _garantir_periodo_aberto(conn, anterior.empresa_id, anterior.data_saida)
            _garantir_alteracao_editavel(conn, anterior.alteracao_entrada_id)
            _garantir_alteracao_editavel(conn, anterior.alteracao_saida_id)
    if v.id is None:
        cur = conn.execute(
            """INSERT INTO vinculo_societario
               (empresa_id, socio_id, percentual_capital, quantidade_cotas, data_entrada,
                data_saida, alteracao_entrada_id, alteracao_saida_id, observacao, valor_capital)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                v.empresa_id,
                v.socio_id,
                v.percentual_capital,
                v.quantidade_cotas,
                v.data_entrada,
                v.data_saida,
                v.alteracao_entrada_id,
                v.alteracao_saida_id,
                v.observacao,
                v.valor_capital,
            ),
        )
        novo_id = cur.fetchone()[0]
        _registrar_log(conn, "criar", "vinculo_societario", novo_id, _descricao_vinculo(conn, v))
        conn.commit()
        return novo_id
    conn.execute(
        """UPDATE vinculo_societario SET empresa_id=%s, socio_id=%s, percentual_capital=%s,
           quantidade_cotas=%s, data_entrada=%s, data_saida=%s, alteracao_entrada_id=%s,
           alteracao_saida_id=%s, observacao=%s, valor_capital=%s WHERE id=%s""",
        (
            v.empresa_id,
            v.socio_id,
            v.percentual_capital,
            v.quantidade_cotas,
            v.data_entrada,
            v.data_saida,
            v.alteracao_entrada_id,
            v.alteracao_saida_id,
            v.observacao,
            v.valor_capital,
            v.id,
        ),
    )
    _registrar_log(conn, "atualizar", "vinculo_societario", v.id, _descricao_vinculo(conn, v))
    conn.commit()
    return v.id


def _salvar_vinculo_de_alteracao(conn: Conexao, v: VinculoSocietario, anterior: VinculoSocietario | None) -> int:
    """salvar_vinculo de participação que passa por alteração contratual.
    Quem manda são os movimentos: a entrada é o movimento da alteração de
    entrada, a saída é o da alteração de saída. Gravar aqui é gravar neles —
    cada um na sua alteração — e recompor.

    Participação que já é de uma alteração não muda de alteração por aqui
    (isso se faz na própria alteração), e a saída que é a participação nova
    de outra alteração também não: mudar uma tela de sócio não pode mexer no
    que outra alteração registrou sem a pessoa ver."""
    _garantir_alteracao_da_empresa(conn, v.alteracao_entrada_id, v.empresa_id)
    _garantir_alteracao_da_empresa(conn, v.alteracao_saida_id, v.empresa_id)
    ligadas = {v.alteracao_entrada_id, v.alteracao_saida_id}
    if anterior is not None:
        ligadas |= {anterior.alteracao_entrada_id, anterior.alteracao_saida_id}
    for alteracao_id in ligadas - {None}:
        _garantir_alteracao_editavel(conn, alteracao_id)
    try:
        if anterior is not None and anterior.alteracao_entrada_id is not None:
            # Participação de uma alteração: corrige o movimento dela.
            entrada = buscar_alteracao(conn, anterior.alteracao_entrada_id)
            saida_id = anterior.alteracao_saida_id
            desfaz_saida = saida_id is not None and v.alteracao_saida_id is None and not v.data_saida
            if v.alteracao_entrada_id != anterior.alteracao_entrada_id or (
                v.alteracao_saida_id != saida_id and not desfaz_saida
            ):
                raise ValueError(
                    f"Esta participação foi registrada pela alteração contratual Nº {entrada.numero}. Para "
                    "trocar a alteração, mude por Alterações contratuais."
                )
            movimento = _movimento(conn, entrada.id, v.socio_id)
            # Entrou e saiu pela mesma alteração: a saída mora no próprio
            # movimento de entrada.
            nesta = saida_id is not None and saida_id == entrada.id
            if saida_id is not None and not nesta and (desfaz_saida or v.data_saida != anterior.data_saida):
                saida = buscar_alteracao(conn, saida_id)
                do_outro = _movimento(conn, saida.id, v.socio_id)
                if do_outro is None or do_outro["tipo"] != "saida":
                    raise ValueError(
                        f"A saída desta participação é a participação nova registrada na alteração Nº "
                        f"{saida.numero}. Para mudar a saída, mude por lá."
                    )
                if desfaz_saida:
                    conn.execute("DELETE FROM alteracao_movimento WHERE id = %s", (do_outro["id"],))
                else:
                    _gravar_movimento(conn, saida, v.socio_id, "saida", data=v.data_saida)
            fim = (v.data_saida or None) if saida_id is None or nesta else None
            _gravar_movimento(
                conn, entrada, v.socio_id, movimento["tipo"] if movimento else "entrada", data=v.data_entrada,
                percentual=v.percentual_capital, cotas=v.quantidade_cotas, capital=v.valor_capital, fim=fim,
                saida_nesta=nesta and fim is not None,
            )
        else:
            # História sem alteração (ou participação nova): o que não é de
            # alteração continua no vínculo; o que passa a ser, vira movimento.
            if v.alteracao_entrada_id is not None:
                entrada = buscar_alteracao(conn, v.alteracao_entrada_id)
                fim = v.data_saida if v.data_saida and v.alteracao_saida_id is None else None
                _gravar_movimento(conn, entrada, v.socio_id, "entrada", data=v.data_entrada,
                                  percentual=v.percentual_capital, cotas=v.quantidade_cotas,
                                  capital=v.valor_capital, fim=fim)
                if anterior is not None:
                    # O mesmo vínculo passa a ser desta alteração (o
                    # recompor o reconhece), em vez de sumir e nascer outro.
                    conn.execute("UPDATE vinculo_societario SET alteracao_entrada_id = %s WHERE id = %s",
                                 (entrada.id, anterior.id))
            else:
                fim = v.data_saida if v.alteracao_saida_id is None else None
                if anterior is None:
                    _garantir_periodo_aberto(conn, v.empresa_id, v.data_entrada)
                    anterior = buscar_vinculo(conn, conn.execute(
                        """INSERT INTO vinculo_societario
                           (empresa_id, socio_id, percentual_capital, quantidade_cotas, data_entrada, data_saida,
                            observacao, valor_capital)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                        (v.empresa_id, v.socio_id, v.percentual_capital, v.quantidade_cotas, v.data_entrada,
                         fim, v.observacao, v.valor_capital),
                    ).fetchone()[0])
                else:
                    for data in {anterior.data_entrada, v.data_entrada}:
                        _garantir_periodo_aberto(conn, v.empresa_id, data)
                    conn.execute(
                        """UPDATE vinculo_societario SET percentual_capital = %s, quantidade_cotas = %s,
                           valor_capital = %s, data_entrada = %s, observacao = %s,
                           data_saida = CASE WHEN alteracao_saida_id IS NULL THEN %s ELSE data_saida END
                           WHERE id = %s""",
                        (v.percentual_capital, v.quantidade_cotas, v.valor_capital, v.data_entrada,
                         v.observacao, fim, anterior.id),
                    )
            if anterior is not None and anterior.alteracao_saida_id not in (None, v.alteracao_saida_id):
                antigo = _movimento(conn, anterior.alteracao_saida_id, v.socio_id)
                if antigo is not None and antigo["tipo"] == "saida":
                    conn.execute("DELETE FROM alteracao_movimento WHERE id = %s", (antigo["id"],))
            if v.alteracao_saida_id is not None and v.data_saida:
                saida = buscar_alteracao(conn, v.alteracao_saida_id)
                _gravar_movimento(conn, saida, v.socio_id, "saida", data=v.data_saida)
        recompor_quadro(conn, v.empresa_id)
        if v.observacao is not None:
            atual = (_vinculo_do_movimento(conn, v.alteracao_entrada_id, v.socio_id)
                     if v.alteracao_entrada_id else (anterior.id if anterior else None))
            if atual is not None:
                conn.execute("UPDATE vinculo_societario SET observacao = %s WHERE id = %s", (v.observacao, atual))
        resultado = (_vinculo_do_movimento(conn, v.alteracao_entrada_id, v.socio_id)
                     if v.alteracao_entrada_id else anterior.id)
        _registrar_log(conn, "atualizar" if v.id else "criar", "vinculo_societario", resultado,
                       _descricao_vinculo(conn, v))
        conn.commit()
        return resultado
    except BaseException:
        conn.rollback()
        raise


def _descricao_vinculo(conn: Conexao, v: VinculoSocietario) -> str:
    socio = conn.execute("SELECT nome FROM socio WHERE id=%s", (v.socio_id,)).fetchone()
    empresa = conn.execute("SELECT nome FROM empresa WHERE id=%s", (v.empresa_id,)).fetchone()
    return f"{socio['nome'] if socio else '?'} em {empresa['nome'] if empresa else '?'} ({v.percentual_capital:.4f}%)"


def encerrar_vinculo(
    conn: Conexao, vinculo_id: int, data_saida: str, alteracao_saida_id: int | None
) -> None:
    """Fecha o vínculo vigente (preenche data_saida) sem apagar histórico.
    Com alteração, a saída é o movimento dela; sem, fica no próprio vínculo
    (ou no movimento que o abriu, se ele é de uma alteração)."""
    vinculo = buscar_vinculo(conn, vinculo_id)
    if vinculo is not None and data_saida < vinculo.data_entrada:
        raise ValueError("A data de saída não pode ser anterior à data de entrada.")
    if vinculo is not None:
        _garantir_periodo_aberto(conn, vinculo.empresa_id, data_saida)
    _garantir_alteracao_editavel(conn, alteracao_saida_id)
    if vinculo is not None and alteracao_saida_id is not None:
        salvar_movimento(conn, alteracao_saida_id, vinculo.socio_id, "saida", data=data_saida)
        return
    if vinculo is not None and vinculo.alteracao_entrada_id is not None:
        salvar_vinculo(conn, VinculoSocietario(**{**vinculo.__dict__, "data_saida": data_saida}))
        return
    conn.execute(
        "UPDATE vinculo_societario SET data_saida=%s, alteracao_saida_id=%s WHERE id=%s",
        (data_saida, alteracao_saida_id, vinculo_id),
    )
    _registrar_log(conn, "encerrar", "vinculo_societario", vinculo_id, f"Saída em {data_saida}")
    conn.commit()


def excluir_vinculo(conn: Conexao, vinculo_id: int) -> None:
    vinculo = buscar_vinculo(conn, vinculo_id)
    if vinculo is not None and vinculo.alteracao_entrada_id is not None:
        # Participação de uma alteração: excluir é tirar o movimento dela
        # (e a saída que só fazia sentido para esta participação), tudo
        # numa gravação só.
        _garantir_alteracao_editavel(conn, vinculo.alteracao_entrada_id)
        _garantir_alteracao_editavel(conn, vinculo.alteracao_saida_id)
        try:
            for data in (vinculo.data_entrada, vinculo.data_saida):
                if data:
                    _garantir_periodo_aberto(conn, vinculo.empresa_id, data)
            for alteracao_id, tipos in ((vinculo.alteracao_saida_id, ("saida",)),
                                        (vinculo.alteracao_entrada_id, tuple(TIPOS_MOVIMENTO))):
                movimento = _movimento(conn, alteracao_id, vinculo.socio_id) if alteracao_id else None
                if movimento is not None and movimento["tipo"] in tipos:
                    conn.execute("DELETE FROM alteracao_movimento WHERE id = %s", (movimento["id"],))
            recompor_quadro(conn, vinculo.empresa_id)
            conn.execute("DELETE FROM vinculo_societario WHERE id = %s", (vinculo_id,))
            _registrar_log(conn, "excluir", "vinculo_societario", vinculo_id, _descricao_vinculo(conn, vinculo))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return
    if vinculo is not None:
        _garantir_periodo_aberto(conn, vinculo.empresa_id, vinculo.data_entrada)
        if vinculo.data_saida is not None:
            _garantir_periodo_aberto(conn, vinculo.empresa_id, vinculo.data_saida)
        _garantir_alteracao_editavel(conn, vinculo.alteracao_entrada_id)
        _garantir_alteracao_editavel(conn, vinculo.alteracao_saida_id)
    conn.execute("DELETE FROM vinculo_societario WHERE id=%s", (vinculo_id,))
    _registrar_log(conn, "excluir", "vinculo_societario", vinculo_id, "")
    conn.commit()


def quantidade_socios_ativos_por_empresa(conn: Conexao) -> dict[int, int]:
    """Empresa -> quantos sócios ela tem hoje, pra lista de empresas inteira
    numa consulta só."""
    return {
        r["empresa_id"]: r["total"]
        for r in conn.execute(
            """SELECT empresa_id, COUNT(DISTINCT socio_id) AS total FROM vinculo_societario
               WHERE data_saida IS NULL GROUP BY empresa_id"""
        ).fetchall()
    }


def ficha_empresa(conn: Conexao, empresa_id: int) -> dict | None:
    """Tudo o que a ficha da empresa mostra, numa leitura só: o estado
    vigente (da alteração mais recente), o valor da cota, o quadro
    societário de hoje, quem já saiu, as alterações contratuais e o lucro
    distribuído por ano. Só lê — quem grava é a tela de edição."""
    empresa = buscar_empresa(conn, empresa_id)
    if empresa is None:
        return None
    estado = estado_atual_empresa(conn, empresa_id)
    valor_cota = valor_da_cota(conn, empresa_id)

    linhas = conn.execute(
        """SELECT v.*, s.nome AS socio_nome, s.cpf AS socio_cpf, s.tipo_pessoa
           FROM vinculo_societario v JOIN socio s ON s.id = v.socio_id
           WHERE v.empresa_id = %s ORDER BY v.percentual_capital DESC, s.nome""",
        (empresa_id,),
    ).fetchall()
    quadro, saidas = [], []
    for v in linhas:
        if v["data_saida"] is None:
            calculado = (v["quantidade_cotas"] or 0) * valor_cota if valor_cota and v["quantidade_cotas"] else None
            quadro.append({
                "vinculo_id": v["id"],
                "socio_id": v["socio_id"],
                "nome": v["socio_nome"],
                "documento": v["socio_cpf"] or "",
                "tipo_pessoa": v["tipo_pessoa"],
                "percentual": v["percentual_capital"],
                "cotas": v["quantidade_cotas"],
                "capital": v["valor_capital"] if v["valor_capital"] is not None else calculado,
                "capital_calculado": v["valor_capital"] is None and calculado is not None,
                "data_entrada": v["data_entrada"],
            })
        else:
            saidas.append({"socio_id": v["socio_id"], "nome": v["socio_nome"], "data_saida": v["data_saida"]})
    # Quem saiu e voltou não é "ex-sócio": fica só no quadro de hoje.
    ativos = {q["socio_id"] for q in quadro}
    saidas = sorted((s for s in saidas if s["socio_id"] not in ativos), key=lambda s: s["data_saida"], reverse=True)

    alteracoes = listar_alteracoes(conn, empresa_id)
    ultima = max(alteracoes, key=lambda a: (a.data, a.numero)) if alteracoes else None

    distribuicoes = conn.execute(
        """SELECT d.ano_base, SUM(d.valor_distribuido) AS total, COUNT(DISTINCT d.socio_id) AS socios,
                  COALESCE(MAX(p.fechado), 0) AS fechado
           FROM distribuicao_lucro d
           LEFT JOIN periodo_distribuicao p ON p.empresa_id = d.empresa_id AND p.ano_base = d.ano_base
           WHERE d.empresa_id = %s GROUP BY d.ano_base ORDER BY d.ano_base DESC LIMIT 5""",
        (empresa_id,),
    ).fetchall()

    return {
        "empresa": empresa,
        "capital_social": estado["capital_social"],
        "quantidade_cotas": estado["quantidade_cotas"],
        "valor_cota": valor_cota,
        "valor_cota_informado": bool(empresa.valor_cota),
        "quadro": quadro,
        "soma_percentual": sum(q["percentual"] for q in quadro),
        "saidas": saidas,
        "total_alteracoes": len(alteracoes),
        "ultima_alteracao": ultima,
        "fundacao_diferente": ultima is not None and (
            round(ultima.capital_social, 2) != round(empresa.capital_social, 2)
            or round(ultima.quantidade_cotas, 2) != round(empresa.quantidade_cotas, 2)
        ),
        "distribuicoes": [
            {"ano": d["ano_base"], "total": d["total"], "socios": d["socios"], "fechado": bool(d["fechado"])}
            for d in distribuicoes
        ],
    }



def ficha_alteracao(conn: Conexao, alteracao_id: int) -> dict | None:
    """O que a ficha de uma alteração contratual mostra: os dados do
    contrato, o que mudou em relação à alteração anterior (capital e
    cotas), quem entrou, quem saiu, quem só teve a participação refeita e
    o quadro societário como ficou depois dela. Só lê."""
    a = buscar_alteracao(conn, alteracao_id)
    if a is None:
        return None

    anteriores = [
        x for x in listar_alteracoes(conn, a.empresa_id)
        if x.id != a.id and (x.data, x.numero) < (a.data, a.numero)
    ]
    anterior = max(anteriores, key=lambda x: (x.data, x.numero)) if anteriores else None
    if anterior is not None:
        capital_antes, cotas_antes = anterior.capital_social, anterior.quantidade_cotas
    else:
        empresa = buscar_empresa(conn, a.empresa_id)
        capital_antes, cotas_antes = empresa.capital_social, empresa.quantidade_cotas

    linhas = conn.execute(
        """SELECT v.*, s.nome AS socio_nome, s.cpf AS socio_cpf
           FROM vinculo_societario v JOIN socio s ON s.id = v.socio_id
           WHERE v.empresa_id = %s ORDER BY v.percentual_capital DESC, s.nome""",
        (a.empresa_id,),
    ).fetchall()
    entraram = {v["socio_id"] for v in linhas if v["alteracao_entrada_id"] == a.id}
    sairam = {v["socio_id"] for v in linhas if v["alteracao_saida_id"] == a.id}
    # Fechar o vínculo antigo e abrir um novo na mesma alteração é como a
    # participação de quem continua é refeita: não é entrada nem saída.
    mudaram = entraram & sairam

    valor_cota = a.capital_social / a.quantidade_cotas if a.capital_social and a.quantidade_cotas else None
    quadro, saidas = [], []
    for v in linhas:
        # Quem entrou por esta alteração conta como sócio depois dela mesmo
        # com a data de entrada diferente (o contrato de hoje pode registrar
        # quem entrou antes, numa alteração que não foi cadastrada).
        entrou_aqui = v["alteracao_entrada_id"] == a.id
        ativo = (entrou_aqui or v["data_entrada"] <= a.data) and (
            v["data_saida"] is None or v["data_saida"] > a.data
        ) and v["alteracao_saida_id"] != a.id
        if ativo:
            if v["socio_id"] in mudaram:
                movimento = "mudou"
            elif v["alteracao_entrada_id"] == a.id:
                movimento = "entrou"
            else:
                movimento = ""
            calculado = v["quantidade_cotas"] * valor_cota if valor_cota and v["quantidade_cotas"] else None
            quadro.append({
                "socio_id": v["socio_id"],
                "nome": v["socio_nome"],
                "documento": v["socio_cpf"] or "",
                "percentual": v["percentual_capital"],
                "cotas": v["quantidade_cotas"],
                "capital": v["valor_capital"] if v["valor_capital"] is not None else calculado,
                "movimento": movimento,
            })
        elif v["alteracao_saida_id"] == a.id and v["socio_id"] not in mudaram:
            saidas.append({"socio_id": v["socio_id"], "nome": v["socio_nome"], "documento": v["socio_cpf"] or ""})

    return {
        "alteracao": a,
        "anterior": anterior,
        "capital_antes": capital_antes,
        "cotas_antes": cotas_antes,
        "valor_cota": valor_cota,
        "quadro": quadro,
        "soma_percentual": sum(q["percentual"] or 0 for q in quadro),
        "entradas": [q["nome"] for q in quadro if q["movimento"] == "entrou"],
        "mudancas": [q["nome"] for q in quadro if q["movimento"] == "mudou"],
        "saidas": saidas,
        # O que esta alteração registrou, com os valores dela — é o que se
        # corrige nela, sem mexer nas outras.
        "movimentos": listar_movimentos(conn, a.id),
    }


def movimentacoes_do_socio(conn: Conexao, socio_id: int) -> list[dict]:
    """A história do sócio em cada empresa, em eventos que se leem: entrou,
    saiu, ou teve a participação refeita. É assim que se pergunta ("quando
    ele entrou na Clínica?"), e não vínculo por vínculo.

    Fechar um vínculo e abrir outro na mesma data é como a participação de
    quem continua é refeita: vira "mudou" (a nova, com o antes e o depois) e
    "saiu" com refeita=True (o encerramento da antiga). Mais recente
    primeiro."""
    vinculos = sorted(listar_vinculos_socio(conn, socio_id), key=lambda v: (v.empresa_id, v.data_entrada, v.id))
    empresas = {e.id: e for e in listar_empresas(conn)}
    numeros: dict[int, int] = {}
    for empresa_id in {v.empresa_id for v in vinculos}:
        for a in listar_alteracoes(conn, empresa_id):
            numeros[a.id] = a.numero

    eventos: list[dict] = []
    for i, v in enumerate(vinculos):
        anterior = vinculos[i - 1] if i and vinculos[i - 1].empresa_id == v.empresa_id else None
        seguinte = vinculos[i + 1] if i + 1 < len(vinculos) and vinculos[i + 1].empresa_id == v.empresa_id else None
        empresa = empresas.get(v.empresa_id)
        base = {
            "empresa_id": v.empresa_id,
            "empresa_nome": empresa.nome if empresa else "?",
            "vinculo_id": v.id,
        }
        refeita = anterior is not None and anterior.data_saida == v.data_entrada
        eventos.append({
            **base,
            "tipo": "mudou" if refeita else "entrou",
            "data": v.data_entrada,
            "percentual": v.percentual_capital,
            "cotas": v.quantidade_cotas,
            "capital": v.valor_capital,
            "percentual_antes": anterior.percentual_capital if refeita else None,
            "cotas_antes": anterior.quantidade_cotas if refeita else None,
            "alteracao_numero": numeros.get(v.alteracao_entrada_id),
            "refeita": False,
        })
        if v.data_saida is not None:
            # Também quando a participação é refeita: a de antes foi
            # encerrada, e a saída dela aparece — marcada como "refeita",
            # pra não parecer que o sócio deixou a empresa.
            refeita_depois = seguinte is not None and seguinte.data_entrada == v.data_saida
            eventos.append({
                **base,
                "tipo": "saiu",
                "data": v.data_saida,
                "percentual": v.percentual_capital,
                "cotas": v.quantidade_cotas,
                "capital": v.valor_capital,
                "percentual_antes": None,
                "cotas_antes": None,
                "alteracao_numero": numeros.get(v.alteracao_saida_id),
                "refeita": refeita_depois,
            })
    # Mais recente primeiro; no mesmo dia, a participação nova acima do
    # encerramento da antiga, que acima de uma entrada.
    ordem = {"mudou": 2, "saiu": 1, "entrou": 0}
    eventos.sort(key=lambda e: (e["data"], ordem[e["tipo"]]), reverse=True)
    return eventos

def quantidade_empresas_ativas_por_socio(conn: Conexao) -> dict[int, int]:
    """Sócio -> em quantas empresas ele está hoje. Uma consulta só pra lista
    inteira: perguntar sócio por sócio seria uma ida ao servidor por linha."""
    return {
        r["socio_id"]: r["total"]
        for r in conn.execute(
            """SELECT socio_id, COUNT(DISTINCT empresa_id) AS total FROM vinculo_societario
               WHERE data_saida IS NULL GROUP BY socio_id"""
        ).fetchall()
    }


def listar_vinculos_socio(conn: Conexao, socio_id: int) -> list[VinculoSocietario]:
    rows = conn.execute(
        "SELECT * FROM vinculo_societario WHERE socio_id=%s ORDER BY data_entrada",
        (socio_id,),
    ).fetchall()
    return [VinculoSocietario(**dict(r)) for r in rows]


def valor_da_cota(conn: Conexao, empresa_id: int) -> float | None:
    """Quanto vale UMA cota da empresa: o valor informado no cadastro dela
    e, sem ele, o capital social vigente dividido pelo total de cotas. None
    quando não há como saber (empresa importada do relatório de sócios, que
    não traz capital nem cotas, e sem valor da cota informado)."""
    empresa = buscar_empresa(conn, empresa_id)
    if empresa is not None and empresa.valor_cota:
        return empresa.valor_cota
    estado = estado_atual_empresa(conn, empresa_id)
    if estado["quantidade_cotas"] and estado["capital_social"]:
        return estado["capital_social"] / estado["quantidade_cotas"]
    return None


def definir_valor_da_cota(conn: Conexao, empresa_id: int, valor: float) -> None:
    """Grava o valor nominal da cota na empresa — vale pra todos os sócios
    dela. Informado normalmente na hora de associar um sócio, que é quando a
    falta dele aparece."""
    empresa = buscar_empresa(conn, empresa_id)
    if empresa is None or (empresa.valor_cota is not None and round(empresa.valor_cota, 6) == round(valor, 6)):
        return
    conn.execute("UPDATE empresa SET valor_cota=%s WHERE id=%s", (valor, empresa_id))
    _registrar_log(conn, "atualizar", "empresa", empresa_id, f"Valor da cota: R$ {valor:.6g}")
    conn.commit()


def valor_participacao(conn: Conexao, vinculo: VinculoSocietario) -> float:
    """Capital do sócio pelas cotas: cotas do vínculo × valor de uma cota
    (ver valor_da_cota). Zero quando o valor da cota não é conhecido."""
    valor = valor_da_cota(conn, vinculo.empresa_id)
    return (vinculo.quantidade_cotas or 0) * (valor or 0.0)


def _ano_corrente() -> int:
    """Separado pra os testes fixarem o "ano corrente" da regra abaixo."""
    return dt.date.today().year


def alteracao_automatica_cabe(data: str) -> bool:
    """Se um movimento de sócio nesta data ainda ganha alteração contratual
    automática: só do ano corrente em diante.

    Entrada de sócio de anos atrás é história que já tem contrato próprio —
    criar uma alteração "nova" datada lá atrás inventaria um evento que o
    escritório não registrou, e bagunçaria a numeração. O vínculo fica sem
    alteração, e ela é associada (ou criada) depois, na edição do vínculo."""
    return bool(data) and int(data[:4]) >= _ano_corrente()


def _abrir_alteracao_automatica(conn: Conexao, empresa_id: int, data: str, descricao: str) -> tuple[int, bool]:
    """A alteração do dia (ver alteracao_do_dia), já gravada — para a
    importação, que lança várias linhas na mesma alteração. Devolve
    (id, se foi criada agora)."""
    do_dia = {a.id for a in listar_alteracoes(conn, empresa_id) if a.data == data}
    try:
        alteracao_id = alteracao_do_dia(conn, empresa_id, data, descricao)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return alteracao_id, alteracao_id not in do_dia


def associar_socio_a_empresa(
    conn: Conexao,
    empresa_id: int,
    socio_id: int,
    percentual_capital: float,
    quantidade_cotas: float,
    data_entrada: str,
    descricao: str = "Inclusão de sócio (registrado pela aba de Sócios)",
    valor_capital: float | None = None,
) -> int:
    """Associa o sócio à empresa e registra automaticamente a alteração
    contratual correspondente, para que o histórico da empresa reflita o
    movimento feito por aqui — se a entrada for do ano corrente (ver
    alteracao_automatica_cabe). Entrada mais antiga fica sem alteração,
    pra ser associada depois."""
    _garantir_periodo_aberto(conn, empresa_id, data_entrada)
    if not alteracao_automatica_cabe(data_entrada):
        return salvar_vinculo(
            conn,
            VinculoSocietario(
                id=None,
                empresa_id=empresa_id,
                socio_id=socio_id,
                percentual_capital=percentual_capital,
                quantidade_cotas=quantidade_cotas,
                data_entrada=data_entrada,
                data_saida=None,
                valor_capital=valor_capital,
            ),
        )
    try:
        alteracao_id = alteracao_do_dia(conn, empresa_id, data_entrada, descricao)
    except BaseException:
        conn.rollback()
        raise
    salvar_movimento(conn, alteracao_id, socio_id, "entrada", percentual=percentual_capital,
                     cotas=quantidade_cotas, capital=valor_capital)
    return _vinculo_do_movimento(conn, alteracao_id, socio_id)


def encerrar_vinculo_registrando_alteracao(
    conn: Conexao,
    vinculo: VinculoSocietario,
    data_saida: str,
    descricao: str = "Saída de sócio (registrado pela aba de Sócios)",
) -> None:
    # valida antes de abrir a alteração automática — senão uma data inválida
    # deixa pra trás uma alteração contratual vazia, já commitada, sem
    # nenhuma saída de sócio de fato registrada nela
    if data_saida < vinculo.data_entrada:
        raise ValueError("A data de saída não pode ser anterior à data de entrada.")
    _garantir_periodo_aberto(conn, vinculo.empresa_id, data_saida)
    try:
        alteracao_id = alteracao_do_dia(conn, vinculo.empresa_id, data_saida, descricao)
    except BaseException:
        conn.rollback()
        raise
    salvar_movimento(conn, alteracao_id, vinculo.socio_id, "saida")


def vinculos_ativos_fora_da_lista(
    conn: Conexao, empresa_id: int, documentos: set[str], data_corte: str
) -> list[tuple[VinculoSocietario, Socio]]:
    """Sócios ativos na empresa naquela data cujo documento não está em
    `documentos` — o quadro que o relatório traz.

    Sócio sem CPF/CNPJ cadastrado fica de fora da lista de propósito: não há
    como afirmar que ele não está no arquivo, e dar baixa por suposição é
    justamente o que não se pode fazer com histórico societário."""
    por_id = {s.id: s for s in listar_socios(conn)}
    fora = []
    for v in listar_vinculos_empresa(conn, empresa_id):
        if not (v.data_entrada <= data_corte and (v.data_saida is None or v.data_saida > data_corte)):
            continue
        socio = por_id.get(v.socio_id)
        documento = normalizar_documento(socio.cpf if socio else "")
        if socio is not None and documento and documento not in documentos:
            fora.append((v, socio))
    return fora


def encerrar_vinculos_fora_da_lista(
    conn: Conexao,
    empresa_id: int,
    documentos: set[str],
    data_saida: str,
    alteracao_id: int | None,
) -> list[str]:
    """Dá baixa em quem continua ativo aqui e não está no quadro do relatório,
    devolvendo os nomes encerrados.

    Só faz sentido quando o arquivo é o quadro societário completo — por isso
    é opção explícita de quem importa, e nunca o comportamento padrão. Quem
    entrou depois de `data_saida` não aparece: para aquela data ele ainda não
    era sócio, e não há vínculo a encerrar."""
    encerrados = []
    for vinculo, socio in vinculos_ativos_fora_da_lista(conn, empresa_id, documentos, data_saida):
        encerrar_vinculo(conn, vinculo.id, data_saida, alteracao_id)
        encerrados.append(socio.nome)
    return encerrados


def _capital_pelas_cotas(conn: Conexao, empresa_id: int, cotas: float | None) -> float | None:
    """Capital do sócio quando a planilha traz as cotas mas não o capital:
    cotas × valor da cota, se a empresa tem o valor da cota informado. Sem
    ele, fica sem capital — estimar por um capital social que pode estar
    desatualizado gravaria um número que ninguém conferiu."""
    if not cotas:
        return None
    empresa = buscar_empresa(conn, empresa_id)
    if empresa is None or not empresa.valor_cota:
        return None
    return round(cotas * empresa.valor_cota, 2)


# Campo da linha importada -> (atributo do vínculo, casas comparadas). As
# casas são a precisão com que cada valor é mostrado e guardado; comparar
# além disso faria toda importação "mudar" tudo por ruído de float.
_CAMPOS_DA_PARTICIPACAO = (
    ("percentual_capital", "percentual_capital", 4),
    ("cotas_socio", "quantidade_cotas", 4),
    ("valor_capital_socio", "valor_capital", 2),
)


def _mudancas_de_participacao(vinculo: VinculoSocietario, linha: dict) -> dict:
    """O que a linha traz de diferente do vínculo: atributo -> valor novo.

    Campo vazio (ou zero) na linha é campo que a planilha não informou — a
    leitura não distingue um do outro —, e não "zere a participação": sem
    esta regra, um layout sem a coluna de cotas apagaria as cotas de todo
    mundo a cada importação."""
    mudancas = {}
    for campo, atributo, casas in _CAMPOS_DA_PARTICIPACAO:
        novo = linha.get(campo)
        if not novo:
            continue
        atual = getattr(vinculo, atributo)
        if atual is None or round(float(atual), casas) != round(float(novo), casas):
            mudancas[atributo] = float(novo)
    return mudancas


def _registrar_nova_participacao(
    conn: Conexao,
    vinculo: VinculoSocietario,
    linha: dict,
    data_mudanca: str,
    alteracao_id: int | None,
) -> int:
    """Mesma mecânica de atualizar_cotas_vinculo — fecha o vínculo vigente e
    abre outro com a participação nova, os dois na mesma alteração —, só que
    na alteração que a importação já escolheu, em vez de abrir uma própria."""
    # Campo que o relatório não traz (cotas, capital) fica com o valor de
    # antes: sem esta retaguarda, cada importação zeraria os dois.
    salvar_movimento(
        conn, alteracao_id, vinculo.socio_id, "participacao", data=data_mudanca,
        percentual=linha.get("percentual_capital") or vinculo.percentual_capital,
        cotas=linha.get("cotas_socio") or vinculo.quantidade_cotas,
        capital=linha.get("valor_capital_socio") or vinculo.valor_capital,
    )
    return _vinculo_do_movimento(conn, alteracao_id, vinculo.socio_id)


def atualizar_cotas_vinculo(
    conn: Conexao,
    vinculo: VinculoSocietario,
    novo_percentual: float,
    novas_cotas: float,
    data: str,
    descricao: str = "Atualização de cotas (registrado pela aba de Sócios)",
) -> int:
    """Registra mudança na participação de um sócio já ativo: fecha o vínculo
    vigente e abre um novo com os valores atualizados, ambos amarrados à
    mesma alteração contratual — preserva o histórico em vez de sobrescrever."""
    if data < vinculo.data_entrada:
        raise ValueError("A data da atualização não pode ser anterior à data de entrada do vínculo.")
    _garantir_periodo_aberto(conn, vinculo.empresa_id, data)
    try:
        alteracao_id = alteracao_do_dia(conn, vinculo.empresa_id, data, descricao)
    except BaseException:
        conn.rollback()
        raise
    salvar_movimento(conn, alteracao_id, vinculo.socio_id, "participacao", percentual=novo_percentual,
                     cotas=novas_cotas)
    return _vinculo_do_movimento(conn, alteracao_id, vinculo.socio_id)


# ---------------------------------------------------------- DistribuicaoLucro --


def listar_distribuicoes(conn: Conexao, empresa_id: int, ano_base: int) -> list[DistribuicaoLucro]:
    rows = conn.execute(
        "SELECT * FROM distribuicao_lucro WHERE empresa_id=%s AND ano_base=%s",
        (empresa_id, ano_base),
    ).fetchall()
    return [DistribuicaoLucro(**dict(r)) for r in rows]


def salvar_distribuicao(
    conn: Conexao,
    empresa_id: int,
    ano_base: int,
    socio_id: int,
    valor_distribuido: float,
    pro_labore: float = 0.0,
    irrf: float = 0.0,
) -> int:
    """Uma linha por (empresa, ano, sócio) — salvar de novo substitui os
    valores em vez de duplicar, porque é a deliberação vigente daquele ano."""
    _garantir_periodo_aberto(conn, empresa_id, ano_base)
    existente = conn.execute(
        "SELECT id FROM distribuicao_lucro WHERE empresa_id=%s AND ano_base=%s AND socio_id=%s",
        (empresa_id, ano_base, socio_id),
    ).fetchone()
    socio = conn.execute("SELECT nome FROM socio WHERE id=%s", (socio_id,)).fetchone()
    detalhes = (
        f"{socio['nome'] if socio else '?'} — {ano_base} — R$ {valor_distribuido:.2f}"
        f" (pró-labore R$ {pro_labore:.2f}, IRRF R$ {irrf:.2f})"
    )
    if existente is not None:
        conn.execute(
            "UPDATE distribuicao_lucro SET valor_distribuido=%s, pro_labore=%s, irrf=%s WHERE id=%s",
            (valor_distribuido, pro_labore, irrf, existente["id"]),
        )
        _registrar_log(conn, "atualizar", "distribuicao_lucro", existente["id"], detalhes)
        conn.commit()
        return existente["id"]
    cur = conn.execute(
        """INSERT INTO distribuicao_lucro (empresa_id, ano_base, socio_id, valor_distribuido, pro_labore, irrf)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (empresa_id, ano_base, socio_id, valor_distribuido, pro_labore, irrf),
    )
    novo_id = cur.fetchone()[0]
    _registrar_log(conn, "criar", "distribuicao_lucro", novo_id, detalhes)
    conn.commit()
    return novo_id


def excluir_distribuicao(conn: Conexao, empresa_id: int, ano_base: int, socio_id: int) -> bool:
    """Apaga a distribuição do ano de um sócio. Devolve se havia o que apagar."""
    _garantir_periodo_aberto(conn, empresa_id, ano_base)
    linha = conn.execute(
        "DELETE FROM distribuicao_lucro WHERE empresa_id=%s AND ano_base=%s AND socio_id=%s RETURNING id",
        (empresa_id, ano_base, socio_id),
    ).fetchone()
    if linha is None:
        conn.rollback()
        return False
    socio = conn.execute("SELECT nome FROM socio WHERE id=%s", (socio_id,)).fetchone()
    _registrar_log(conn, "excluir", "distribuicao_lucro", linha["id"],
                   f"{socio['nome'] if socio else '?'} — {ano_base}")
    conn.commit()
    return True


def total_distribuido_empresa_ano(conn: Conexao, empresa_id: int, ano_base: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(valor_distribuido), 0) AS total FROM distribuicao_lucro WHERE empresa_id=%s AND ano_base=%s",
        (empresa_id, ano_base),
    ).fetchone()
    return row["total"]


def estado_empresa_no_periodo(conn: Conexao, empresa_id: int, ano_base: int) -> dict:
    """Capital social e total de cotas vigentes no início e no fim do ano (a
    partir do histórico de alterações contratuais) — dá pra saber se houve
    aumento/redução de capital, ou mudança na quantidade de cotas, naquele
    ano especificamente."""

    def estado_ate(data_limite: str) -> tuple[float, float]:
        row = conn.execute(
            """SELECT capital_social, quantidade_cotas FROM alteracao_contratual
               WHERE empresa_id=%s AND data <= %s
               ORDER BY data DESC, numero DESC LIMIT 1""",
            (empresa_id, data_limite),
        ).fetchone()
        if row is not None:
            return row["capital_social"], row["quantidade_cotas"]
        empresa = buscar_empresa(conn, empresa_id)
        return (empresa.capital_social, empresa.quantidade_cotas) if empresa else (0.0, 0.0)

    capital_inicio, cotas_inicio = estado_ate(f"{ano_base - 1}-12-31")
    capital_fim, cotas_fim = estado_ate(f"{ano_base}-12-31")
    return {
        "capital_inicio": capital_inicio,
        "capital_fim": capital_fim,
        "variacao_capital": capital_fim - capital_inicio,
        "cotas_inicio": cotas_inicio,
        "cotas_fim": cotas_fim,
        "variacao_cotas": cotas_fim - cotas_inicio,
    }


def consistencia_cotas_socios(conn: Conexao, empresa_id: int, ano_base: int) -> dict:
    """Compara o total de cotas da empresa no fim do ano contra a soma das
    cotas dos sócios ainda ativos nessa data. Se não bater, o capital/cotas
    da empresa mudou (por alteração contratual) mas ninguém redistribuiu as
    cotas entre os sócios — sinal de que a distribuição pode estar errada."""
    fim_ano = f"{ano_base}-12-31"
    estado = estado_empresa_no_periodo(conn, empresa_id, ano_base)

    row = conn.execute(
        """SELECT COALESCE(SUM(quantidade_cotas), 0) AS total FROM vinculo_societario
           WHERE empresa_id=%s AND data_entrada <= %s
             AND (data_saida IS NULL OR data_saida > %s)""",
        (empresa_id, fim_ano, fim_ano),
    ).fetchone()
    soma_socios = row["total"]

    return {
        "cotas_totais_empresa": estado["cotas_fim"],
        "soma_cotas_socios": soma_socios,
        "diferenca": estado["cotas_fim"] - soma_socios,
    }


def consistencia_percentual_socios(conn: Conexao, empresa_id: int, ano_base: int) -> dict:
    """A soma dos percentuais de capital dos sócios ativos deveria fechar em
    100%. Se não fechar, tem sócio faltando, sobrando, ou percentual
    cadastrado errado — vale avisar antes de fechar a distribuição do ano."""
    fim_ano = f"{ano_base}-12-31"
    row = conn.execute(
        """SELECT COALESCE(SUM(percentual_capital), 0) AS total FROM vinculo_societario
           WHERE empresa_id=%s AND data_entrada <= %s
             AND (data_saida IS NULL OR data_saida > %s)""",
        (empresa_id, fim_ano, fim_ano),
    ).fetchone()
    soma_percentual = row["total"]

    return {
        "soma_percentual": soma_percentual,
        "diferenca": 100 - soma_percentual,
    }


def buscar_vinculo(conn: Conexao, vinculo_id: int) -> VinculoSocietario | None:
    row = conn.execute("SELECT * FROM vinculo_societario WHERE id=%s", (vinculo_id,)).fetchone()
    return VinculoSocietario(**dict(row)) if row else None


# -------------------------------------------------------------- Movimentacao --


def listar_movimentacoes(
    conn: Conexao, empresa_id: int, socio_id: int, ano_base: int, tipo: str | None = None
) -> list[Movimentacao]:
    """tipo=None lista todos os 4 tipos juntos (empréstimo nos dois sentidos,
    adiantamento de lucro, devolução de capital) — pensado pra caber numa
    única tela de movimentações em vez de uma por tipo."""
    if tipo is None:
        rows = conn.execute(
            """SELECT * FROM movimentacao
               WHERE empresa_id=%s AND socio_id=%s AND left(data, 4)=%s
               ORDER BY data""",
            (empresa_id, socio_id, str(ano_base)),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM movimentacao
               WHERE empresa_id=%s AND socio_id=%s AND tipo=%s AND left(data, 4)=%s
               ORDER BY data""",
            (empresa_id, socio_id, tipo, str(ano_base)),
        ).fetchall()
    return [Movimentacao(**dict(r)) for r in rows]


def soma_movimentacoes(
    conn: Conexao, empresa_id: int, socio_id: int, ano_base: int, tipo: str
) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(valor), 0) AS total FROM movimentacao
           WHERE empresa_id=%s AND socio_id=%s AND tipo=%s AND left(data, 4)=%s""",
        (empresa_id, socio_id, tipo, str(ano_base)),
    ).fetchone()
    return row["total"]


def salvar_movimentacao(conn: Conexao, m: Movimentacao) -> int:
    _garantir_periodo_aberto(conn, m.empresa_id, m.data)
    socio = conn.execute("SELECT nome FROM socio WHERE id=%s", (m.socio_id,)).fetchone()
    detalhes = f"{TIPOS_MOVIMENTACAO_LABEL.get(m.tipo, m.tipo)} — {socio['nome'] if socio else '?'} — R$ {m.valor:.2f} — {m.data}"
    if m.id is None:
        cur = conn.execute(
            "INSERT INTO movimentacao (empresa_id, socio_id, tipo, valor, data) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (m.empresa_id, m.socio_id, m.tipo, m.valor, m.data),
        )
        novo_id = cur.fetchone()[0]
        _registrar_log(conn, "criar", "movimentacao", novo_id, detalhes)
        conn.commit()
        return novo_id
    conn.execute(
        "UPDATE movimentacao SET empresa_id=%s, socio_id=%s, tipo=%s, valor=%s, data=%s WHERE id=%s",
        (m.empresa_id, m.socio_id, m.tipo, m.valor, m.data, m.id),
    )
    _registrar_log(conn, "atualizar", "movimentacao", m.id, detalhes)
    conn.commit()
    return m.id


def excluir_movimentacao(conn: Conexao, movimentacao_id: int) -> None:
    existente = conn.execute(
        "SELECT empresa_id, data FROM movimentacao WHERE id=%s", (movimentacao_id,)
    ).fetchone()
    if existente is not None:
        _garantir_periodo_aberto(conn, existente["empresa_id"], existente["data"])
    conn.execute("DELETE FROM movimentacao WHERE id=%s", (movimentacao_id,))
    _registrar_log(conn, "excluir", "movimentacao", movimentacao_id, "")
    conn.commit()


# --------------------------------------------------- Panorama de distribuição --


def _inicio_do_vinculo_continuo(todos: list[Linha], vinculo_atual: Linha) -> str:
    """Anda pra trás nos segmentos do vínculo até achar onde a passagem
    *atual* realmente começou. Uma atualização de cotas fecha e reabre o
    vínculo no mesmo dia (data_saida do segmento anterior == data_entrada do
    novo) — isso não conta como reentrada, então continua andando pra trás.
    Uma saída de verdade deixa uma lacuna (o próximo segmento começa depois),
    e aí para: aquela data_entrada é a reentrada real do sócio.

    `visitados` evita loop infinito: uma correção no mesmo dia (cotas
    atualizadas no mesmo dia em que o vínculo começou) deixa um segmento
    com data_entrada == data_saida, que bateria consigo mesmo pra sempre
    sem essa trava."""
    atual = vinculo_atual
    visitados = {atual["id"]}
    while True:
        anterior = next(
            (v for v in todos if v["id"] not in visitados and v["data_saida"] == atual["data_entrada"]), None
        )
        if anterior is None:
            return atual["data_entrada"]
        visitados.add(anterior["id"])
        atual = anterior


def _saida_anterior_ao_vinculo_continuo(todos: list[Linha], primeira_entrada: str) -> str | None:
    """Se o sócio já tinha saído de vez antes de reentrar (a passagem atual
    começou em primeira_entrada, sem ligação contígua com nada antes), acha
    a data dessa saída anterior — é o outro lado do mesmo evento de
    reentrada, senão a saída simplesmente some da visão anual quando o
    sócio volta a ficar ativo no mesmo período analisado."""
    anteriores = [v for v in todos if v["data_saida"] is not None and v["data_saida"] < primeira_entrada]
    if not anteriores:
        return None
    return max(anteriores, key=lambda v: v["data_saida"])["data_saida"]


def panorama_distribuicao_anual(conn: Conexao, empresa_id: int, ano_base: int) -> list[dict]:
    """Uma linha por sócio (não por segmento de vínculo) que teve alguma
    participação no ano: cotas/percentual vigentes ao final do ano (ou no
    momento em que saiu), valor e % distribuído, empréstimo recebido, e se
    entrou/saiu da sociedade *naquele ano* — uma atualização de cotas no meio
    do ano fecha e reabre o vínculo internamente, mas não conta como o sócio
    tendo saído e voltado (ver _inicio_do_vinculo_continuo); uma saída e
    reentrada de verdade, anos depois, continua contando normalmente.

    Quando a empresa lança por trimestre, cada linha traz também o acumulado
    trimestral e de onde veio o valor anual mostrado ("trimestres" ou
    "manual")."""
    inicio, fim = f"{ano_base}-01-01", f"{ano_base}-12-31"

    # Vínculos e empréstimos da empresa inteira de uma vez, separados por
    # sócio aqui: com o banco no servidor, uma consulta por sócio vira uma
    # ida e volta pela rede por sócio — e a visão geral chama isto pra cada
    # empresa em cada ano.
    vinculos_por_socio: dict[int, list[Linha]] = {}
    for v in conn.execute(
        "SELECT * FROM vinculo_societario WHERE empresa_id=%s ORDER BY data_entrada, id",
        (empresa_id,),
    ).fetchall():
        vinculos_por_socio.setdefault(v["socio_id"], []).append(v)
    socios_no_ano = [
        socio_id
        for socio_id, vinculos in vinculos_por_socio.items()
        if any(v["data_entrada"] <= fim and (v["data_saida"] is None or v["data_saida"] >= inicio) for v in vinculos)
    ]
    movimentos: dict[int, dict[str, float]] = {}
    for r in conn.execute(
        """SELECT socio_id, tipo, SUM(valor) AS total FROM movimentacao
           WHERE empresa_id=%s AND left(data, 4)=%s GROUP BY socio_id, tipo""",
        (empresa_id, str(ano_base)),
    ).fetchall():
        movimentos.setdefault(r["socio_id"], {})[r["tipo"]] = r["total"]
    emprestimos = {sid: m.get("emprestimo_empresa_para_socio", 0.0) for sid, m in movimentos.items()}

    distribuicoes = {d.socio_id: d for d in listar_distribuicoes(conn, empresa_id, ano_base)}
    total_distribuido = total_distribuido_empresa_ano(conn, empresa_id, ano_base)
    # Só os sócios desta empresa no ano: montar o cadastro inteiro (mais de
    # mil sócios) para cada empresa e cada ano era 70% do tempo da visão
    # geral — 10 s no período todo.
    socios = {
        r["id"]: Socio(**dict(r))
        for r in conn.execute("SELECT * FROM socio WHERE id = ANY(%s)", (socios_no_ano,)).fetchall()
    } if socios_no_ano else {}
    acumulado = acumulado_trimestral(conn, empresa_id, ano_base)

    linhas = []
    for socio_id in socios_no_ano:
        todos = vinculos_por_socio[socio_id]

        vinculo_atual = next(
            (
                v
                for v in todos
                if v["data_entrada"] <= fim and (v["data_saida"] is None or v["data_saida"] > fim)
            ),
            None,
        )
        ainda_ativo = vinculo_atual is not None
        if vinculo_atual is None:
            candidatos = [v for v in todos if v["data_entrada"] <= fim and v["data_saida"] and v["data_saida"] >= inicio]
            vinculo_atual = max(candidatos, key=lambda v: v["data_saida"]) if candidatos else None
        if vinculo_atual is None:
            continue

        primeira_entrada = _inicio_do_vinculo_continuo(todos, vinculo_atual)
        saida_anterior = _saida_anterior_ao_vinculo_continuo(todos, primeira_entrada)
        reentrou_no_ano = saida_anterior is not None and inicio <= saida_anterior <= fim

        distribuicao = distribuicoes.get(socio_id)
        valor_distribuido = distribuicao.valor_distribuido if distribuicao else 0.0
        percentual_distribuido = (100 * valor_distribuido / total_distribuido) if total_distribuido else 0.0
        emprestimo = emprestimos.get(socio_id, 0.0)

        # De onde veio o valor anual. Em vez de guardar a origem numa coluna
        # (que ficaria mentindo assim que alguém editasse o outro lado), ela é
        # deduzida: se bate com a soma dos trimestres, veio dela. Se alguém
        # editou o anual à mão depois, o número deixa de bater e a tela
        # mostra "manual" — que é exatamente o que aconteceu.
        somas = acumulado.get(socio_id)
        origem_valor = "manual"
        if somas is not None:
            # Os três campos são propagados juntos pelos trimestres; se
            # QUALQUER um divergir, alguém editou o anual à mão e o rótulo
            # tem que dizer isso — comparar só o valor distribuído deixaria
            # um pró-labore editado passando por somatório.
            atuais = (
                valor_distribuido,
                distribuicao.pro_labore if distribuicao else 0.0,
                distribuicao.irrf if distribuicao else 0.0,
            )
            esperados = (somas["valor_distribuido"], somas["pro_labore"], somas["irrf"])
            if all(abs(a - e) <= 0.005 for a, e in zip(atuais, esperados)):
                origem_valor = "trimestres"

        socio = socios.get(socio_id)
        linhas.append(
            {
                "vinculo_id": vinculo_atual["id"],
                "socio_id": socio_id,
                "socio_nome": socio.nome if socio else "?",
                "socio_cpf": socio.cpf if socio else "",
                "socio_tipo_pessoa": socio.tipo_pessoa if socio else "fisica",
                "percentual_capital": vinculo_atual["percentual_capital"],
                "quantidade_cotas": vinculo_atual["quantidade_cotas"] or 0,
                "distribuicao_id": distribuicao.id if distribuicao else None,
                "valor_distribuido": valor_distribuido,
                "pro_labore": distribuicao.pro_labore if distribuicao else 0.0,
                "irrf": distribuicao.irrf if distribuicao else 0.0,
                "percentual_distribuido": percentual_distribuido,
                "tem_trimestres": somas is not None,
                "acumulado_trimestral": somas["valor_distribuido"] if somas else 0.0,
                "origem_valor": origem_valor,
                "emprestimo_recebido": emprestimo,
                "adiantamento": movimentos.get(socio_id, {}).get("adiantamento_lucro", 0.0),
                "emprestimo_feito": movimentos.get(socio_id, {}).get("emprestimo_socio_para_empresa", 0.0),
                "devolucao_capital": movimentos.get(socio_id, {}).get("devolucao_capital", 0.0),
                "data_entrada": vinculo_atual["data_entrada"],
                "data_saida": None if ainda_ativo else vinculo_atual["data_saida"],
                "entrou_no_ano": inicio <= primeira_entrada <= fim,
                "saiu_no_ano": (not ainda_ativo) and inicio <= vinculo_atual["data_saida"] <= fim,
                "reentrou_no_ano": reentrou_no_ano,
                "data_saida_anterior": saida_anterior if reentrou_no_ano else None,
            }
        )
    linhas.sort(key=lambda l: l["socio_nome"])
    return linhas


# ------------------------------------------------ Distribuição trimestral --


def listar_distribuicoes_trimestrais(
    conn: Conexao, empresa_id: int, ano_base: int, trimestre: int | None = None
) -> list[DistribuicaoTrimestral]:
    """trimestre=None traz o ano inteiro — é assim que se soma o acumulado."""
    if trimestre is None:
        rows = conn.execute(
            """SELECT * FROM distribuicao_trimestral WHERE empresa_id=%s AND ano_base=%s
               ORDER BY trimestre""",
            (empresa_id, ano_base),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM distribuicao_trimestral WHERE empresa_id=%s AND ano_base=%s AND trimestre=%s",
            (empresa_id, ano_base, trimestre),
        ).fetchall()
    return [DistribuicaoTrimestral(**dict(r)) for r in rows]


def ultimo_ano_com_distribuicao(conn: Conexao, empresa_id: int | None = None) -> int | None:
    """O ano mais recente com distribuição lançada (da empresa, ou de
    qualquer uma) — é onde as telas de distribuição abrem, em vez de num ano
    ainda vazio."""
    if empresa_id is None:
        row = conn.execute("SELECT MAX(ano_base) AS a FROM distribuicao_lucro").fetchone()
    else:
        row = conn.execute("SELECT MAX(ano_base) AS a FROM distribuicao_lucro WHERE empresa_id=%s",
                           (empresa_id,)).fetchone()
    return row["a"]


def trimestres_lancados(conn: Conexao, empresa_id: int, ano_base: int) -> list[int]:
    """Quais trimestres do ano já têm algum lançamento — é o que diz se esta
    empresa usa controle trimestral e até onde o acumulado já foi."""
    rows = conn.execute(
        """SELECT DISTINCT trimestre FROM distribuicao_trimestral
           WHERE empresa_id=%s AND ano_base=%s ORDER BY trimestre""",
        (empresa_id, ano_base),
    ).fetchall()
    return [r["trimestre"] for r in rows]


def acumulado_trimestral(
    conn: Conexao, empresa_id: int, ano_base: int, ate_trimestre: int | None = None
) -> dict[int, dict]:
    """Soma dos trimestres por sócio, {socio_id: {valor_distribuido, pro_labore,
    irrf}}. ate_trimestre limita o acumulado (o 2º trimestre mostra 1º + 2º)."""
    limite = ate_trimestre if ate_trimestre is not None else 4
    rows = conn.execute(
        """SELECT socio_id,
                  COALESCE(SUM(valor_distribuido), 0) AS valor_distribuido,
                  COALESCE(SUM(pro_labore), 0) AS pro_labore,
                  COALESCE(SUM(irrf), 0) AS irrf
           FROM distribuicao_trimestral
           WHERE empresa_id=%s AND ano_base=%s AND trimestre <= %s
           GROUP BY socio_id""",
        (empresa_id, ano_base, limite),
    ).fetchall()
    return {
        r["socio_id"]: {
            "valor_distribuido": r["valor_distribuido"],
            "pro_labore": r["pro_labore"],
            "irrf": r["irrf"],
        }
        for r in rows
    }


def salvar_distribuicao_trimestral(
    conn: Conexao,
    empresa_id: int,
    ano_base: int,
    trimestre: int,
    socio_id: int,
    valor_distribuido: float,
    pro_labore: float = 0.0,
    irrf: float = 0.0,
) -> int:
    """Grava o trimestre e reflete o acumulado do ano na distribuição anual.

    A propagação é o ponto todo do controle trimestral: sem ela existiriam
    dois números concorrentes pro mesmo ano, e o informe de rendimentos (que
    lê a distribuição anual) ficaria defasado a cada trimestre lançado.
    Editar o valor anual à mão depois continua valendo — até o próximo
    lançamento trimestral, que volta a escrever a soma por cima."""
    if trimestre not in TRIMESTRES:
        raise ValueError(f"Trimestre inválido: {trimestre}. Use 1, 2, 3 ou 4.")
    _garantir_periodo_aberto(conn, empresa_id, ano_base)

    existente = conn.execute(
        """SELECT id FROM distribuicao_trimestral
           WHERE empresa_id=%s AND ano_base=%s AND trimestre=%s AND socio_id=%s""",
        (empresa_id, ano_base, trimestre, socio_id),
    ).fetchone()
    socio = conn.execute("SELECT nome FROM socio WHERE id=%s", (socio_id,)).fetchone()
    detalhes = (
        f"{socio['nome'] if socio else '?'} — {trimestre}º trimestre de {ano_base} — "
        f"R$ {valor_distribuido:.2f} (pró-labore R$ {pro_labore:.2f}, IRRF R$ {irrf:.2f})"
    )

    if existente is not None:
        conn.execute(
            """UPDATE distribuicao_trimestral SET valor_distribuido=%s, pro_labore=%s, irrf=%s
               WHERE id=%s""",
            (valor_distribuido, pro_labore, irrf, existente["id"]),
        )
        _registrar_log(conn, "atualizar", "distribuicao_trimestral", existente["id"], detalhes)
        registro_id = existente["id"]
    else:
        cur = conn.execute(
            """INSERT INTO distribuicao_trimestral
               (empresa_id, ano_base, trimestre, socio_id, valor_distribuido, pro_labore, irrf)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (empresa_id, ano_base, trimestre, socio_id, valor_distribuido, pro_labore, irrf),
        )
        novo_id = cur.fetchone()[0]
        _registrar_log(conn, "criar", "distribuicao_trimestral", novo_id, detalhes)
        registro_id = novo_id
    conn.commit()

    _refletir_trimestres_no_anual(conn, empresa_id, ano_base, socio_id)
    return registro_id


def excluir_distribuicao_trimestral(conn: Conexao, registro_id: int) -> None:
    registro = conn.execute(
        "SELECT * FROM distribuicao_trimestral WHERE id=%s", (registro_id,)
    ).fetchone()
    if registro is None:
        return
    _garantir_periodo_aberto(conn, registro["empresa_id"], registro["ano_base"])
    conn.execute("DELETE FROM distribuicao_trimestral WHERE id=%s", (registro_id,))
    _registrar_log(
        conn,
        "excluir",
        "distribuicao_trimestral",
        registro_id,
        f"{registro['trimestre']}º trimestre de {registro['ano_base']}",
    )
    conn.commit()
    _refletir_trimestres_no_anual(conn, registro["empresa_id"], registro["ano_base"], registro["socio_id"])


def _refletir_trimestres_no_anual(
    conn: Conexao, empresa_id: int, ano_base: int, socio_id: int
) -> None:
    """Escreve a soma dos trimestres do sócio na distribuição anual. Quando o
    último trimestre do sócio é excluído, a soma vira zero e o anual zera
    junto — deixar o valor antigo lá seria pior: ninguém saberia de onde
    veio."""
    soma = acumulado_trimestral(conn, empresa_id, ano_base).get(
        socio_id, {"valor_distribuido": 0.0, "pro_labore": 0.0, "irrf": 0.0}
    )
    salvar_distribuicao(
        conn,
        empresa_id,
        ano_base,
        socio_id,
        soma["valor_distribuido"],
        soma["pro_labore"],
        soma["irrf"],
    )


def panorama_distribuicao_trimestral(
    conn: Conexao, empresa_id: int, ano_base: int, trimestre: int
) -> list[dict]:
    """Uma linha por sócio que esteve na sociedade em algum momento DAQUELE
    trimestre — quem saiu no 1º não aparece no 4º. Cada linha traz o que foi
    lançado no trimestre e o acumulado do ano até ele, que é o número que a
    distribuição anual está mostrando."""
    inicio, fim = periodo_trimestre(ano_base, trimestre)

    vinculos = conn.execute(
        """SELECT socio_id, percentual_capital, quantidade_cotas, data_entrada, data_saida
           FROM vinculo_societario
           WHERE empresa_id=%s AND data_entrada <= %s
             AND (data_saida IS NULL OR data_saida >= %s)
           ORDER BY data_entrada""",
        (empresa_id, fim, inicio),
    ).fetchall()

    lancamentos = {
        d.socio_id: d for d in listar_distribuicoes_trimestrais(conn, empresa_id, ano_base, trimestre)
    }
    acumulado = acumulado_trimestral(conn, empresa_id, ano_base, ate_trimestre=trimestre)
    socios = {s.id: s for s in listar_socios(conn)}

    linhas: dict[int, dict] = {}
    for v in vinculos:
        socio = socios.get(v["socio_id"])
        lancamento = lancamentos.get(v["socio_id"])
        somas = acumulado.get(v["socio_id"], {})
        # Um sócio pode ter mais de um segmento de vínculo dentro do mesmo
        # trimestre (atualização de cotas no meio); vale o mais recente, que é
        # o que a ordenação por data_entrada deixa por último.
        linhas[v["socio_id"]] = {
            "socio_id": v["socio_id"],
            "socio_nome": socio.nome if socio else "?",
            "socio_cpf": socio.cpf if socio else "",
            "percentual_capital": v["percentual_capital"],
            "quantidade_cotas": v["quantidade_cotas"] or 0,
            "registro_id": lancamento.id if lancamento else None,
            "valor_distribuido": lancamento.valor_distribuido if lancamento else 0.0,
            "pro_labore": lancamento.pro_labore if lancamento else 0.0,
            "irrf": lancamento.irrf if lancamento else 0.0,
            "acumulado_valor": somas.get("valor_distribuido", 0.0),
            "acumulado_pro_labore": somas.get("pro_labore", 0.0),
            "acumulado_irrf": somas.get("irrf", 0.0),
            "data_saida": v["data_saida"],
            "saiu_no_trimestre": bool(v["data_saida"] and inicio <= v["data_saida"] <= fim),
            "entrou_no_trimestre": inicio <= v["data_entrada"] <= fim,
        }
    return sorted(linhas.values(), key=lambda l: l["socio_nome"])


def total_distribuido_trimestre(
    conn: Conexao, empresa_id: int, ano_base: int, trimestre: int
) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(valor_distribuido), 0) AS total FROM distribuicao_trimestral
           WHERE empresa_id=%s AND ano_base=%s AND trimestre=%s""",
        (empresa_id, ano_base, trimestre),
    ).fetchone()
    return row["total"]


# ---------------------------------------------------- Importação em massa (cadastro) --


def preparar_importacao_cadastro(conn: Conexao, linhas: list[dict]) -> dict:
    """Casa cada linha da planilha de cadastro em massa (empresa + sócio +
    vínculo) contra os cadastros já existentes. Empresa é casada por nº de
    da empresa, CNPJ ou nome exato — baixo risco de duplicata, resolve sozinha
    (ou fica marcada pra criar). Sócio é casado por CPF, com nome único como
    retaguarda — mesma regra de nunca duplicar usada na importação de
    distribuição, porque o mesmo sócio costuma aparecer em várias empresas:
    o que não bate com segurança vira pendência pra revisão humana. Não
    escreve nada no banco.

    Devolve três listas: "prontas" (aplicáveis direto), "pendencias" (falta
    decidir qual é o sócio) e "conflitos" (a linha se contradiz e não dá pra
    aplicar sem corrigir a planilha)."""
    empresas = listar_empresas(conn)
    por_numero_chamada = {e.numero_chamada.strip(): e for e in empresas if e.numero_chamada and e.numero_chamada.strip()}
    por_cnpj = {normalizar_documento(e.cnpj): e for e in empresas if e.cnpj and e.cnpj.strip()}
    por_nome_empresa: dict[str, list[Empresa]] = {}
    for e in empresas:
        por_nome_empresa.setdefault(e.nome.strip().lower(), []).append(e)

    socios = listar_socios(conn)
    por_cpf_socio = {normalizar_documento(s.cpf): s for s in socios if s.cpf and s.cpf.strip()}
    por_nome_socio: dict[str, list[Socio]] = {}
    for s in socios:
        por_nome_socio.setdefault(s.nome.strip().lower(), []).append(s)

    prontas: list[dict] = []
    pendencias: list[dict] = []
    conflitos: list[dict] = []

    for linha in linhas:
        por_chamada = por_numero_chamada.get(linha["numero_chamada"].strip()) if linha["numero_chamada"] else None
        pelo_cnpj = por_cnpj.get(normalizar_documento(linha["cnpj"])) if linha["cnpj"] else None

        # Nº da empresa e CNPJ apontando pra empresas DIFERENTES é erro de
        # digitação na planilha, não uma escolha a fazer: aplicar em cima de
        # uma das duas lançaria distribuição na empresa errada, calado. A
        # linha fica de fora e o motivo é mostrado no fim da importação.
        if por_chamada is not None and pelo_cnpj is not None and por_chamada.id != pelo_cnpj.id:
            conflitos.append(
                {
                    **linha,
                    "aviso": (
                        f'O nº da empresa "{linha["numero_chamada"]}" é da empresa '
                        f'"{por_chamada.nome}", mas o CNPJ informado é da empresa '
                        f'"{pelo_cnpj.nome}". Corrija a planilha e importe de novo.'
                    ),
                }
            )
            continue

        empresa = por_chamada or pelo_cnpj
        if empresa is None:
            candidatos_empresa = por_nome_empresa.get(linha["empresa_nome"].strip().lower(), [])
            if len(candidatos_empresa) == 1:
                empresa = candidatos_empresa[0]

        # Linha sem sócio nenhum vem do modelo "Só empresas": cadastra a
        # empresa e não abre vínculo. Não é pendência — não há o que decidir.
        if not linha["socio_nome"] and not linha["socio_cpf"]:
            prontas.append({**linha, "empresa_existente": empresa, "socio_id": None})
            continue

        socio = None
        motivo_socio = None
        if linha["socio_cpf"]:
            socio = por_cpf_socio.get(normalizar_documento(linha["socio_cpf"]))
        if socio is None:
            candidatos_socio = por_nome_socio.get(linha["socio_nome"].strip().lower(), [])
            if len(candidatos_socio) == 1:
                socio = candidatos_socio[0]
            elif len(candidatos_socio) > 1:
                motivo_socio = (
                    f'Encontrei {len(candidatos_socio)} sócios cadastrados com o nome '
                    f'"{linha["socio_nome"]}" — escolha o correto.'
                )

        if socio is None:
            if motivo_socio is None:
                motivo_socio = "Nenhum sócio cadastrado bate com esse CPF/nome — cadastre um novo ou vincule manualmente."
            pendencias.append({**linha, "empresa_existente": empresa, "socio_sugestao": None, "aviso": motivo_socio})
            continue

        prontas.append({**linha, "empresa_existente": empresa, "socio_id": socio.id})

    return {"prontas": prontas, "pendencias": pendencias, "conflitos": conflitos}


def _lancar_distribuicao_da_linha(conn: Conexao, empresa_id: int, linha: dict) -> int:
    if linha.get("ano_base") and (linha.get("valor_distribuido") or linha.get("pro_labore") or linha.get("irrf")):
        salvar_distribuicao(
            conn,
            empresa_id,
            linha["ano_base"],
            linha["socio_id"],
            linha.get("valor_distribuido") or 0.0,
            pro_labore=linha.get("pro_labore") or 0.0,
            irrf=linha.get("irrf") or 0.0,
        )
        return 1
    return 0


def aplicar_importacao_cadastro(
    conn: Conexao,
    linhas_resolvidas: list[dict],
    progresso=None,
    *,
    alteracao_id: int | None = None,
    criar_alteracao_por_empresa: bool = False,
    descricao_alteracao_automatica: str = "Importação de relatório de sócios",
    atualizar_participacao: bool = False,
) -> dict:
    """Aplica linhas já resolvidas (empresa existente em "empresa_existente",
    ou dados pra criar uma nova; "socio_id" já definido, ou None quando a
    linha só cadastra a empresa): cria a empresa se
    for nova (reaproveitando entre linhas da mesma planilha), cria o vínculo
    só se o sócio ainda não tiver vínculo com essa empresa naquele período —
    nunca duplica nem a empresa nem o vínculo, nem quando o vínculo em questão
    já está encerrado. Se a linha trouxer "data_saida", encerra o vínculo (o
    recém-criado ou o que já existia). Se trouxer
    "ano_base" com valor distribuído, pró-labore ou IRRF, lança a
    distribuição daquele ano pra esse sócio.

    Movimentação de sócio é alteração contratual, então todo vínculo criado ou
    encerrado aqui é amarrado a uma: `alteracao_id` força a mesma alteração já
    aberta pra todas as linhas (importação feita de dentro de um card da aba
    Alterações, sempre de uma empresa só); sem ele, `criar_alteracao_por_empresa`
    abre — e reaproveita entre linhas da mesma empresa nesta chamada — uma
    alteração automática por empresa tocada, no mesmo espírito de
    _abrir_alteracao_automatica. Nenhum dos dois é passado por quem importa
    planilha de cadastro comum, que não é movimentação societária.

    Alteração automática só é aberta pra movimento do ano corrente em diante
    (ver alteracao_automatica_cabe): sócio que entrou há anos fica com a data
    de entrada certa e sem alteração, pra ela ser associada depois.

    Sócio que já tem vínculo ativo e vem com percentual, cotas ou capital
    diferentes tem o vínculo atualizado — reimportar a planilha corrigida é
    como se corrige o quadro. Com `atualizar_participacao` E uma alteração
    escolhida (`alteracao_id`), a mudança é registrada como movimentação: o
    vínculo atual é fechado na data da alteração e outro é aberto com os
    valores novos (ver _registrar_nova_participacao), preservando o
    histórico. Sem alteração escolhida, o vínculo é corrigido no lugar."""
    empresas_criadas = 0
    vinculos_criados = 0
    vinculos_ja_existentes = 0
    vinculos_encerrados = 0
    participacoes_atualizadas = 0
    participacoes_nao_atualizadas = 0
    distribuicoes_lancadas = 0
    cache_empresa_nova: dict[tuple[str, str], int] = {}
    alteracoes_automaticas: dict[int, int | None] = {}
    alteracoes_criadas = 0
    alteracoes_trancadas = 0

    def alteracao_para(empresa_id: int, data_referencia: str) -> int | None:
        nonlocal alteracoes_criadas, alteracoes_trancadas
        if alteracao_id is not None:
            return alteracao_id
        if not criar_alteracao_por_empresa or not alteracao_automatica_cabe(data_referencia):
            return None
        if empresa_id not in alteracoes_automaticas:
            try:
                existente, criada = _abrir_alteracao_automatica(
                    conn, empresa_id, data_referencia, descricao_alteracao_automatica
                )
            except ValueError:
                # A alteração desse dia está trancada: a movimentação entra
                # sem alteração (como história), e o resumo avisa.
                existente, criada = None, False
                alteracoes_trancadas += 1
            alteracoes_automaticas[empresa_id] = existente
            alteracoes_criadas += criada
        return alteracoes_automaticas[empresa_id]

    # `progresso` é opcional e recebe (feitas, total): permite à tela mostrar a
    # barra andando numa importação grande sem que este módulo precise saber
    # que existe uma tela.
    total = len(linhas_resolvidas)
    for feitas, linha in enumerate(linhas_resolvidas, start=1):
        if progresso is not None:
            progresso(feitas, total)
        empresa_existente = linha.get("empresa_existente")
        if empresa_existente is not None:
            empresa_id = empresa_existente.id
        else:
            chave = (linha["numero_chamada"].strip(), linha["empresa_nome"].strip().lower())
            empresa_id = cache_empresa_nova.get(chave)
            if empresa_id is None:
                empresa_id = salvar_empresa(
                    conn,
                    Empresa(
                        id=None,
                        numero_chamada=linha["numero_chamada"],
                        nome=linha["empresa_nome"],
                        cnpj=linha["cnpj"],
                        capital_social=linha["capital_social"],
                        quantidade_cotas=linha["quantidade_cotas"],
                    ),
                )
                cache_empresa_nova[chave] = empresa_id
                empresas_criadas += 1

        if linha.get("socio_id") is None:
            continue  # modelo "Só empresas": a empresa acima é tudo que a linha traz

        if not linha.get("valor_capital_socio"):
            capital = _capital_pelas_cotas(conn, empresa_id, linha.get("cotas_socio"))
            if capital:
                linha = {**linha, "valor_capital_socio": capital}

        vinculos_do_socio = [
            v for v in listar_vinculos_empresa(conn, empresa_id) if v.socio_id == linha["socio_id"]
        ]
        vinculo_ativo = next((v for v in vinculos_do_socio if v.data_saida is None), None)

        # Vínculo que já foi encerrado não é reconhecido pela busca acima, que
        # só olha os ativos. Sem esta checagem, reimportar o mesmo relatório
        # (o uso normal: o arquivo do mês seguinte traz o histórico inteiro de
        # novo) recriaria uma cópia de cada sócio que já saiu, e o quadro
        # societário iria enchendo de passado repetido a cada importação.
        if vinculo_ativo is None and linha.get("data_saida"):
            ja_encerrado = next(
                (
                    v
                    for v in vinculos_do_socio
                    if v.data_saida is not None and v.data_entrada == linha["data_entrada"]
                ),
                None,
            )
            if ja_encerrado is not None:
                vinculos_ja_existentes += 1
                # A data de saída gravada não é mexida de propósito: se o
                # relatório mudou de ideia sobre ela, isso é correção de
                # histórico e se faz na aba Sócios, onde fica registrada.
                # A distribuição da linha entra assim mesmo — pular a linha
                # inteira perdia o lucro do ano de quem já tinha saído.
                distribuicoes_lancadas += _lancar_distribuicao_da_linha(conn, empresa_id, linha)
                continue

        if vinculo_ativo is None:
            novo_id = salvar_vinculo(
                conn,
                VinculoSocietario(
                    id=None,
                    empresa_id=empresa_id,
                    socio_id=linha["socio_id"],
                    percentual_capital=linha["percentual_capital"],
                    quantidade_cotas=linha["cotas_socio"] or None,
                    valor_capital=linha.get("valor_capital_socio") or None,
                    data_entrada=linha["data_entrada"],
                    data_saida=None,
                    alteracao_entrada_id=alteracao_para(empresa_id, linha["data_entrada"]),
                ),
            )
            vinculos_criados += 1
            vinculo_ativo = buscar_vinculo(conn, novo_id)
        elif not linha.get("data_saida") and (mudancas := _mudancas_de_participacao(vinculo_ativo, linha)):
            if atualizar_participacao and alteracao_id is not None:
                # A mudança é datada na alteração que está recebendo a
                # importação — é ela que registra a nova divisão do capital —,
                # e não na data de ingresso do sócio, que é história antiga.
                data_mudanca = buscar_alteracao(conn, alteracao_id).data
                if data_mudanca < vinculo_ativo.data_entrada:
                    # Fechar um vínculo antes de ele começar não existe: a
                    # alteração é anterior ao ingresso deste sócio, e quem
                    # importou precisa saber que a participação ficou como estava.
                    participacoes_nao_atualizadas += 1
                else:
                    novo_id = _registrar_nova_participacao(
                        conn, vinculo_ativo, linha, data_mudanca, alteracao_id
                    )
                    participacoes_atualizadas += 1
                    vinculo_ativo = buscar_vinculo(conn, novo_id)
            else:
                for atributo, valor in mudancas.items():
                    setattr(vinculo_ativo, atributo, valor)
                try:
                    salvar_vinculo(conn, vinculo_ativo)
                    participacoes_atualizadas += 1
                except ValueError:
                    # Período fechado ou alteração trancada: o vínculo é
                    # histórico protegido, e o resumo avisa que ficou como estava.
                    participacoes_nao_atualizadas += 1
                    vinculo_ativo = buscar_vinculo(conn, vinculo_ativo.id)
        else:
            vinculos_ja_existentes += 1

        if linha.get("data_saida"):
            encerrar_vinculo(
                conn, vinculo_ativo.id, linha["data_saida"], alteracao_para(empresa_id, linha["data_saida"])
            )
            vinculos_encerrados += 1

        distribuicoes_lancadas += _lancar_distribuicao_da_linha(conn, empresa_id, linha)

    return {
        "empresas_criadas": empresas_criadas,
        "vinculos_criados": vinculos_criados,
        "vinculos_ja_existentes": vinculos_ja_existentes,
        "vinculos_encerrados": vinculos_encerrados,
        "participacoes_atualizadas": participacoes_atualizadas,
        "participacoes_nao_atualizadas": participacoes_nao_atualizadas,
        "distribuicoes_lancadas": distribuicoes_lancadas,
        "alteracoes_criadas": alteracoes_criadas,
        "alteracoes_trancadas": alteracoes_trancadas,
    }


# ---------------------------------------------------------- Análise / dashboard --

CLASSIFICACOES = ("proporcional", "desproporcional", "socio_sem_distribuicao", "empresa_sem_distribuicao")


def anos_disponiveis(conn: Conexao) -> list[int]:
    """Anos com algum lançamento de distribuição — usado pra sugerir o
    período no seletor do dashboard. Nunca retorna vazio: sem nenhum
    lançamento ainda, sugere o ano corrente."""
    linhas = conn.execute("SELECT DISTINCT ano_base FROM distribuicao_lucro").fetchall()
    anos = {r["ano_base"] for r in linhas}
    if not anos:
        anos.add(dt.date.today().year)
    return sorted(anos)


def _classificar_linha(linha: dict, total_distribuido_empresa: float, tolerancia: float) -> str:
    if total_distribuido_empresa <= 0:
        return "empresa_sem_distribuicao"
    if linha["valor_distribuido"] <= 0:
        return "socio_sem_distribuicao"
    if abs(linha["percentual_distribuido"] - linha["percentual_capital"]) <= tolerancia:
        return "proporcional"
    return "desproporcional"


def linhas_classificadas_empresa_ano(
    conn: Conexao, empresa_id: int, ano_base: int, tolerancia: float
) -> list[dict]:
    """panorama_distribuicao_anual + rótulo de classificação (proporcional /
    desproporcional / sócio sem distribuição / empresa sem distribuição)."""
    linhas = panorama_distribuicao_anual(conn, empresa_id, ano_base)
    total = total_distribuido_empresa_ano(conn, empresa_id, ano_base)
    return [{**linha, "ano_base": ano_base, "classificacao": _classificar_linha(linha, total, tolerancia)} for linha in linhas]


def analise_empresa_periodo(
    conn: Conexao, empresa_id: int, ano_de: int, ano_ate: int, tolerancia: float
) -> list[dict]:
    """Linhas classificadas de uma empresa, ano a ano, num intervalo."""
    resultado = []
    for ano in range(ano_de, ano_ate + 1):
        resultado.extend(linhas_classificadas_empresa_ano(conn, empresa_id, ano, tolerancia))
    return resultado


def versao_dos_dados(conn: Conexao) -> tuple:
    """Muda sempre que alguém grava alguma coisa — toda gravação deixa uma
    linha no log de atividade. Serve para quem guarda uma conta cara saber se
    ela ainda vale, sem refazê-la."""
    linha = conn.execute("SELECT COALESCE(MAX(id), 0) AS ultimo, COUNT(*) AS quantos FROM log_atividade").fetchone()
    return (linha["ultimo"], linha["quantos"])


class AnaliseCancelada(Exception):
    """Quem pediu a visão geral desistiu no meio (trocou de período)."""


def visao_geral(conn: Conexao, ano_de: int, ano_ate: int, tolerancia: float, progresso=None) -> dict:
    """Panorama de todas as empresas no período: quanto foi distribuído
    proporcional/desproporcionalmente, quanto foi emprestado, e quais
    empresas não distribuíram nada no período.

    progresso(feitas, total, nome_da_empresa) é chamado a cada empresa — é
    a conta demorada do sistema, e a tela mostra o andamento. Se ele
    levantar AnaliseCancelada, a análise para ali."""
    with conn.leituras_repetidas_em_cache():
        return _visao_geral(conn, ano_de, ano_ate, tolerancia, progresso)


def _visao_geral(conn: Conexao, ano_de: int, ano_ate: int, tolerancia: float, progresso=None) -> dict:
    empresas = listar_empresas(conn)
    linhas_todas: list[dict] = []
    resumo_empresas: list[dict] = []

    for feitas, empresa in enumerate(empresas):
        if progresso is not None:
            progresso(feitas, len(empresas), empresa.nome)
        linhas_empresa = analise_empresa_periodo(conn, empresa.id, ano_de, ano_ate, tolerancia)
        for linha in linhas_empresa:
            linhas_todas.append({**linha, "empresa_id": empresa.id, "empresa_nome": empresa.nome})

        total_empresa = sum(total_distribuido_empresa_ano(conn, empresa.id, ano) for ano in range(ano_de, ano_ate + 1))
        desproporcionais = sum(1 for l in linhas_empresa if l["classificacao"] == "desproporcional")
        emprestimos_empresa = sum(l["emprestimo_recebido"] for l in linhas_empresa)

        resumo_empresas.append(
            {
                "empresa_id": empresa.id,
                "empresa_nome": empresa.nome,
                "total_distribuido": total_empresa,
                "socios_desproporcionais": desproporcionais,
                "total_emprestimos": emprestimos_empresa,
                "distribuiu_no_periodo": total_empresa > 0,
            }
        )

    total_distribuido = sum(l["valor_distribuido"] for l in linhas_todas)
    total_proporcional = sum(l["valor_distribuido"] for l in linhas_todas if l["classificacao"] == "proporcional")
    total_desproporcional = sum(l["valor_distribuido"] for l in linhas_todas if l["classificacao"] == "desproporcional")
    total_emprestimos = sum(l["emprestimo_recebido"] for l in linhas_todas)

    return {
        "total_empresas": len(empresas),
        "empresas_sem_distribuicao": [r["empresa_nome"] for r in resumo_empresas if not r["distribuiu_no_periodo"]],
        "total_distribuido": total_distribuido,
        "total_proporcional": total_proporcional,
        "total_desproporcional": total_desproporcional,
        "total_emprestimos": total_emprestimos,
        "resumo_empresas": resumo_empresas,
        "linhas": linhas_todas,
    }



def painel_geral(conn: Conexao, ano_de: int, ano_ate: int, limite: int = 10) -> dict:
    """Os números do dashboard geral, em poucas consultas agregadas — com
    centenas de empresas, perguntar empresa por empresa deixava a tela lenta.

    - por_ano: total distribuído, pró-labore, IRRF, empresas e sócios de
      CADA ano com lançamento (a evolução mostra todos, o período escolhido
      fica realçado);
    - do período: totais, os que mais distribuíram/receberam, as
      movimentações por tipo e quantas empresas e sócios estavam ativos no
      fim dele;
    - anterior: o total do período de mesmo tamanho logo antes, pra dizer se
      cresceu ou caiu."""
    por_ano = [
        {"ano": r["ano_base"], "total": r["total"] or 0.0, "pro_labore": r["pro"] or 0.0, "irrf": r["irrf"] or 0.0,
         "empresas": r["empresas"], "socios": r["socios"]}
        for r in conn.execute(
            """SELECT ano_base, SUM(valor_distribuido) AS total, SUM(pro_labore) AS pro, SUM(irrf) AS irrf,
                      COUNT(DISTINCT empresa_id) FILTER (WHERE valor_distribuido > 0) AS empresas,
                      COUNT(DISTINCT socio_id) FILTER (WHERE valor_distribuido > 0) AS socios
               FROM distribuicao_lucro GROUP BY ano_base ORDER BY ano_base"""
        ).fetchall()
    ]
    no_periodo = [a for a in por_ano if ano_de <= a["ano"] <= ano_ate]
    total = sum(a["total"] for a in no_periodo)
    tamanho = ano_ate - ano_de + 1
    anterior = sum(a["total"] for a in por_ano if ano_de - tamanho <= a["ano"] < ano_de)
    # Só compara com o período anterior se os lançamentos cobrem a janela
    # inteira dele: comparar com uma janela pela metade inventaria um salto
    # que é só história que falta.
    tem_anterior = bool(por_ano) and por_ano[0]["ano"] <= ano_de - tamanho

    top_empresas = [
        {"empresa_id": r["id"], "nome": r["nome"], "numero": r["numero_chamada"], "total": r["total"],
         "socios": r["socios"]}
        for r in conn.execute(
            """SELECT e.id, e.nome, e.numero_chamada, SUM(d.valor_distribuido) AS total,
                      COUNT(DISTINCT d.socio_id) FILTER (WHERE d.valor_distribuido > 0) AS socios
               FROM distribuicao_lucro d JOIN empresa e ON e.id = d.empresa_id
               WHERE d.ano_base BETWEEN %s AND %s
               GROUP BY e.id, e.nome, e.numero_chamada HAVING SUM(d.valor_distribuido) > 0
               ORDER BY total DESC LIMIT %s""",
            (ano_de, ano_ate, limite),
        ).fetchall()
    ]
    top_socios = [
        {"socio_id": r["id"], "nome": r["nome"], "documento": r["cpf"] or "", "total": r["total"],
         "empresas": r["empresas"]}
        for r in conn.execute(
            """SELECT s.id, s.nome, s.cpf, SUM(d.valor_distribuido) AS total,
                      COUNT(DISTINCT d.empresa_id) FILTER (WHERE d.valor_distribuido > 0) AS empresas
               FROM distribuicao_lucro d JOIN socio s ON s.id = d.socio_id
               WHERE d.ano_base BETWEEN %s AND %s
               GROUP BY s.id, s.nome, s.cpf HAVING SUM(d.valor_distribuido) > 0
               ORDER BY total DESC LIMIT %s""",
            (ano_de, ano_ate, limite),
        ).fetchall()
    ]
    movimentos = {
        r["tipo"]: r["total"] or 0.0
        for r in conn.execute(
            """SELECT tipo, SUM(valor) AS total FROM movimentacao
               WHERE left(data, 4) BETWEEN %s AND %s GROUP BY tipo""",
            (str(ano_de), str(ano_ate)),
        ).fetchall()
    }
    fim = f"{ano_ate}-12-31"
    ativos = conn.execute(
        """SELECT COUNT(DISTINCT empresa_id) AS empresas, COUNT(DISTINCT socio_id) AS socios
           FROM vinculo_societario WHERE data_entrada <= %s AND (data_saida IS NULL OR data_saida > %s)""",
        (fim, fim),
    ).fetchone()
    return {
        "por_ano": por_ano,
        "total": total,
        "pro_labore": sum(a["pro_labore"] for a in no_periodo),
        "irrf": sum(a["irrf"] for a in no_periodo),
        "empresas_que_distribuiram": len(_empresas_com_distribuicao(conn, ano_de, ano_ate)),
        "socios_que_receberam": conn.execute(
            """SELECT COUNT(DISTINCT socio_id) AS n FROM distribuicao_lucro
               WHERE ano_base BETWEEN %s AND %s AND valor_distribuido > 0""",
            (ano_de, ano_ate),
        ).fetchone()["n"],
        "total_anterior": anterior if tem_anterior else None,
        "top_empresas": top_empresas,
        "top_socios": top_socios,
        "movimentos": movimentos,
        "empresas_ativas": ativos["empresas"],
        "socios_ativos": ativos["socios"],
    }


def _empresas_com_distribuicao(conn: Conexao, ano_de: int, ano_ate: int) -> list[int]:
    return [
        r["empresa_id"]
        for r in conn.execute(
            """SELECT DISTINCT empresa_id FROM distribuicao_lucro
               WHERE ano_base BETWEEN %s AND %s AND valor_distribuido > 0""",
            (ano_de, ano_ate),
        ).fetchall()
    ]


def painel_empresa(conn: Conexao, empresa_id: int) -> dict:
    """O que o dashboard de uma empresa mostra além das linhas classificadas:
    o total de cada ano com a parte de cada sócio (pra empilhar no gráfico) e
    as movimentações por ano."""
    por_ano: dict[int, dict] = {}
    for r in conn.execute(
        """SELECT d.ano_base, d.socio_id, s.nome, d.valor_distribuido, d.pro_labore, d.irrf
           FROM distribuicao_lucro d JOIN socio s ON s.id = d.socio_id
           WHERE d.empresa_id = %s ORDER BY d.ano_base""",
        (empresa_id,),
    ).fetchall():
        ano = por_ano.setdefault(r["ano_base"], {"ano": r["ano_base"], "total": 0.0, "pro_labore": 0.0,
                                                  "irrf": 0.0, "socios": {}})
        ano["total"] += r["valor_distribuido"] or 0.0
        ano["pro_labore"] += r["pro_labore"] or 0.0
        ano["irrf"] += r["irrf"] or 0.0
        if r["valor_distribuido"]:
            ano["socios"][r["socio_id"]] = (r["nome"], r["valor_distribuido"])
    movimentos: dict[int, dict[str, float]] = {}
    for r in conn.execute(
        """SELECT left(data, 4) AS ano, tipo, SUM(valor) AS total FROM movimentacao
           WHERE empresa_id = %s GROUP BY left(data, 4), tipo""",
        (empresa_id,),
    ).fetchall():
        movimentos.setdefault(int(r["ano"]), {})[r["tipo"]] = r["total"]
    return {"por_ano": [por_ano[a] for a in sorted(por_ano)], "movimentos": movimentos}

# --------------------------------------------------------------- Usuario --


def _usuario_de_linha(row: Linha) -> Usuario:
    dados = dict(row)
    dados["admin"] = bool(dados["admin"])
    dados["ativo"] = bool(dados["ativo"])
    return Usuario(**dados)


def existe_algum_usuario(conn: Conexao) -> bool:
    return conn.execute("SELECT 1 FROM usuario LIMIT 1").fetchone() is not None


def listar_usuarios(conn: Conexao) -> list[Usuario]:
    rows = conn.execute("SELECT * FROM usuario ORDER BY nome").fetchall()
    return [_usuario_de_linha(r) for r in rows]


def buscar_usuario_por_login(conn: Conexao, login: str) -> Usuario | None:
    row = conn.execute("SELECT * FROM usuario WHERE login=%s", (login.strip().lower(),)).fetchone()
    return _usuario_de_linha(row) if row else None


def criar_usuario(
    conn: Conexao, nome: str, login: str, senha: str, admin: bool = False
) -> int:
    if buscar_usuario_por_login(conn, login) is not None:
        raise ValueError(f'Já existe um usuário com o login "{login}".')
    senha_hash, senha_salt = gerar_hash_senha(senha)
    cur = conn.execute(
        """INSERT INTO usuario (nome, login, senha_hash, senha_salt, admin, ativo, criado_em)
           VALUES (%s, %s, %s, %s, %s, 1, %s) RETURNING id""",
        (nome, login.strip().lower(), senha_hash, senha_salt, int(admin), dt.date.today().isoformat()),
    )
    novo_id = cur.fetchone()[0]
    _registrar_log(conn, "criar", "usuario", novo_id, f"{nome} ({login})")
    conn.commit()
    return novo_id


def autenticar(conn: Conexao, login: str, senha: str) -> Usuario | None:
    usuario = buscar_usuario_por_login(conn, login)
    if usuario is None or not usuario.ativo:
        return None
    if not senha_confere(senha, usuario.senha_hash, usuario.senha_salt):
        return None
    return usuario


def motivo_login_recusado(conn: Conexao, login: str) -> str:
    """Por que autenticar() recusou esse login, em palavras de quem vai
    corrigir. Uma mensagem só pra tudo ("login ou senha incorretos") fazia
    uma senha recém-redefinida parecer não ter funcionado, quando o que
    estava errado era o login digitado — ou a conta, desativada.

    Quem digita o NOME no lugar do login recebe o login certo: no escritório
    todo mundo se conhece, e é o engano mais comum de quem esqueceu a senha."""
    digitado = login.strip()
    usuario = buscar_usuario_por_login(conn, digitado)
    if usuario is not None:
        if not usuario.ativo:
            return "Este usuário está desativado. Peça a um administrador para reativá-lo."
        return "Senha incorreta."
    pelo_nome = [u for u in listar_usuarios(conn) if u.nome.strip().lower() == digitado.lower()]
    if len(pelo_nome) == 1:
        return f'"{digitado}" é o nome do usuário. Entre com o login: {pelo_nome[0].login}'
    return f'Não existe usuário com o login "{digitado}". Confira o login na aba Usuários, com um administrador.'


def atualizar_usuario(conn: Conexao, usuario_id: int, nome: str, login: str, admin: bool) -> None:
    existente = buscar_usuario_por_login(conn, login)
    if existente is not None and existente.id != usuario_id:
        raise ValueError(f'Já existe um usuário com o login "{login}".')
    conn.execute(
        "UPDATE usuario SET nome=%s, login=%s, admin=%s WHERE id=%s",
        (nome, login.strip().lower(), int(admin), usuario_id),
    )
    _registrar_log(conn, "atualizar", "usuario", usuario_id, f"{nome} ({login})")
    conn.commit()


def definir_ativo(conn: Conexao, usuario_id: int, ativo: bool) -> None:
    conn.execute("UPDATE usuario SET ativo=%s WHERE id=%s", (int(ativo), usuario_id))
    _registrar_log(conn, "ativar" if ativo else "desativar", "usuario", usuario_id, "")
    conn.commit()


def alterar_senha(conn: Conexao, usuario_id: int, nova_senha: str) -> None:
    senha_hash, senha_salt = gerar_hash_senha(nova_senha)
    conn.execute("UPDATE usuario SET senha_hash=%s, senha_salt=%s WHERE id=%s", (senha_hash, senha_salt, usuario_id))
    # Senha nova derruba os acessos sem senha: é o que se faz quando se
    # desconfia que alguém está usando a conta.
    conn.execute("DELETE FROM acesso_lembrado WHERE usuario_id=%s", (usuario_id,))
    _registrar_log(conn, "trocar_senha", "usuario", usuario_id, "")
    conn.commit()


# -------------------------------------------------------- AcessoLembrado --
#
# "Entrar sem pedir a senha neste computador". O PC guarda uma chave aleatória
# nas preferências locais; o banco guarda só o hash dela. A senha nunca sai
# da tela de login. Trocar a senha, desativar o usuário ou clicar em Sair
# invalida a chave.


def _hash_da_chave(chave: str) -> str:
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()


def criar_acesso_lembrado(conn: Conexao, usuario_id: int) -> str:
    chave = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO acesso_lembrado (usuario_id, chave_hash, criado_em) VALUES (%s, %s, %s)",
        (usuario_id, _hash_da_chave(chave), dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return chave


def usuario_do_acesso_lembrado(conn: Conexao, chave: str) -> Usuario | None:
    if not chave:
        return None
    row = conn.execute(
        "SELECT usuario_id FROM acesso_lembrado WHERE chave_hash=%s", (_hash_da_chave(chave),)
    ).fetchone()
    if row is None:
        return None
    usuario = next((u for u in listar_usuarios(conn) if u.id == row["usuario_id"]), None)
    if usuario is None or not usuario.ativo:
        return None
    conn.execute(
        "UPDATE acesso_lembrado SET ultimo_uso=%s WHERE chave_hash=%s",
        (dt.datetime.now().isoformat(timespec="seconds"), _hash_da_chave(chave)),
    )
    conn.commit()
    return usuario


def quantidade_acessos_lembrados(conn: Conexao, usuario_id: int) -> int:
    """Em quantos computadores este usuário entra sem digitar a senha."""
    return conn.execute(
        "SELECT count(*) AS n FROM acesso_lembrado WHERE usuario_id=%s", (usuario_id,)
    ).fetchone()["n"]


def encerrar_acessos_lembrados(conn: Conexao, usuario_id: int) -> None:
    """Todos os computadores voltam a pedir a senha deste usuário."""
    conn.execute("DELETE FROM acesso_lembrado WHERE usuario_id=%s", (usuario_id,))
    _registrar_log(conn, "encerrar_acessos", "usuario", usuario_id, "")
    conn.commit()


def esquecer_acesso_lembrado(conn: Conexao, chave: str) -> None:
    if not chave:
        return
    conn.execute("DELETE FROM acesso_lembrado WHERE chave_hash=%s", (_hash_da_chave(chave),))
    conn.commit()


# ---------------------------------------------------------- LogAtividade --


def _log_de_linha(row: Linha) -> LogAtividade:
    return LogAtividade(**dict(row))


def listar_log_atividade(
    conn: Conexao,
    data_de: str | None = None,
    data_ate: str | None = None,
    usuario_id: int | None = None,
    limite: int = 500,
) -> list[LogAtividade]:
    condicoes = []
    parametros: list = []
    if data_de:
        condicoes.append("left(data_hora, 10) >= %s")
        parametros.append(data_de)
    if data_ate:
        condicoes.append("left(data_hora, 10) <= %s")
        parametros.append(data_ate)
    if usuario_id is not None:
        condicoes.append("usuario_id = %s")
        parametros.append(usuario_id)

    sql = "SELECT * FROM log_atividade"
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY data_hora DESC, id DESC LIMIT %s"
    parametros.append(limite)

    rows = conn.execute(sql, parametros).fetchall()
    return [_log_de_linha(r) for r in rows]


# ------------------------------------------------- Informe de rendimentos --


def empresas_do_socio_no_ano(conn: Conexao, socio_id: int, ano_base: int) -> list[Empresa]:
    """Empresas que foram fonte pagadora desse sócio no ano — uma empresa por
    informe, porque cada uma emite o seu próprio comprovante com o seu CNPJ.

    Entra na lista quem teve vínculo em qualquer momento do ano (entrou em
    março ou saiu em agosto continua tendo informe daquele ano) e também quem
    já saiu mas ainda tem o que declarar naquele ano:

    * lucro deliberado depois da saída ainda é rendimento pago pela empresa;
    * empréstimo tomado antes da saída continua sendo saldo em 31/12 até ser
      quitado, e é o comprovante que dá ao sócio o número da ficha de Dívidas
      e Ônus Reais.

    Sem isso o informe sumiria justamente no ano em que o sócio precisa dele."""
    inicio, fim = f"{ano_base}-01-01", f"{ano_base}-12-31"
    rows = conn.execute(
        """SELECT DISTINCT e.* FROM empresa e
           WHERE e.id IN (
               SELECT empresa_id FROM vinculo_societario
               WHERE socio_id = %s AND data_entrada <= %s AND (data_saida IS NULL OR data_saida >= %s)
               UNION
               SELECT empresa_id FROM distribuicao_lucro WHERE socio_id = %s AND ano_base = %s
               UNION
               SELECT empresa_id FROM movimentacao
               WHERE socio_id = %s AND left(data, 4) = %s
               UNION
               SELECT empresa_id FROM movimentacao
               WHERE socio_id = %s AND tipo = 'emprestimo_empresa_para_socio' AND data <= %s
               UNION
               SELECT empresa_id FROM informe_rendimento WHERE socio_id = %s AND ano_base = %s
           )
           ORDER BY e.nome""",
        (
            socio_id, fim, inicio,
            socio_id, ano_base,
            socio_id, str(ano_base),
            socio_id, fim,
            socio_id, ano_base,
        ),
    ).fetchall()
    return [Empresa(**dict(r)) for r in rows]


def saldo_emprestimo_em(conn: Conexao, empresa_id: int, socio_id: int, ano_base: int) -> float:
    """Saldo acumulado dos empréstimos da empresa ao sócio até 31/12 do ano —
    é o número que vai pro Quadro 7, pro sócio declarar em Dívidas e Ônus
    Reais.

    Soma só o sentido empresa→sócio. O sentido oposto (sócio→empresa) é uma
    dívida da empresa, não um pagamento desta aqui: abater um do outro
    misturaria dois saldos que a declaração pede em fichas separadas. O
    sistema também não registra amortização, então isto é uma sugestão — a
    tela deixa corrigir antes de emitir."""
    row = conn.execute(
        """SELECT COALESCE(SUM(valor), 0) AS total FROM movimentacao
           WHERE empresa_id=%s AND socio_id=%s AND tipo='emprestimo_empresa_para_socio' AND data <= %s""",
        (empresa_id, socio_id, f"{ano_base}-12-31"),
    ).fetchone()
    return row["total"]


def buscar_informe(
    conn: Conexao, empresa_id: int, ano_base: int, socio_id: int
) -> InformeRendimento | None:
    row = conn.execute(
        "SELECT * FROM informe_rendimento WHERE empresa_id=%s AND ano_base=%s AND socio_id=%s",
        (empresa_id, ano_base, socio_id),
    ).fetchone()
    return InformeRendimento(**dict(row)) if row else None


def variacao_cotas_socio(
    conn: Conexao, empresa_id: int, socio_id: int, ano_base: int
) -> dict:
    """Quantas cotas o sócio tinha nessa empresa em 31/12 do ano anterior e em
    31/12 do ano-base, quanto vale cada cota, e a data em que ele saiu da
    sociedade — se saiu naquele ano.

    É o que o Quadro 7 do informe precisa pra dizer ao sócio o que lançar nas
    fichas de Bens e Direitos e de Dívidas e Ônus Reais. Como mudança de
    participação aqui fecha um vínculo e abre outro (ver
    atualizar_cotas_vinculo), comparar as duas datas é o que revela a venda
    ou a compra de cotas do ano, sem precisar percorrer alteração por
    alteração.

    A saída só é reconhecida quando o sócio terminou o ano fora da sociedade:
    quem apenas reduziu participação em agosto também tem um vínculo fechado
    naquela data, e chamar isso de saída faria o informe mandá-lo baixar uma
    participação que ele ainda tem."""
    inicio, fim = f"{ano_base - 1}-12-31", f"{ano_base}-12-31"

    def cotas_em(data: str) -> float:
        row = conn.execute(
            """SELECT COALESCE(SUM(quantidade_cotas), 0) AS total FROM vinculo_societario
               WHERE empresa_id=%s AND socio_id=%s AND data_entrada <= %s
                 AND (data_saida IS NULL OR data_saida > %s)""",
            (empresa_id, socio_id, data, data),
        ).fetchone()
        return row["total"] or 0.0

    cotas_inicio, cotas_fim = cotas_em(inicio), cotas_em(fim)

    # Valor nominal da cota = capital social / total de cotas da EMPRESA. Vale
    # o estado do fim do ano; só quando a empresa ainda não tinha cotas ali é
    # que o do início serve de retaguarda.
    estado = estado_empresa_no_periodo(conn, empresa_id, ano_base)
    if estado["cotas_fim"]:
        valor_nominal = estado["capital_fim"] / estado["cotas_fim"]
    elif estado["cotas_inicio"]:
        valor_nominal = estado["capital_inicio"] / estado["cotas_inicio"]
    else:
        valor_nominal = 0.0

    data_saida = None
    if not cotas_fim:
        row = conn.execute(
            """SELECT MAX(data_saida) AS data FROM vinculo_societario
               WHERE empresa_id=%s AND socio_id=%s AND data_saida IS NOT NULL
                 AND data_saida BETWEEN %s AND %s""",
            (empresa_id, socio_id, f"{ano_base}-01-01", fim),
        ).fetchone()
        data_saida = row["data"]

    return {
        "cotas_inicio": cotas_inicio,
        "cotas_fim": cotas_fim,
        "variacao": cotas_fim - cotas_inicio,
        "valor_nominal": valor_nominal,
        "data_saida": data_saida,
    }


def informe_sugerido(
    conn: Conexao, empresa_id: int, ano_base: int, socio_id: int
) -> InformeRendimento:
    """Monta o informe a partir do que o sistema já sabe, sem gravar nada:
    pró-labore e IRRF da distribuição do ano viram as linhas 1 e 5 do Quadro
    3, o valor distribuído vira a linha 5 do Quadro 4, e o saldo de
    empréstimo vira o Quadro 7 — junto com a saída da sociedade e a variação
    de cotas do ano, que saem do histórico de vínculos.

    O que o sistema não controla (INSS, 13º, pensão alimentícia, diárias) sai
    zerado e é preenchido na tela. É aqui — e só aqui — que os REAL do banco
    viram centavos."""
    distribuicao = conn.execute(
        "SELECT * FROM distribuicao_lucro WHERE empresa_id=%s AND ano_base=%s AND socio_id=%s",
        (empresa_id, ano_base, socio_id),
    ).fetchone()
    cotas = variacao_cotas_socio(conn, empresa_id, socio_id, ano_base)
    return InformeRendimento(
        id=None,
        empresa_id=empresa_id,
        socio_id=socio_id,
        ano_base=ano_base,
        q3_total_rendimentos=fiscal.reais_para_centavos(distribuicao["pro_labore"] if distribuicao else 0),
        q3_irrf=fiscal.reais_para_centavos(distribuicao["irrf"] if distribuicao else 0),
        q4_lucros_dividendos=fiscal.reais_para_centavos(
            distribuicao["valor_distribuido"] if distribuicao else 0
        ),
        emprestimo_saldo=fiscal.reais_para_centavos(
            saldo_emprestimo_em(conn, empresa_id, socio_id, ano_base)
        ),
        saida_sociedade_data=cotas["data_saida"] or "",
        cotas_inicio=cotas["cotas_inicio"],
        cotas_fim=cotas["cotas_fim"],
        cota_valor_nominal=fiscal.reais_para_centavos(cotas["valor_nominal"]),
    )


def carregar_informe(
    conn: Conexao, empresa_id: int, ano_base: int, socio_id: int
) -> tuple[InformeRendimento, bool]:
    """O informe já conferido e salvo, se existir; senão o sugerido a partir
    dos lançamentos. Devolve junto se veio do banco, pra tela poder avisar
    que está mostrando sugestão e não algo que alguém já conferiu."""
    salvo = buscar_informe(conn, empresa_id, ano_base, socio_id)
    if salvo is not None:
        return salvo, True
    return informe_sugerido(conn, empresa_id, ano_base, socio_id), False


def salvar_informe(conn: Conexao, informe: InformeRendimento) -> int:
    """Grava os valores conferidos — um registro por (empresa, ano, sócio),
    substituindo o anterior, porque é o informe vigente daquele ano.

    Não passa por _garantir_periodo_aberto: emitir informe é obrigação de
    abril, quando o período do ano anterior normalmente já está fechado."""
    negativos = [
        campo for campo in CAMPOS_VALOR_INFORME + ("emprestimo_saldo", "cota_valor_nominal")
        if int(getattr(informe, campo) or 0) < 0
    ]
    if negativos:
        raise ValueError("Os valores do informe não podem ser negativos.")
    if (informe.cotas_inicio or 0) < 0 or (informe.cotas_fim or 0) < 0:
        raise ValueError("A quantidade de cotas do informe não pode ser negativa.")
    if not (1996 <= informe.ano_base <= dt.date.today().year + 1):
        raise ValueError(
            f"Ano-calendário inválido: {informe.ano_base}. O informe existe pra anos a partir de 1996."
        )

    campos = CAMPOS_VALOR_INFORME + (
        "codigo_beneficiario",
        "natureza_rendimento",
        "emprestimo_saldo",
        *CAMPOS_COTAS_INFORME,
        "informacoes_complementares",
        "responsavel_nome",
    )
    valores = [getattr(informe, campo) for campo in campos]
    agora = dt.datetime.now().isoformat(timespec="seconds")
    socio = conn.execute("SELECT nome FROM socio WHERE id=%s", (informe.socio_id,)).fetchone()
    empresa = conn.execute("SELECT nome FROM empresa WHERE id=%s", (informe.empresa_id,)).fetchone()
    detalhes = (
        f"{socio['nome'] if socio else '?'} — {empresa['nome'] if empresa else '?'} — {informe.ano_base}"
    )

    existente = conn.execute(
        "SELECT id FROM informe_rendimento WHERE empresa_id=%s AND ano_base=%s AND socio_id=%s",
        (informe.empresa_id, informe.ano_base, informe.socio_id),
    ).fetchone()
    if existente is not None:
        atribuicoes = ", ".join(f"{campo}=%s" for campo in campos)
        conn.execute(
            f"UPDATE informe_rendimento SET {atribuicoes}, atualizado_em=%s WHERE id=%s",
            (*valores, agora, existente["id"]),
        )
        _registrar_log(conn, "atualizar", "informe_rendimento", existente["id"], detalhes)
        conn.commit()
        return existente["id"]

    colunas = ", ".join(("empresa_id", "socio_id", "ano_base", *campos, "atualizado_em"))
    marcadores = ", ".join(["%s"] * (len(campos) + 4))
    cur = conn.execute(
        f"INSERT INTO informe_rendimento ({colunas}) VALUES ({marcadores}) RETURNING id",
        (informe.empresa_id, informe.socio_id, informe.ano_base, *valores, agora),
    )
    novo_id = cur.fetchone()[0]
    _registrar_log(conn, "criar", "informe_rendimento", novo_id, detalhes)
    conn.commit()
    return novo_id


def registrar_emissao_informe(
    conn: Conexao, empresa_id: int, ano_base: int, socio_id: int, destino: str
) -> None:
    """Auditoria da emissão em si — o informe salvo diz o que foi declarado,
    o log diz quando saiu o papel e pra onde, que é o que se pergunta quando
    o sócio liga dizendo que não recebeu."""
    socio = conn.execute("SELECT nome FROM socio WHERE id=%s", (socio_id,)).fetchone()
    empresa = conn.execute("SELECT nome FROM empresa WHERE id=%s", (empresa_id,)).fetchone()
    _registrar_log(
        conn,
        "emitir",
        "informe_rendimento",
        None,
        f"{socio['nome'] if socio else '?'} — {empresa['nome'] if empresa else '?'} — "
        f"ano-calendário {ano_base} — {destino}",
    )
    conn.commit()


# ----------------------------------------------------- layouts de importação
def listar_layouts_importacao(conn: Conexao) -> list[LayoutImportacao]:
    linhas = conn.execute(
        "SELECT id, nome, linha_inicial, colunas_json FROM layout_importacao ORDER BY lower(nome)"
    ).fetchall()
    return [
        LayoutImportacao(
            id=linha["id"],
            nome=linha["nome"],
            linha_inicial=linha["linha_inicial"],
            colunas=de_json(linha["colunas_json"]),
        )
        for linha in linhas
    ]


def salvar_layout_importacao(conn: Conexao, layout: LayoutImportacao) -> int:
    """Grava o layout já validado. O nome é a identidade dele na tela, então
    dois com o mesmo nome seriam impossíveis de distinguir na lista."""
    garantir_valido(layout)
    nome = layout.nome.strip()
    colunas = para_json(limpar_colunas(layout.colunas))
    agora = dt.datetime.now().isoformat(timespec="seconds")

    repetido = conn.execute(
        "SELECT id FROM layout_importacao WHERE lower(nome) = lower(%s) AND id IS DISTINCT FROM %s",
        (nome, layout.id),
    ).fetchone()
    if repetido is not None:
        raise ValueError(f'Já existe um layout chamado "{nome}". Use outro nome.')

    if layout.id is None:
        cur = conn.execute(
            "INSERT INTO layout_importacao (nome, linha_inicial, colunas_json, criado_em, atualizado_em) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (nome, layout.linha_inicial, colunas, agora, agora),
        )
        novo_id = cur.fetchone()[0]
        _registrar_log(conn, "criar", "layout_importacao", novo_id, nome)
        conn.commit()
        return novo_id

    conn.execute(
        "UPDATE layout_importacao SET nome=%s, linha_inicial=%s, colunas_json=%s, atualizado_em=%s WHERE id=%s",
        (nome, layout.linha_inicial, colunas, agora, layout.id),
    )
    _registrar_log(conn, "atualizar", "layout_importacao", layout.id, nome)
    conn.commit()
    return layout.id


def excluir_layout_importacao(conn: Conexao, layout_id: int) -> None:
    linha = conn.execute("SELECT nome FROM layout_importacao WHERE id=%s", (layout_id,)).fetchone()
    if linha is None:
        return
    conn.execute("DELETE FROM layout_importacao WHERE id=%s", (layout_id,))
    _registrar_log(conn, "excluir", "layout_importacao", layout_id, linha["nome"])
    conn.commit()
