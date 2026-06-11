"""
Autenticacao simples e segura (senha com hash PBKDF2-SHA256 + salt por usuario).
Os usuarios ficam na aba/arquivo "usuarios". O perfil 'admin' e definido pela
lista de emails em st.secrets["auth"]["admin_emails"].
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime

import streamlit as st

import storage as db

_ITERACOES = 200_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def admin_emails() -> list[str]:
    try:
        return [e.strip().lower() for e in st.secrets["auth"]["admin_emails"]]
    except Exception:
        return []


def is_admin(email: str) -> bool:
    return str(email).lower() in admin_emails()


def _hash(senha: str, salt_hex: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"),
                             bytes.fromhex(salt_hex), _ITERACOES)
    return binascii.hexlify(dk).decode()


def registrar(nome: str, email: str, senha: str) -> tuple[bool, str]:
    email = email.strip().lower()
    nome = nome.strip()
    if not nome:
        return False, "Informe seu nome."
    if not _EMAIL_RE.match(email):
        return False, "Email invalido."
    if len(senha) < 4:
        return False, "A senha deve ter ao menos 4 caracteres."
    if db.get_usuario(email):
        return False, "Ja existe uma conta com este email."

    salt = os.urandom(16).hex()
    db.criar_usuario({
        "email": email, "nome": nome, "senha_hash": _hash(senha, salt),
        "salt": salt, "perfil": "admin" if is_admin(email) else "usuario",
        "data_cadastro": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    return True, "Conta criada com sucesso! Agora e so entrar."


def autenticar(email: str, senha: str) -> dict | None:
    email = email.strip().lower()
    u = db.get_usuario(email)
    if not u:
        return None
    if not u.get("salt") or _hash(senha, u["salt"]) != u.get("senha_hash"):
        return None
    # honra a lista de admins do config mesmo que tenha mudado depois do cadastro
    u["perfil"] = "admin" if is_admin(email) else u.get("perfil", "usuario")
    return u


def redefinir_senha(email: str, nova_senha: str) -> tuple[bool, str]:
    """Admin define uma nova senha provisoria para um usuario."""
    email = email.strip().lower()
    if len(nova_senha) < 4:
        return False, "A nova senha deve ter ao menos 4 caracteres."
    if not db.get_usuario(email):
        return False, "Usuário não encontrado."
    salt = os.urandom(16).hex()
    db.atualizar_usuario(email, {"senha_hash": _hash(nova_senha, salt), "salt": salt})
    return True, "Senha redefinida! Informe a nova senha à pessoa."


def carregar_usuario(email: str) -> dict | None:
    """Recarrega os dados do usuario (usado no auto-login por cookie)."""
    u = db.get_usuario(email)
    if u:
        u["perfil"] = "admin" if is_admin(email) else u.get("perfil", "usuario")
    return u


# --------------------------------------------------------------------------
# Token assinado para "manter conectado" (cookie). Assinado com HMAC usando
# a chave privada do Google (segredo que o app ja possui) -> nao da pra forjar.
# --------------------------------------------------------------------------
def _cookie_secret() -> bytes:
    material = ""
    try:
        material = st.secrets["gcp_service_account"]["private_key"]
    except Exception:
        try:
            with open(db.SERVICE_ACCOUNT_FILE, encoding="utf-8") as f:
                material = json.load(f).get("private_key", "")
        except Exception:
            material = "fallback-local-dev"
    return hashlib.sha256(("acomp::" + material).encode()).digest()


def gerar_token(email: str, dias: int = 30) -> str:
    exp = int(time.time()) + dias * 86400
    payload = f"{email.lower()}|{exp}"
    sig = hmac.new(_cookie_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def validar_token(token: str) -> str | None:
    """Retorna o email se o token for valido e nao expirado; senao None."""
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        email, exp, sig = raw.rsplit("|", 2)
        if int(exp) < time.time():
            return None
        esperado = hmac.new(_cookie_secret(), f"{email}|{exp}".encode(),
                            hashlib.sha256).hexdigest()
        return email if hmac.compare_digest(esperado, sig) else None
    except Exception:
        return None
