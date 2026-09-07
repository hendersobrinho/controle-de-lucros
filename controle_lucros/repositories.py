"""Operações de CRUD e consultas, uma função por caso de uso."""
from __future__ import annotations

import datetime as dt
import re
import sqlite3

from . import fiscal, sessao
from .auth import gerar_hash_senha, gerar_token_sessao, senha_confere, token_confere
from .models import (
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


def _registrar_log(conn: sqlite3.Connection, acao: str, entidade: str, entidade_id: int | None, detalhes: str) -> None:
    """Grava uma linha de auditoria com o usuário da sessão atual — chamado
    de dentro das próprias funções de gravação, na mesma transação."""
    usuario = sessao.usuario_atual()
    conn.execute(
        """INSERT INTO log_atividade (usuario_id, usuario_nome, data_hora, acao, entidade, entidade_id, detalhes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
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


def listar_empresas(conn: sqlite3.Connection) -> list[Empresa]:
    rows = conn.execute("SELECT * FROM empresa ORDER BY nome").fetchall()
    return [Empresa(**dict(r)) for r in rows]


def buscar_empresa(conn: sqlite3.Connection, empresa_id: int) -> Empresa | None:
    row = conn.execute("SELECT * FROM empresa WHERE id=?", (empresa_id,)).fetchone()
    return Empresa(**dict(row)) if row else None


def salvar_empresa(conn: sqlite3.Connection, e: Empresa) -> int:
    if e.id is None:
        cur = conn.execute(
            """INSERT INTO empresa (numero_chamada, nome, cnpj, capital_social, quantidade_cotas)
               VALUES (?, ?, ?, ?, ?)""",
            (e.numero_chamada, e.nome, e.cnpj, e.capital_social, e.quantidade_cotas),
        )
        _registrar_log(conn, "criar", "empresa", cur.lastrowid, f"{e.nome} (nº {e.numero_chamada})")
        conn.commit()
        return cur.lastrowid
    conn.execute(
        """UPDATE empresa SET numero_chamada=?, nome=?, cnpj=?, capital_social=?, quantidade_cotas=?
           WHERE id=?""",
        (e.numero_chamada, e.nome, e.cnpj, e.capital_social, e.quantidade_cotas, e.id),
    )
    _registrar_log(conn, "atualizar", "empresa", e.id, f"{e.nome} (nº {e.numero_chamada})")
    conn.commit()
    return e.id


def excluir_empresa(conn: sqlite3.Connection, empresa_id: int) -> None:
    empresa = buscar_empresa(conn, empresa_id)
    try:
        conn.execute("DELETE FROM empresa WHERE id=?", (empresa_id,))
    except sqlite3.IntegrityError:
        raise ValueError(
            "Não é possível excluir esta empresa: há sócios vinculados, alterações contratuais, "
            "distribuições ou movimentações registradas para ela. Remova-os primeiro."
        ) from None
    _registrar_log(conn, "excluir", "empresa", empresa_id, empresa.nome if empresa else "")
    conn.commit()


# ------------------------------------------------------------------ Socio --


def listar_socios(conn: sqlite3.Connection) -> list[Socio]:
    rows = conn.execute("SELECT * FROM socio ORDER BY nome").fetchall()
    return [Socio(**dict(r)) for r in rows]


def salvar_socio(conn: sqlite3.Connection, s: Socio) -> int:
    cpf_normalizado = normalizar_documento(s.cpf)
    if cpf_normalizado:
        outros = conn.execute("SELECT id, nome, cpf FROM socio WHERE id IS NOT ?", (s.id,)).fetchall()
        outro = next((o for o in outros if normalizar_documento(o["cpf"]) == cpf_normalizado), None)
        if outro is not None:
            raise ValueError(f'Já existe um sócio cadastrado com esse CPF/CNPJ: "{outro["nome"]}".')
    if s.id is None:
        cur = conn.execute(
            "INSERT INTO socio (nome, cpf, tipo_pessoa) VALUES (?, ?, ?)", (s.nome, s.cpf, s.tipo_pessoa)
        )
        _registrar_log(conn, "criar", "socio", cur.lastrowid, s.nome)
        conn.commit()
        return cur.lastrowid
    conn.execute("UPDATE socio SET nome=?, cpf=?, tipo_pessoa=? WHERE id=?", (s.nome, s.cpf, s.tipo_pessoa, s.id))
    _registrar_log(conn, "atualizar", "socio", s.id, s.nome)
    conn.commit()
    return s.id


def excluir_socio(conn: sqlite3.Connection, socio_id: int) -> None:
    socio = conn.execute("SELECT nome FROM socio WHERE id=?", (socio_id,)).fetchone()
    try:
        conn.execute("DELETE FROM socio WHERE id=?", (socio_id,))
    except sqlite3.IntegrityError:
        raise ValueError(
            "Não é possível excluir este sócio: há vínculos societários, distribuições ou movimentações "
            "registradas para ele. Remova-os primeiro."
        ) from None
    _registrar_log(conn, "excluir", "socio", socio_id, socio["nome"] if socio else "")
    conn.commit()


# ------------------------------------------------------- AlteracaoContratual --


def listar_alteracoes(conn: sqlite3.Connection, empresa_id: int) -> list[AlteracaoContratual]:
    rows = conn.execute(
        "SELECT * FROM alteracao_contratual WHERE empresa_id=? ORDER BY numero",
        (empresa_id,),
    ).fetchall()
    return [AlteracaoContratual(**{**dict(r), "fechada": bool(r["fechada"])}) for r in rows]


def buscar_alteracao(conn: sqlite3.Connection, alteracao_id: int) -> AlteracaoContratual | None:
    row = conn.execute(
        "SELECT * FROM alteracao_contratual WHERE id=?", (alteracao_id,)
    ).fetchone()
    if row is None:
        return None
    return AlteracaoContratual(**{**dict(row), "fechada": bool(row["fechada"])})


def proximo_numero_alteracao(conn: sqlite3.Connection, empresa_id: int) -> int:
    maior = conn.execute(
        "SELECT MAX(numero) AS m FROM alteracao_contratual WHERE empresa_id=?",
        (empresa_id,),
    ).fetchone()["m"]
    return (maior or 0) + 1


def estado_atual_empresa(conn: sqlite3.Connection, empresa_id: int) -> dict:
    """Snapshot vigente: da alteração contratual mais recente *por data*
    (não por número) — um registro retroativo (nº mais alto, mas com data
    efetiva anterior a uma alteração já existente) não pode virar o estado
    "atual" só por ter sido cadastrado depois. Mesmo critério de ordenação
    de estado_empresa_no_periodo, pra nunca divergirem sobre o que é o
    estado vigente da empresa. Sem nenhuma alteração ainda, usa a
    empresa-base."""
    ultima = conn.execute(
        """SELECT nome_empresa AS nome, capital_social, quantidade_cotas
           FROM alteracao_contratual WHERE empresa_id=? ORDER BY date(data) DESC, numero DESC LIMIT 1""",
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


def salvar_alteracao(conn: sqlite3.Connection, a: AlteracaoContratual) -> int:
    if a.id is not None:
        existente = buscar_alteracao(conn, a.id)
        if existente is not None and existente.fechada:
            raise ValueError("Esta alteração contratual está fechada. Destranque-a para editar.")
    _garantir_periodo_aberto(conn, a.empresa_id, a.data)
    if a.id is None:
        cur = conn.execute(
            """INSERT INTO alteracao_contratual
               (empresa_id, numero, data, nome_empresa, capital_social, quantidade_cotas, descricao, fechada)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (a.empresa_id, a.numero, a.data, a.nome_empresa, a.capital_social, a.quantidade_cotas, a.descricao),
        )
        _registrar_log(
            conn, "criar", "alteracao_contratual", cur.lastrowid, f"Nº {a.numero} — {a.nome_empresa} — {a.descricao}"
        )
        conn.commit()
        return cur.lastrowid
    conn.execute(
        """UPDATE alteracao_contratual SET data=?, nome_empresa=?, capital_social=?,
           quantidade_cotas=?, descricao=? WHERE id=?""",
        (a.data, a.nome_empresa, a.capital_social, a.quantidade_cotas, a.descricao, a.id),
    )
    _registrar_log(
        conn, "atualizar", "alteracao_contratual", a.id, f"Nº {a.numero} — {a.nome_empresa} — {a.descricao}"
    )
    conn.commit()
    return a.id


def fechar_alteracao(conn: sqlite3.Connection, alteracao_id: int) -> None:
    conn.execute("UPDATE alteracao_contratual SET fechada=1 WHERE id=?", (alteracao_id,))
    _registrar_log(conn, "fechar", "alteracao_contratual", alteracao_id, "")
    conn.commit()


def reabrir_alteracao(conn: sqlite3.Connection, alteracao_id: int) -> None:
    conn.execute("UPDATE alteracao_contratual SET fechada=0 WHERE id=?", (alteracao_id,))
    _registrar_log(conn, "reabrir", "alteracao_contratual", alteracao_id, "")
    conn.commit()


def excluir_alteracao(conn: sqlite3.Connection, alteracao_id: int) -> None:
    existente = buscar_alteracao(conn, alteracao_id)
    if existente is not None and existente.fechada:
        raise ValueError("Esta alteração contratual está fechada. Destranque-a para excluir.")
    if existente is not None:
        _garantir_periodo_aberto(conn, existente.empresa_id, existente.data)
    try:
        conn.execute("DELETE FROM alteracao_contratual WHERE id=?", (alteracao_id,))
    except sqlite3.IntegrityError:
        raise ValueError(
            "Não é possível excluir esta alteração contratual: há vínculos societários (entrada ou saída "
            "de sócio) registrados nela. Remova esses movimentos primeiro."
        ) from None
    _registrar_log(conn, "excluir", "alteracao_contratual", alteracao_id, f"Nº {existente.numero}" if existente else "")
    conn.commit()


# ------------------------------------------------------ Período de distribuição --


def periodo_esta_fechado(conn: sqlite3.Connection, empresa_id: int, ano_base: int) -> bool:
    row = conn.execute(
        "SELECT fechado FROM periodo_distribuicao WHERE empresa_id=? AND ano_base=?",
        (empresa_id, ano_base),
    ).fetchone()
    return bool(row["fechado"]) if row else False


def fechar_periodo(conn: sqlite3.Connection, empresa_id: int, ano_base: int) -> None:
    """Tranca todo dado ligado a esse ano/empresa — distribuição, pró-labore,
    IRRF, movimentações, e qualquer mudança de sócio ou cotas datada dentro
    do ano. Nada disso pode ser alterado enquanto o período não for
    destrancado de novo."""
    existente = conn.execute(
        "SELECT id FROM periodo_distribuicao WHERE empresa_id=? AND ano_base=?", (empresa_id, ano_base)
    ).fetchone()
    hoje = dt.date.today().isoformat()
    if existente is not None:
        conn.execute("UPDATE periodo_distribuicao SET fechado=1, fechado_em=? WHERE id=?", (hoje, existente["id"]))
    else:
        conn.execute(
            "INSERT INTO periodo_distribuicao (empresa_id, ano_base, fechado, fechado_em) VALUES (?, ?, 1, ?)",
            (empresa_id, ano_base, hoje),
        )
    _registrar_log(conn, "fechar", "periodo_distribuicao", empresa_id, f"Ano {ano_base}")
    conn.commit()


def reabrir_periodo(conn: sqlite3.Connection, empresa_id: int, ano_base: int) -> None:
    conn.execute(
        "UPDATE periodo_distribuicao SET fechado=0 WHERE empresa_id=? AND ano_base=?", (empresa_id, ano_base)
    )
    _registrar_log(conn, "reabrir", "periodo_distribuicao", empresa_id, f"Ano {ano_base}")
    conn.commit()


def _garantir_periodo_aberto(conn: sqlite3.Connection, empresa_id: int, data_ou_ano) -> None:
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


def listar_vinculos_empresa(conn: sqlite3.Connection, empresa_id: int) -> list[VinculoSocietario]:
    rows = conn.execute(
        "SELECT * FROM vinculo_societario WHERE empresa_id=? ORDER BY data_entrada",
        (empresa_id,),
    ).fetchall()
    return [VinculoSocietario(**dict(r)) for r in rows]


def vinculos_movimentados_na_alteracao(
    conn: sqlite3.Connection, alteracao_id: int
) -> list[VinculoSocietario]:
    """Vínculos que entraram e/ou saíram nesta alteração contratual específica."""
    rows = conn.execute(
        """SELECT * FROM vinculo_societario
           WHERE alteracao_entrada_id=? OR alteracao_saida_id=?""",
        (alteracao_id, alteracao_id),
    ).fetchall()
    return [VinculoSocietario(**dict(r)) for r in rows]


def _garantir_alteracao_editavel(conn: sqlite3.Connection, alteracao_id: int | None) -> None:
    if alteracao_id is None:
        return
    alteracao = buscar_alteracao(conn, alteracao_id)
    if alteracao is not None and alteracao.fechada:
        raise ValueError("A alteração contratual associada está fechada. Destranque-a para editar.")


def salvar_vinculo(conn: sqlite3.Connection, v: VinculoSocietario) -> int:
    if v.data_saida is not None and v.data_saida < v.data_entrada:
        raise ValueError("A data de saída não pode ser anterior à data de entrada.")
    _garantir_periodo_aberto(conn, v.empresa_id, v.data_entrada)
    if v.data_saida is not None:
        _garantir_periodo_aberto(conn, v.empresa_id, v.data_saida)
    _garantir_alteracao_editavel(conn, v.alteracao_entrada_id)
    _garantir_alteracao_editavel(conn, v.alteracao_saida_id)
    if v.id is None:
        cur = conn.execute(
            """INSERT INTO vinculo_societario
               (empresa_id, socio_id, percentual_capital, quantidade_cotas, data_entrada,
                data_saida, alteracao_entrada_id, alteracao_saida_id, observacao)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            ),
        )
        _registrar_log(conn, "criar", "vinculo_societario", cur.lastrowid, _descricao_vinculo(conn, v))
        conn.commit()
        return cur.lastrowid
    conn.execute(
        """UPDATE vinculo_societario SET empresa_id=?, socio_id=?, percentual_capital=?,
           quantidade_cotas=?, data_entrada=?, data_saida=?, alteracao_entrada_id=?,
           alteracao_saida_id=?, observacao=? WHERE id=?""",
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
            v.id,
        ),
    )
    _registrar_log(conn, "atualizar", "vinculo_societario", v.id, _descricao_vinculo(conn, v))
    conn.commit()
    return v.id


def _descricao_vinculo(conn: sqlite3.Connection, v: VinculoSocietario) -> str:
    socio = conn.execute("SELECT nome FROM socio WHERE id=?", (v.socio_id,)).fetchone()
    empresa = conn.execute("SELECT nome FROM empresa WHERE id=?", (v.empresa_id,)).fetchone()
    return f"{socio['nome'] if socio else '?'} em {empresa['nome'] if empresa else '?'} ({v.percentual_capital:.4f}%)"


def encerrar_vinculo(
    conn: sqlite3.Connection, vinculo_id: int, data_saida: str, alteracao_saida_id: int | None
) -> None:
    """Fecha o vínculo vigente (preenche data_saida) sem apagar histórico."""
    vinculo = buscar_vinculo(conn, vinculo_id)
    if vinculo is not None and data_saida < vinculo.data_entrada:
        raise ValueError("A data de saída não pode ser anterior à data de entrada.")
    if vinculo is not None:
        _garantir_periodo_aberto(conn, vinculo.empresa_id, data_saida)
    _garantir_alteracao_editavel(conn, alteracao_saida_id)
    conn.execute(
        "UPDATE vinculo_societario SET data_saida=?, alteracao_saida_id=? WHERE id=?",
        (data_saida, alteracao_saida_id, vinculo_id),
    )
    _registrar_log(conn, "encerrar", "vinculo_societario", vinculo_id, f"Saída em {data_saida}")
    conn.commit()


def excluir_vinculo(conn: sqlite3.Connection, vinculo_id: int) -> None:
    vinculo = buscar_vinculo(conn, vinculo_id)
    if vinculo is not None:
        _garantir_periodo_aberto(conn, vinculo.empresa_id, vinculo.data_entrada)
        if vinculo.data_saida is not None:
            _garantir_periodo_aberto(conn, vinculo.empresa_id, vinculo.data_saida)
        _garantir_alteracao_editavel(conn, vinculo.alteracao_entrada_id)
        _garantir_alteracao_editavel(conn, vinculo.alteracao_saida_id)
    conn.execute("DELETE FROM vinculo_societario WHERE id=?", (vinculo_id,))
    _registrar_log(conn, "excluir", "vinculo_societario", vinculo_id, "")
    conn.commit()


def listar_vinculos_socio(conn: sqlite3.Connection, socio_id: int) -> list[VinculoSocietario]:
    rows = conn.execute(
        "SELECT * FROM vinculo_societario WHERE socio_id=? ORDER BY data_entrada",
        (socio_id,),
    ).fetchall()
    return [VinculoSocietario(**dict(r)) for r in rows]


def valor_participacao(conn: sqlite3.Connection, vinculo: VinculoSocietario) -> float:
    """Valor atual da participação do sócio: cotas do vínculo × valor de cada
    cota hoje (capital social vigente da empresa / total de cotas vigente)."""
    estado = estado_atual_empresa(conn, vinculo.empresa_id)
    total_cotas = estado["quantidade_cotas"]
    if not total_cotas:
        return 0.0
    valor_por_cota = estado["capital_social"] / total_cotas
    return (vinculo.quantidade_cotas or 0) * valor_por_cota


def _abrir_alteracao_automatica(conn: sqlite3.Connection, empresa_id: int, data: str, descricao: str) -> int:
    """Cria uma alteração contratual já aberta, herdando nome/capital/cotas
    vigentes da empresa — usada quando o movimento de sócio é registrado pela
    aba de Sócios em vez de pela aba de Alterações contratuais."""
    estado = estado_atual_empresa(conn, empresa_id)
    numero = proximo_numero_alteracao(conn, empresa_id)
    return salvar_alteracao(
        conn,
        AlteracaoContratual(
            id=None,
            empresa_id=empresa_id,
            numero=numero,
            data=data,
            nome_empresa=estado["nome"],
            capital_social=estado["capital_social"],
            quantidade_cotas=estado["quantidade_cotas"],
            descricao=descricao,
        ),
    )


def associar_socio_a_empresa(
    conn: sqlite3.Connection,
    empresa_id: int,
    socio_id: int,
    percentual_capital: float,
    quantidade_cotas: float,
    data_entrada: str,
    descricao: str = "Inclusão de sócio (registrado pela aba de Sócios)",
) -> int:
    """Associa o sócio à empresa e registra automaticamente a alteração
    contratual correspondente, para que o histórico da empresa reflita o
    movimento feito por aqui."""
    _garantir_periodo_aberto(conn, empresa_id, data_entrada)
    alteracao_id = _abrir_alteracao_automatica(conn, empresa_id, data_entrada, descricao)
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
            alteracao_entrada_id=alteracao_id,
        ),
    )


def encerrar_vinculo_registrando_alteracao(
    conn: sqlite3.Connection,
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
    alteracao_id = _abrir_alteracao_automatica(conn, vinculo.empresa_id, data_saida, descricao)
    encerrar_vinculo(conn, vinculo.id, data_saida, alteracao_id)


def atualizar_cotas_vinculo(
    conn: sqlite3.Connection,
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
    alteracao_id = _abrir_alteracao_automatica(conn, vinculo.empresa_id, data, descricao)
    encerrar_vinculo(conn, vinculo.id, data, alteracao_id)
    return salvar_vinculo(
        conn,
        VinculoSocietario(
            id=None,
            empresa_id=vinculo.empresa_id,
            socio_id=vinculo.socio_id,
            percentual_capital=novo_percentual,
            quantidade_cotas=novas_cotas,
            data_entrada=data,
            data_saida=None,
            alteracao_entrada_id=alteracao_id,
        ),
    )


# ---------------------------------------------------------- DistribuicaoLucro --


def listar_distribuicoes(conn: sqlite3.Connection, empresa_id: int, ano_base: int) -> list[DistribuicaoLucro]:
    rows = conn.execute(
        "SELECT * FROM distribuicao_lucro WHERE empresa_id=? AND ano_base=?",
        (empresa_id, ano_base),
    ).fetchall()
    return [DistribuicaoLucro(**dict(r)) for r in rows]


def salvar_distribuicao(
    conn: sqlite3.Connection,
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
        "SELECT id FROM distribuicao_lucro WHERE empresa_id=? AND ano_base=? AND socio_id=?",
        (empresa_id, ano_base, socio_id),
    ).fetchone()
    socio = conn.execute("SELECT nome FROM socio WHERE id=?", (socio_id,)).fetchone()
    detalhes = (
        f"{socio['nome'] if socio else '?'} — {ano_base} — R$ {valor_distribuido:.2f}"
        f" (pró-labore R$ {pro_labore:.2f}, IRRF R$ {irrf:.2f})"
    )
    if existente is not None:
        conn.execute(
            "UPDATE distribuicao_lucro SET valor_distribuido=?, pro_labore=?, irrf=? WHERE id=?",
            (valor_distribuido, pro_labore, irrf, existente["id"]),
        )
        _registrar_log(conn, "atualizar", "distribuicao_lucro", existente["id"], detalhes)
        conn.commit()
        return existente["id"]
    cur = conn.execute(
        """INSERT INTO distribuicao_lucro (empresa_id, ano_base, socio_id, valor_distribuido, pro_labore, irrf)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (empresa_id, ano_base, socio_id, valor_distribuido, pro_labore, irrf),
    )
    _registrar_log(conn, "criar", "distribuicao_lucro", cur.lastrowid, detalhes)
    conn.commit()
    return cur.lastrowid


def total_distribuido_empresa_ano(conn: sqlite3.Connection, empresa_id: int, ano_base: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(valor_distribuido), 0) AS total FROM distribuicao_lucro WHERE empresa_id=? AND ano_base=?",
        (empresa_id, ano_base),
    ).fetchone()
    return row["total"]


