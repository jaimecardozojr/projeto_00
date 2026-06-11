"""
Autenticacao simples e segura (senha com hash PBKDF2-SHA256 + salt por usuario).
Os usuarios ficam na aba/arquivo "usuarios". O perfil 'admin' e definido pela
lista de emails em st.secrets["auth"]["admin_emails"].
"""
from __future__ import annotations

import binascii
import hashlib
import os
import re
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
