"""Hash e verificação de senha — PBKDF2-HMAC-SHA256 com salt aleatório por
usuário, só com a biblioteca padrão do Python (sem dependência nova).

No fim do arquivo, os tokens do "continuar conectado": aleatórios, guardados
no banco só como hash, e sem nenhuma relação com a senha."""
from __future__ import annotations

import binascii
import hashlib
import hmac
import os
import secrets

ITERACOES = 200_000


def gerar_hash_senha(senha: str, salt_hex: str | None = None) -> tuple[str, str]:
    """Retorna (hash_hex, salt_hex). Se salt_hex não for informado, gera um
    novo salt aleatório — use isso ao criar/trocar senha."""
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, ITERACOES)
    return binascii.hexlify(hash_bytes).decode("ascii"), salt.hex()


def senha_confere(senha: str, hash_esperado: str, salt_hex: str) -> bool:
    hash_calculado, _ = gerar_hash_senha(senha, salt_hex)
    return hmac.compare_digest(hash_calculado, hash_esperado)


def gerar_token_sessao() -> tuple[str, str]:
    """(token, hash) para o "continuar conectado". Devolve o token só uma vez
    — ele vai pro arquivo de preferências da máquina; no banco fica apenas o
    hash, então nem quem lê o banco consegue reconstruir uma sessão."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    """SHA-256 simples, sem as 200 mil iterações do PBKDF2 usado em senha: o
    token tem 256 bits de aleatoriedade e não é adivinhável por força bruta,
    então esticar a derivação só atrasaria a abertura do programa."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_confere(token: str, hash_esperado: str) -> bool:
    return hmac.compare_digest(hash_token(token), hash_esperado)