def estado_empresa_no_periodo(conn: sqlite3.Connection, empresa_id: int, ano_base: int) -> dict:
    """Capital social e total de cotas vigentes no início e no fim do ano (a
    partir do histórico de alterações contratuais) — dá pra saber se houve
    aumento/redução de capital, ou mudança na quantidade de cotas, naquele
    ano especificamente."""

    def estado_ate(data_limite: str) -> tuple[float, float]:
        row = conn.execute(
            """SELECT capital_social, quantidade_cotas FROM alteracao_contratual
               WHERE empresa_id=? AND date(data) <= date(?)
               ORDER BY date(data) DESC, numero DESC LIMIT 1""",
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


def consistencia_cotas_socios(conn: sqlite3.Connection, empresa_id: int, ano_base: int) -> dict:
    """Compara o total de cotas da empresa no fim do ano contra a soma das
    cotas dos sócios ainda ativos nessa data. Se não bater, o capital/cotas
    da empresa mudou (por alteração contratual) mas ninguém redistribuiu as
    cotas entre os sócios — sinal de que a distribuição pode estar errada."""
    fim_ano = f"{ano_base}-12-31"
    estado = estado_empresa_no_periodo(conn, empresa_id, ano_base)

    row = conn.execute(
        """SELECT COALESCE(SUM(quantidade_cotas), 0) AS total FROM vinculo_societario
           WHERE empresa_id=? AND date(data_entrada) <= date(?)
             AND (data_saida IS NULL OR date(data_saida) > date(?))""",
        (empresa_id, fim_ano, fim_ano),
    ).fetchone()
    soma_socios = row["total"]

    return {
        "cotas_totais_empresa": estado["cotas_fim"],
        "soma_cotas_socios": soma_socios,
        "diferenca": estado["cotas_fim"] - soma_socios,
    }


def consistencia_percentual_socios(conn: sqlite3.Connection, empresa_id: int, ano_base: int) -> dict:
    """A soma dos percentuais de capital dos sócios ativos deveria fechar em
    100%. Se não fechar, tem sócio faltando, sobrando, ou percentual
    cadastrado errado — vale avisar antes de fechar a distribuição do ano."""
    fim_ano = f"{ano_base}-12-31"
    row = conn.execute(
        """SELECT COALESCE(SUM(percentual_capital), 0) AS total FROM vinculo_societario
           WHERE empresa_id=? AND date(data_entrada) <= date(?)
             AND (data_saida IS NULL OR date(data_saida) > date(?))""",
        (empresa_id, fim_ano, fim_ano),
    ).fetchone()
    soma_percentual = row["total"]

    return {
        "soma_percentual": soma_percentual,
        "diferenca": 100 - soma_percentual,
    }


def buscar_vinculo(conn: sqlite3.Connection, vinculo_id: int) -> VinculoSocietario | None:
    row = conn.execute("SELECT * FROM vinculo_societario WHERE id=?", (vinculo_id,)).fetchone()
    return VinculoSocietario(**dict(row)) if row else None


# -------------------------------------------------------------- Movimentacao --


def listar_movimentacoes(
    conn: sqlite3.Connection, empresa_id: int, socio_id: int, ano_base: int, tipo: str | None = None
) -> list[Movimentacao]:
    """tipo=None lista todos os 4 tipos juntos (empréstimo nos dois sentidos,
    adiantamento de lucro, devolução de capital) — pensado pra caber numa
    única tela de movimentações em vez de uma por tipo."""
    if tipo is None:
        rows = conn.execute(
            """SELECT * FROM movimentacao
               WHERE empresa_id=? AND socio_id=? AND strftime('%Y', data)=?
               ORDER BY data""",
            (empresa_id, socio_id, str(ano_base)),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM movimentacao
               WHERE empresa_id=? AND socio_id=? AND tipo=? AND strftime('%Y', data)=?
               ORDER BY data""",
            (empresa_id, socio_id, tipo, str(ano_base)),
        ).fetchall()
    return [Movimentacao(**dict(r)) for r in rows]


def soma_movimentacoes(
    conn: sqlite3.Connection, empresa_id: int, socio_id: int, ano_base: int, tipo: str
) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(valor), 0) AS total FROM movimentacao
           WHERE empresa_id=? AND socio_id=? AND tipo=? AND strftime('%Y', data)=?""",
        (empresa_id, socio_id, tipo, str(ano_base)),
    ).fetchone()
    return row["total"]


def salvar_movimentacao(conn: sqlite3.Connection, m: Movimentacao) -> int:
    _garantir_periodo_aberto(conn, m.empresa_id, m.data)
    socio = conn.execute("SELECT nome FROM socio WHERE id=?", (m.socio_id,)).fetchone()
    detalhes = f"{TIPOS_MOVIMENTACAO_LABEL.get(m.tipo, m.tipo)} — {socio['nome'] if socio else '?'} — R$ {m.valor:.2f} — {m.data}"
    if m.id is None:
        cur = conn.execute(
            "INSERT INTO movimentacao (empresa_id, socio_id, tipo, valor, data) VALUES (?, ?, ?, ?, ?)",
            (m.empresa_id, m.socio_id, m.tipo, m.valor, m.data),
        )
        _registrar_log(conn, "criar", "movimentacao", cur.lastrowid, detalhes)
        conn.commit()
        return cur.lastrowid
    conn.execute(
        "UPDATE movimentacao SET empresa_id=?, socio_id=?, tipo=?, valor=?, data=? WHERE id=?",
        (m.empresa_id, m.socio_id, m.tipo, m.valor, m.data, m.id),
    )
    _registrar_log(conn, "atualizar", "movimentacao", m.id, detalhes)
    conn.commit()
    return m.id


def excluir_movimentacao(conn: sqlite3.Connection, movimentacao_id: int) -> None:
    existente = conn.execute(
        "SELECT empresa_id, data FROM movimentacao WHERE id=?", (movimentacao_id,)
    ).fetchone()
    if existente is not None:
        _garantir_periodo_aberto(conn, existente["empresa_id"], existente["data"])
    conn.execute("DELETE FROM movimentacao WHERE id=?", (movimentacao_id,))
    _registrar_log(conn, "excluir", "movimentacao", movimentacao_id, "")
    conn.commit()


# --------------------------------------------------- Panorama de distribuição --


def _inicio_do_vinculo_continuo(todos: list[sqlite3.Row], vinculo_atual: sqlite3.Row) -> str:
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


def _saida_anterior_ao_vinculo_continuo(todos: list[sqlite3.Row], primeira_entrada: str) -> str | None:
    """Se o sócio já tinha saído de vez antes de reentrar (a passagem atual
    começou em primeira_entrada, sem ligação contígua com nada antes), acha
    a data dessa saída anterior — é o outro lado do mesmo evento de
    reentrada, senão a saída simplesmente some da visão anual quando o
    sócio volta a ficar ativo no mesmo período analisado."""
    anteriores = [v for v in todos if v["data_saida"] is not None and v["data_saida"] < primeira_entrada]
    if not anteriores:
        return None
    return max(anteriores, key=lambda v: v["data_saida"])["data_saida"]


def panorama_distribuicao_anual(conn: sqlite3.Connection, empresa_id: int, ano_base: int) -> list[dict]:
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

    socios_no_ano = conn.execute(
        """SELECT DISTINCT socio_id FROM vinculo_societario
           WHERE empresa_id=? AND date(data_entrada) <= date(?)
             AND (data_saida IS NULL OR date(data_saida) >= date(?))""",
        (empresa_id, fim, inicio),
    ).fetchall()

    distribuicoes = {d.socio_id: d for d in listar_distribuicoes(conn, empresa_id, ano_base)}
    total_distribuido = total_distribuido_empresa_ano(conn, empresa_id, ano_base)
    socios = {s.id: s for s in listar_socios(conn)}
    acumulado = acumulado_trimestral(conn, empresa_id, ano_base)

    linhas = []
    for row in socios_no_ano:
        socio_id = row["socio_id"]
        todos = conn.execute(
            "SELECT * FROM vinculo_societario WHERE empresa_id=? AND socio_id=? ORDER BY date(data_entrada)",
            (empresa_id, socio_id),
        ).fetchall()

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
        emprestimo = soma_movimentacoes(conn, empresa_id, socio_id, ano_base, "emprestimo_empresa_para_socio")

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
    conn: sqlite3.Connection, empresa_id: int, ano_base: int, trimestre: int | None = None
) -> list[DistribuicaoTrimestral]:
    """trimestre=None traz o ano inteiro — é assim que se soma o acumulado."""
    if trimestre is None:
        rows = conn.execute(
            """SELECT * FROM distribuicao_trimestral WHERE empresa_id=? AND ano_base=?
               ORDER BY trimestre""",
            (empresa_id, ano_base),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM distribuicao_trimestral WHERE empresa_id=? AND ano_base=? AND trimestre=?",
            (empresa_id, ano_base, trimestre),
        ).fetchall()
    return [DistribuicaoTrimestral(**dict(r)) for r in rows]


