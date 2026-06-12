"""
Integracao com a API do DeepSeek (compativel com o padrao OpenAI).
Gera as porcoes (em gramas) de cada alimento para atingir uma meta de calorias.

A chave fica em st.secrets["deepseek"]["api_key"] (nunca no codigo).
"""
from __future__ import annotations

import json

import requests
import streamlit as st

_URL = "https://api.deepseek.com/chat/completions"
_MODELO = "deepseek-chat"

_SISTEMA = (
    "Voce e um nutricionista assistente. A partir de uma lista de alimentos e de "
    "uma meta de calorias, calcule a porcao (em gramas) de cada alimento para "
    "atingir, no total, aproximadamente a meta. Use valores nutricionais medios "
    "realistas. Responda SEMPRE e SOMENTE com um JSON valido, sem texto fora dele."
)

_FORMATO = (
    '{"itens":[{"alimento":"string","gramas":0,"calorias":0,'
    '"proteina_g":0,"carbo_g":0,"gordura_g":0}],'
    '"total_calorias":0,"observacao":"string"}'
)


def tem_chave() -> bool:
    try:
        return bool(st.secrets["deepseek"]["api_key"])
    except Exception:
        return False


def gerar_refeicao(alimentos: str, calorias: int, restricoes: str = "") -> dict:
    """Chama o DeepSeek e retorna o dict com itens/porcoes. Lanca em caso de erro."""
    chave = st.secrets["deepseek"]["api_key"]

    extra = f" Observacoes/restricoes: {restricoes}." if restricoes.strip() else ""
    prompt = (
        f"Monte uma refeicao de aproximadamente {calorias} kcal usando estes "
        f"alimentos: {alimentos}.{extra}\n"
        f"Distribua as porcoes de forma equilibrada e realista. "
        f"'gramas' e 'calorias' devem ser numeros (sem unidade no valor).\n"
        f"Retorne um JSON exatamente neste formato: {_FORMATO}"
    )

    payload = {
        "model": _MODELO,
        "messages": [
            {"role": "system", "content": _SISTEMA},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "stream": False,
    }
    resp = requests.post(
        _URL, json=payload, timeout=60,
        headers={"Authorization": f"Bearer {chave}",
                 "Content-Type": "application/json"},
    )
    resp.raise_for_status()
    conteudo = resp.json()["choices"][0]["message"]["content"]
    return json.loads(conteudo)