def trimestres_lancados(conn: sqlite3.Connection, empresa_id: int, ano_base: int) -> list[int]:
    """Quais trimestres do ano já têm algum lançamento — é o que diz se esta
    empresa usa controle trimestral e até onde o acumulado já foi."""
    rows = conn.execute(
        """SELECT DISTINCT trimestre FROM distribuicao_trimestral
           WHERE empresa_id=? AND ano_base=? ORDER BY trimestre""",
        (empresa_id, ano_base),
    ).fetchall()
    return [r["trimestre"] for r in rows]


def acumulado_trimestral(
    conn: sqlite3.Connection, empresa_id: int, ano_base: int, ate_trimestre: int | None = None
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
           WHERE empresa_id=? AND ano_base=? AND trimestre <= ?
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
    conn: sqlite3.Connection,
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
           WHERE empresa_id=? AND ano_base=? AND trimestre=? AND socio_id=?""",
        (empresa_id, ano_base, trimestre, socio_id),
    ).fetchone()
    socio = conn.execute("SELECT nome FROM socio WHERE id=?", (socio_id,)).fetchone()
    detalhes = (
        f"{socio['nome'] if socio else '?'} — {trimestre}º trimestre de {ano_base} — "
        f"R$ {valor_distribuido:.2f} (pró-labore R$ {pro_labore:.2f}, IRRF R$ {irrf:.2f})"
    )

    if existente is not None:
        conn.execute(
            """UPDATE distribuicao_trimestral SET valor_distribuido=?, pro_labore=?, irrf=?
               WHERE id=?""",
            (valor_distribuido, pro_labore, irrf, existente["id"]),
        )
        _registrar_log(conn, "atualizar", "distribuicao_trimestral", existente["id"], detalhes)
        registro_id = existente["id"]
    else:
        cur = conn.execute(
            """INSERT INTO distribuicao_trimestral
               (empresa_id, ano_base, trimestre, socio_id, valor_distribuido, pro_labore, irrf)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (empresa_id, ano_base, trimestre, socio_id, valor_distribuido, pro_labore, irrf),
        )
        _registrar_log(conn, "criar", "distribuicao_trimestral", cur.lastrowid, detalhes)
        registro_id = cur.lastrowid
    conn.commit()

    _refletir_trimestres_no_anual(conn, empresa_id, ano_base, socio_id)
    return registro_id


def excluir_distribuicao_trimestral(conn: sqlite3.Connection, registro_id: int) -> None:
    registro = conn.execute(
        "SELECT * FROM distribuicao_trimestral WHERE id=?", (registro_id,)
    ).fetchone()
    if registro is None:
        return
    _garantir_periodo_aberto(conn, registro["empresa_id"], registro["ano_base"])
    conn.execute("DELETE FROM distribuicao_trimestral WHERE id=?", (registro_id,))
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
    conn: sqlite3.Connection, empresa_id: int, ano_base: int, socio_id: int
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
    conn: sqlite3.Connection, empresa_id: int, ano_base: int, trimestre: int
) -> list[dict]:
    """Uma linha por sócio que esteve na sociedade em algum momento DAQUELE
    trimestre — quem saiu no 1º não aparece no 4º. Cada linha traz o que foi
    lançado no trimestre e o acumulado do ano até ele, que é o número que a
    distribuição anual está mostrando."""
    inicio, fim = periodo_trimestre(ano_base, trimestre)

    vinculos = conn.execute(
        """SELECT socio_id, percentual_capital, quantidade_cotas, data_entrada, data_saida
           FROM vinculo_societario
           WHERE empresa_id=? AND date(data_entrada) <= date(?)
             AND (data_saida IS NULL OR date(data_saida) >= date(?))
           ORDER BY date(data_entrada)""",
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
    conn: sqlite3.Connection, empresa_id: int, ano_base: int, trimestre: int
) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(valor_distribuido), 0) AS total FROM distribuicao_trimestral
           WHERE empresa_id=? AND ano_base=? AND trimestre=?""",
        (empresa_id, ano_base, trimestre),
    ).fetchone()
    return row["total"]


# ---------------------------------------------------- Importação em massa (cadastro) --


def preparar_importacao_cadastro(conn: sqlite3.Connection, linhas: list[dict]) -> dict:
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


def aplicar_importacao_cadastro(conn: sqlite3.Connection, linhas_resolvidas: list[dict]) -> dict:
    """Aplica linhas já resolvidas (empresa existente em "empresa_existente",
    ou dados pra criar uma nova; "socio_id" já definido, ou None quando a
    linha só cadastra a empresa): cria a empresa se
    for nova (reaproveitando entre linhas da mesma planilha), cria o vínculo
    só se o sócio ainda não tiver vínculo ativo com essa empresa — nunca
    duplica nem a empresa nem o vínculo. Se a linha trouxer "data_saida",
    encerra o vínculo (o recém-criado ou o que já existia). Se trouxer
    "ano_base" com valor distribuído, pró-labore ou IRRF, lança a
    distribuição daquele ano pra esse sócio."""
    empresas_criadas = 0
    vinculos_criados = 0
    vinculos_ja_existentes = 0
    vinculos_encerrados = 0
    distribuicoes_lancadas = 0
    cache_empresa_nova: dict[tuple[str, str], int] = {}

    for linha in linhas_resolvidas:
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

        vinculo_ativo = next(
            (
                v
                for v in listar_vinculos_empresa(conn, empresa_id)
                if v.socio_id == linha["socio_id"] and v.data_saida is None
            ),
            None,
        )

        if vinculo_ativo is None:
            novo_id = salvar_vinculo(
                conn,
                VinculoSocietario(
                    id=None,
                    empresa_id=empresa_id,
                    socio_id=linha["socio_id"],
                    percentual_capital=linha["percentual_capital"],
                    quantidade_cotas=linha["cotas_socio"] or None,
                    data_entrada=linha["data_entrada"],
                    data_saida=None,
                ),
            )
            vinculos_criados += 1
            vinculo_ativo = buscar_vinculo(conn, novo_id)
        else:
            vinculos_ja_existentes += 1

        if linha.get("data_saida"):
            encerrar_vinculo(conn, vinculo_ativo.id, linha["data_saida"], None)
            vinculos_encerrados += 1

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
            distribuicoes_lancadas += 1

    return {
        "empresas_criadas": empresas_criadas,
        "vinculos_criados": vinculos_criados,
        "vinculos_ja_existentes": vinculos_ja_existentes,
        "vinculos_encerrados": vinculos_encerrados,
        "distribuicoes_lancadas": distribuicoes_lancadas,
    }


# ---------------------------------------------------------- Análise / dashboard --

CLASSIFICACOES = ("proporcional", "desproporcional", "socio_sem_distribuicao", "empresa_sem_distribuicao")


def anos_disponiveis(conn: sqlite3.Connection) -> list[int]:
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
    conn: sqlite3.Connection, empresa_id: int, ano_base: int, tolerancia: float
) -> list[dict]:
    """panorama_distribuicao_anual + rótulo de classificação (proporcional /
    desproporcional / sócio sem distribuição / empresa sem distribuição)."""
    linhas = panorama_distribuicao_anual(conn, empresa_id, ano_base)
    total = total_distribuido_empresa_ano(conn, empresa_id, ano_base)
    return [{**linha, "ano_base": ano_base, "classificacao": _classificar_linha(linha, total, tolerancia)} for linha in linhas]


def analise_empresa_periodo(
    conn: sqlite3.Connection, empresa_id: int, ano_de: int, ano_ate: int, tolerancia: float
) -> list[dict]:
    """Linhas classificadas de uma empresa, ano a ano, num intervalo."""
    resultado = []
    for ano in range(ano_de, ano_ate + 1):
        resultado.extend(linhas_classificadas_empresa_ano(conn, empresa_id, ano, tolerancia))
    return resultado


def visao_geral(conn: sqlite3.Connection, ano_de: int, ano_ate: int, tolerancia: float) -> dict:
    """Panorama de todas as empresas no período: quanto foi distribuído
    proporcional/desproporcionalmente, quanto foi emprestado, e quais
    empresas não distribuíram nada no período."""
    empresas = listar_empresas(conn)
    linhas_todas: list[dict] = []
    resumo_empresas: list[dict] = []

    for empresa in empresas:
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


# --------------------------------------------------------------- Usuario --


def _usuario_de_linha(row: sqlite3.Row) -> Usuario:
    dados = dict(row)
    dados["admin"] = bool(dados["admin"])
    dados["ativo"] = bool(dados["ativo"])
    return Usuario(**dados)


def existe_algum_usuario(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM usuario LIMIT 1").fetchone() is not None


def listar_usuarios(conn: sqlite3.Connection) -> list[Usuario]:
    rows = conn.execute("SELECT * FROM usuario ORDER BY nome").fetchall()
    return [_usuario_de_linha(r) for r in rows]


def buscar_usuario_por_login(conn: sqlite3.Connection, login: str) -> Usuario | None:
    row = conn.execute("SELECT * FROM usuario WHERE login=?", (login.strip().lower(),)).fetchone()
    return _usuario_de_linha(row) if row else None


def criar_usuario(
    conn: sqlite3.Connection, nome: str, login: str, senha: str, admin: bool = False
) -> int:
    if buscar_usuario_por_login(conn, login) is not None:
        raise ValueError(f'Já existe um usuário com o login "{login}".')
    senha_hash, senha_salt = gerar_hash_senha(senha)
    cur = conn.execute(
        """INSERT INTO usuario (nome, login, senha_hash, senha_salt, admin, ativo, criado_em)
           VALUES (?, ?, ?, ?, ?, 1, ?)""",
        (nome, login.strip().lower(), senha_hash, senha_salt, int(admin), dt.date.today().isoformat()),
    )
    _registrar_log(conn, "criar", "usuario", cur.lastrowid, f"{nome} ({login})")
    conn.commit()
    return cur.lastrowid


def autenticar(conn: sqlite3.Connection, login: str, senha: str) -> Usuario | None:
    usuario = buscar_usuario_por_login(conn, login)
    if usuario is None or not usuario.ativo:
        return None
    if not senha_confere(senha, usuario.senha_hash, usuario.senha_salt):
        return None
    return usuario


def atualizar_usuario(conn: sqlite3.Connection, usuario_id: int, nome: str, login: str, admin: bool) -> None:
    existente = buscar_usuario_por_login(conn, login)
    if existente is not None and existente.id != usuario_id:
        raise ValueError(f'Já existe um usuário com o login "{login}".')
    conn.execute(
        "UPDATE usuario SET nome=?, login=?, admin=? WHERE id=?",
        (nome, login.strip().lower(), int(admin), usuario_id),
    )
    _registrar_log(conn, "atualizar", "usuario", usuario_id, f"{nome} ({login})")
    conn.commit()


def definir_ativo(conn: sqlite3.Connection, usuario_id: int, ativo: bool) -> None:
    conn.execute("UPDATE usuario SET ativo=? WHERE id=?", (int(ativo), usuario_id))
    if not ativo:
        # Desativar a conta tem que valer na hora; sem isto a pessoa
        # continuaria entrando pela sessão salva até ela vencer.
        conn.execute("DELETE FROM sessao_salva WHERE usuario_id=?", (usuario_id,))
    _registrar_log(conn, "ativar" if ativo else "desativar", "usuario", usuario_id, "")
    conn.commit()


def alterar_senha(conn: sqlite3.Connection, usuario_id: int, nova_senha: str) -> None:
    """Troca a senha e derruba a sessão salva: quem troca a senha
    normalmente está justamente tirando o acesso de alguém, e uma sessão
    "continuar conectado" sobrevivente anularia isso."""
    senha_hash, senha_salt = gerar_hash_senha(nova_senha)
    conn.execute("UPDATE usuario SET senha_hash=?, senha_salt=? WHERE id=?", (senha_hash, senha_salt, usuario_id))
    conn.execute("DELETE FROM sessao_salva WHERE usuario_id=?", (usuario_id,))
    _registrar_log(conn, "trocar_senha", "usuario", usuario_id, "")
    conn.commit()


# ---------------------------------------------------------- LogAtividade --


# ------------------------------------------------- Continuar conectado --

DIAS_SESSAO_SALVA = 30


def salvar_sessao(conn: sqlite3.Connection, usuario_id: int, dias: int = DIAS_SESSAO_SALVA) -> str:
    """Cria (ou substitui) a sessão salva do usuário e devolve o token, que é
    a única vez em que ele existe em texto — quem chamou tem que guardá-lo na
    máquina. Uma sessão por usuário: entrar de novo invalida a anterior."""
    token, token_hash = gerar_token_sessao()
    agora = dt.datetime.now()
    conn.execute("DELETE FROM sessao_salva WHERE usuario_id=?", (usuario_id,))
    conn.execute(
        "INSERT INTO sessao_salva (usuario_id, token_hash, criado_em, expira_em) VALUES (?, ?, ?, ?)",
        (
            usuario_id,
            token_hash,
            agora.isoformat(timespec="seconds"),
            (agora + dt.timedelta(days=dias)).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return token


def usuario_de_sessao_salva(conn: sqlite3.Connection, usuario_id: int, token: str) -> Usuario | None:
    """O usuário da sessão salva, se o token bater, não tiver vencido e a
    conta continuar ativa. Qualquer falha devolve None e apaga a sessão —
    token que não serve mais não tem por que continuar guardado."""
    row = conn.execute("SELECT * FROM sessao_salva WHERE usuario_id=?", (usuario_id,)).fetchone()
    if row is None:
        return None
    if not token_confere(token, row["token_hash"]) or row["expira_em"] < dt.datetime.now().isoformat():
        esquecer_sessao(conn, usuario_id)
        return None

    usuario_row = conn.execute("SELECT * FROM usuario WHERE id=? AND ativo=1", (usuario_id,)).fetchone()
    if usuario_row is None:
        esquecer_sessao(conn, usuario_id)
        return None
    return _usuario_de_linha(usuario_row)


def esquecer_sessao(conn: sqlite3.Connection, usuario_id: int) -> None:
    conn.execute("DELETE FROM sessao_salva WHERE usuario_id=?", (usuario_id,))
    conn.commit()


def _log_de_linha(row: sqlite3.Row) -> LogAtividade:
    return LogAtividade(**dict(row))


def listar_log_atividade(
    conn: sqlite3.Connection,
    data_de: str | None = None,
    data_ate: str | None = None,
    usuario_id: int | None = None,
    limite: int = 500,
) -> list[LogAtividade]:
    condicoes = []
    parametros: list = []
    if data_de:
        condicoes.append("date(data_hora) >= date(?)")
        parametros.append(data_de)
    if data_ate:
        condicoes.append("date(data_hora) <= date(?)")
        parametros.append(data_ate)
    if usuario_id is not None:
        condicoes.append("usuario_id = ?")
        parametros.append(usuario_id)

    sql = "SELECT * FROM log_atividade"
    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY data_hora DESC, id DESC LIMIT ?"
    parametros.append(limite)

    rows = conn.execute(sql, parametros).fetchall()
    return [_log_de_linha(r) for r in rows]


# ------------------------------------------------- Informe de rendimentos --


def empresas_do_socio_no_ano(conn: sqlite3.Connection, socio_id: int, ano_base: int) -> list[Empresa]:
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
               WHERE socio_id = ? AND data_entrada <= ? AND (data_saida IS NULL OR data_saida >= ?)
               UNION
               SELECT empresa_id FROM distribuicao_lucro WHERE socio_id = ? AND ano_base = ?
               UNION
               SELECT empresa_id FROM movimentacao
               WHERE socio_id = ? AND strftime('%Y', data) = ?
               UNION
               SELECT empresa_id FROM movimentacao
               WHERE socio_id = ? AND tipo = 'emprestimo_empresa_para_socio' AND data <= ?
               UNION
               SELECT empresa_id FROM informe_rendimento WHERE socio_id = ? AND ano_base = ?
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


def saldo_emprestimo_em(conn: sqlite3.Connection, empresa_id: int, socio_id: int, ano_base: int) -> float:
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
           WHERE empresa_id=? AND socio_id=? AND tipo='emprestimo_empresa_para_socio' AND data <= ?""",
        (empresa_id, socio_id, f"{ano_base}-12-31"),
    ).fetchone()
    return row["total"]


def buscar_informe(
    conn: sqlite3.Connection, empresa_id: int, ano_base: int, socio_id: int
) -> InformeRendimento | None:
    row = conn.execute(
        "SELECT * FROM informe_rendimento WHERE empresa_id=? AND ano_base=? AND socio_id=?",
        (empresa_id, ano_base, socio_id),
    ).fetchone()
    return InformeRendimento(**dict(row)) if row else None


def informe_sugerido(
    conn: sqlite3.Connection, empresa_id: int, ano_base: int, socio_id: int
) -> InformeRendimento:
    """Monta o informe a partir do que o sistema já sabe, sem gravar nada:
    pró-labore e IRRF da distribuição do ano viram as linhas 1 e 5 do Quadro
    3, o valor distribuído vira a linha 5 do Quadro 4, e o saldo de
    empréstimo vira o Quadro 7.

    O que o sistema não controla (INSS, 13º, pensão alimentícia, diárias) sai
    zerado e é preenchido na tela. É aqui — e só aqui — que os REAL do banco
    viram centavos."""
    distribuicao = conn.execute(
        "SELECT * FROM distribuicao_lucro WHERE empresa_id=? AND ano_base=? AND socio_id=?",
        (empresa_id, ano_base, socio_id),
    ).fetchone()
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
    )


def carregar_informe(
    conn: sqlite3.Connection, empresa_id: int, ano_base: int, socio_id: int
) -> tuple[InformeRendimento, bool]:
    """O informe já conferido e salvo, se existir; senão o sugerido a partir
    dos lançamentos. Devolve junto se veio do banco, pra tela poder avisar
    que está mostrando sugestão e não algo que alguém já conferiu."""
    salvo = buscar_informe(conn, empresa_id, ano_base, socio_id)
    if salvo is not None:
        return salvo, True
    return informe_sugerido(conn, empresa_id, ano_base, socio_id), False


def salvar_informe(conn: sqlite3.Connection, informe: InformeRendimento) -> int:
    """Grava os valores conferidos — um registro por (empresa, ano, sócio),
    substituindo o anterior, porque é o informe vigente daquele ano.

    Não passa por _garantir_periodo_aberto: emitir informe é obrigação de
    abril, quando o período do ano anterior normalmente já está fechado."""
    negativos = [
        campo for campo in CAMPOS_VALOR_INFORME + ("emprestimo_saldo",)
        if int(getattr(informe, campo) or 0) < 0
    ]
    if negativos:
        raise ValueError("Os valores do informe não podem ser negativos.")
    if not (1996 <= informe.ano_base <= dt.date.today().year + 1):
        raise ValueError(
            f"Ano-calendário inválido: {informe.ano_base}. O informe existe pra anos a partir de 1996."
        )

    campos = CAMPOS_VALOR_INFORME + (
        "codigo_beneficiario",
        "natureza_rendimento",
        "emprestimo_saldo",
        "informacoes_complementares",
        "responsavel_nome",
    )
    valores = [getattr(informe, campo) for campo in campos]
    agora = dt.datetime.now().isoformat(timespec="seconds")
    socio = conn.execute("SELECT nome FROM socio WHERE id=?", (informe.socio_id,)).fetchone()
    empresa = conn.execute("SELECT nome FROM empresa WHERE id=?", (informe.empresa_id,)).fetchone()
    detalhes = (
        f"{socio['nome'] if socio else '?'} — {empresa['nome'] if empresa else '?'} — {informe.ano_base}"
    )

    existente = conn.execute(
        "SELECT id FROM informe_rendimento WHERE empresa_id=? AND ano_base=? AND socio_id=?",
        (informe.empresa_id, informe.ano_base, informe.socio_id),
    ).fetchone()
    if existente is not None:
        atribuicoes = ", ".join(f"{campo}=?" for campo in campos)
        conn.execute(
            f"UPDATE informe_rendimento SET {atribuicoes}, atualizado_em=? WHERE id=?",
            (*valores, agora, existente["id"]),
        )
        _registrar_log(conn, "atualizar", "informe_rendimento", existente["id"], detalhes)
        conn.commit()
        return existente["id"]

    colunas = ", ".join(("empresa_id", "socio_id", "ano_base", *campos, "atualizado_em"))
    marcadores = ", ".join("?" * (len(campos) + 4))
    cur = conn.execute(
        f"INSERT INTO informe_rendimento ({colunas}) VALUES ({marcadores})",
        (informe.empresa_id, informe.socio_id, informe.ano_base, *valores, agora),
    )
    _registrar_log(conn, "criar", "informe_rendimento", cur.lastrowid, detalhes)
    conn.commit()
    return cur.lastrowid


def registrar_emissao_informe(
    conn: sqlite3.Connection, empresa_id: int, ano_base: int, socio_id: int, destino: str
) -> None:
    """Auditoria da emissão em si — o informe salvo diz o que foi declarado,
    o log diz quando saiu o papel e pra onde, que é o que se pergunta quando
    o sócio liga dizendo que não recebeu."""
    socio = conn.execute("SELECT nome FROM socio WHERE id=?", (socio_id,)).fetchone()
    empresa = conn.execute("SELECT nome FROM empresa WHERE id=?", (empresa_id,)).fetchone()
    _registrar_log(
        conn,
        "emitir",
        "informe_rendimento",
        None,
        f"{socio['nome'] if socio else '?'} — {empresa['nome'] if empresa else '?'} — "
        f"ano-calendário {ano_base} — {destino}",
    )
    conn.commit()
