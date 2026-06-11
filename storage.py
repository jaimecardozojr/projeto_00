"""
Camada de dados do app.

Funciona em dois modos, escolhidos automaticamente:
  - MODO NUVEM  -> se houver credenciais Google em st.secrets
                   (dados em Google Sheets, fotos em Google Drive)
  - MODO LOCAL  -> caso contrario (dados em CSV na pasta data/, fotos em data/fotos)

Toda a interface (app.py) usa apenas a funcao get_storage() e os metodos
publicos abaixo, sem saber qual modo esta ativo.
"""
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime

import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------
# Esquema das tabelas (colunas). Usado tanto no CSV quanto no Sheets.
# --------------------------------------------------------------------------
SCHEMAS = {
    "usuarios": [
        "email", "nome", "senha_hash", "salt", "perfil", "data_cadastro",
    ],
    "tarefas": [
        "id", "usuario_email", "categoria", "titulo", "descricao", "prazo",
        "status", "foto_ref", "data_criacao", "data_conclusao", "observacao",
    ],
    "metas": [
        "id", "usuario_email", "categoria", "titulo", "descricao", "valor_inicial",
        "valor_atual", "valor_alvo", "unidade", "prazo", "status", "data_criacao",
    ],
    "evolucao": [
        "id", "usuario_email", "data", "peso", "cintura", "quadril", "braco",
        "coxa", "peito", "observacao",
    ],
}


def _keycol(tabela: str) -> str:
    """Coluna-chave de cada tabela (sempre a primeira coluna)."""
    return SCHEMAS[tabela][0]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
FOTOS_DIR = os.path.join(DATA_DIR, "fotos")
# chave da conta de servico salva na raiz do projeto (alternativa ao secrets.toml)
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "service_account.json")

# No modo nuvem as fotos sao compactadas e guardadas (base64) nesta aba.
FOTOS_SHEET = "fotos"
FOTOS_COLS = ["id", "dados"]
# limite seguro por celula do Google Sheets (max real ~50000 caracteres)
MAX_CHARS_CELULA = 45000


def comprimir_imagem_b64(file_bytes: bytes, max_chars: int = MAX_CHARS_CELULA) -> str:
    """Reduz/comprime a imagem ate o base64 caber em uma celula do Sheets."""
    import base64
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(file_bytes))
    img = ImageOps.exif_transpose(img)  # corrige orientacao da camera
    if img.mode != "RGB":
        img = img.convert("RGB")

    b64 = ""
    for max_dim, qualidade in [(900, 72), (720, 62), (560, 55),
                               (440, 48), (340, 42), (260, 38), (200, 32)]:
        im = img.copy()
        im.thumbnail((max_dim, max_dim))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=qualidade, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        if len(b64) <= max_chars:
            break
    return b64


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ==========================================================================
# MODO LOCAL
# ==========================================================================
class LocalStorage:
    mode = "local"

    def __init__(self):
        os.makedirs(FOTOS_DIR, exist_ok=True)
        for nome, cols in SCHEMAS.items():
            caminho = self._path(nome)
            if not os.path.exists(caminho):
                pd.DataFrame(columns=cols).to_csv(caminho, index=False)

    def _path(self, tabela: str) -> str:
        return os.path.join(DATA_DIR, f"{tabela}.csv")

    def read(self, tabela: str) -> pd.DataFrame:
        df = pd.read_csv(self._path(tabela), dtype=str).fillna("")
        # garante todas as colunas mesmo que o CSV seja antigo
        for c in SCHEMAS[tabela]:
            if c not in df.columns:
                df[c] = ""
        return df[SCHEMAS[tabela]]

    def _write(self, tabela: str, df: pd.DataFrame):
        df.to_csv(self._path(tabela), index=False)

    def append(self, tabela: str, linha: dict):
        df = self.read(tabela)
        df = pd.concat([df, pd.DataFrame([linha])], ignore_index=True)
        self._write(tabela, df)

    def update(self, tabela: str, id_: str, campos: dict):
        df = self.read(tabela)
        mask = df[_keycol(tabela)] == id_
        for k, v in campos.items():
            df.loc[mask, k] = v
        self._write(tabela, df)

    def delete(self, tabela: str, id_: str):
        df = self.read(tabela)
        df = df[df[_keycol(tabela)] != id_]
        self._write(tabela, df)

    # ---- fotos ----
    def salvar_foto(self, file_bytes: bytes, nome_arquivo: str) -> str:
        ref = f"{_new_id()}_{nome_arquivo}"
        with open(os.path.join(FOTOS_DIR, ref), "wb") as f:
            f.write(file_bytes)
        return ref

    def ler_foto(self, ref: str) -> bytes | None:
        if not ref:
            return None
        caminho = os.path.join(FOTOS_DIR, ref)
        if not os.path.exists(caminho):
            return None
        with open(caminho, "rb") as f:
            return f.read()


# ==========================================================================
# MODO NUVEM (Google Sheets + Drive)
# ==========================================================================
class GoogleStorage:
    mode = "nuvem"

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(self):
        import gspread
        from google.oauth2.service_account import Credentials

        # 1) credenciais: do secrets.toml (deploy) OU do arquivo json (local)
        if _tem_credencial_secrets():
            info = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(info, scopes=self.SCOPES)
        elif os.path.exists(SERVICE_ACCOUNT_FILE):
            creds = Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=self.SCOPES)
        else:
            raise RuntimeError("Credenciais Google nao encontradas.")

        # 2) ID da planilha (do secrets.toml)
        sheet_id, _ = _google_ids()

        self._gc = gspread.authorize(creds)
        self._sh = self._gc.open_by_key(sheet_id)

        # garante que cada aba (incluindo "fotos") existe com o cabecalho certo
        todas = dict(SCHEMAS)
        todas[FOTOS_SHEET] = FOTOS_COLS
        existentes = {ws.title for ws in self._sh.worksheets()}
        for nome, cols in todas.items():
            if nome not in existentes:
                ws = self._sh.add_worksheet(title=nome, rows=200, cols=len(cols))
                ws.append_row(cols)
            else:
                ws = self._sh.worksheet(nome)
                if ws.row_values(1) != cols:
                    ws.update([cols], "A1")

    def _ws(self, tabela: str):
        return self._sh.worksheet(tabela)

    def read(self, tabela: str) -> pd.DataFrame:
        registros = self._ws(tabela).get_all_records()
        df = pd.DataFrame(registros)
        if df.empty:
            df = pd.DataFrame(columns=SCHEMAS[tabela])
        for c in SCHEMAS[tabela]:
            if c not in df.columns:
                df[c] = ""
        return df[SCHEMAS[tabela]].astype(str).replace("nan", "")

    def append(self, tabela: str, linha: dict):
        cols = SCHEMAS[tabela]
        self._ws(tabela).append_row([str(linha.get(c, "")) for c in cols],
                                    value_input_option="USER_ENTERED")

    def _row_index(self, tabela: str, id_: str) -> int | None:
        ids = self._ws(tabela).col_values(1)  # coluna "id"
        for i, v in enumerate(ids):
            if v == id_:
                return i + 1  # 1-based; linha 1 = cabecalho
        return None

    def update(self, tabela: str, id_: str, campos: dict):
        ws = self._ws(tabela)
        linha = self._row_index(tabela, id_)
        if not linha:
            return
        cols = SCHEMAS[tabela]
        for k, v in campos.items():
            if k in cols:
                ws.update_cell(linha, cols.index(k) + 1, str(v))

    def delete(self, tabela: str, id_: str):
        linha = self._row_index(tabela, id_)
        if linha:
            self._ws(tabela).delete_rows(linha)

    # ---- fotos (compactadas em base64 na aba "fotos") ----
    def salvar_foto(self, file_bytes: bytes, nome_arquivo: str) -> str:
        ref = _new_id()
        b64 = comprimir_imagem_b64(file_bytes)
        self._sh.worksheet(FOTOS_SHEET).append_row(
            [ref, b64], value_input_option="RAW")
        return ref

    def ler_foto(self, ref: str) -> bytes | None:
        if not ref:
            return None
        try:
            import base64
            ws = self._sh.worksheet(FOTOS_SHEET)
            ids = ws.col_values(1)  # coluna "id"
            for i, v in enumerate(ids):
                if v == ref:
                    b64 = ws.cell(i + 1, 2).value
                    return base64.b64decode(b64) if b64 else None
        except Exception:
            return None
        return None


# ==========================================================================
# Fabrica unica (cacheada) + API de alto nivel usada pelo app
# ==========================================================================
def _secret(secao: str, chave: str):
    """Le st.secrets[secao][chave] sem quebrar se nao existir."""
    try:
        return st.secrets[secao][chave]
    except Exception:
        return None


def _google_ids():
    """Retorna (sheet_id, drive_folder_id) vindos do secrets.toml."""
    return _secret("google", "sheet_id"), _secret("google", "drive_folder_id")


def _tem_credencial_secrets() -> bool:
    try:
        return "gcp_service_account" in st.secrets
    except Exception:
        return False


def _google_configurado() -> bool:
    tem_credencial = _tem_credencial_secrets() or os.path.exists(SERVICE_ACCOUNT_FILE)
    sheet_id, _ = _google_ids()
    return bool(tem_credencial and sheet_id)


@st.cache_resource(show_spinner="Conectando ao banco de dados...")
def get_storage():
    try:
        if _google_configurado():
            return GoogleStorage()
    except Exception as e:  # cai para local se algo falhar
        st.warning(f"Nao foi possivel conectar ao Google ({e}). Usando modo local.")
    return LocalStorage()


# ---------- Usuarios ----------
def listar_usuarios() -> pd.DataFrame:
    return get_storage().read("usuarios")


def get_usuario(email: str) -> dict | None:
    df = get_storage().read("usuarios")
    if df.empty:
        return None
    m = df[df["email"].str.lower() == str(email).lower()]
    return m.iloc[0].to_dict() if not m.empty else None


def criar_usuario(linha: dict):
    get_storage().append("usuarios", linha)


def atualizar_usuario(email: str, campos: dict):
    get_storage().update("usuarios", email, campos)


# ---------- Tarefas ----------
def listar_tarefas(usuario_email: str, categoria: str | None = None) -> pd.DataFrame:
    df = get_storage().read("tarefas")
    if not df.empty:
        df = df[df["usuario_email"] == usuario_email]
    if categoria:
        df = df[df["categoria"] == categoria]
    return df


def listar_todas_tarefas() -> pd.DataFrame:
    return get_storage().read("tarefas")


def criar_tarefa(usuario_email, categoria, titulo, descricao, prazo):
    get_storage().append("tarefas", {
        "id": _new_id(), "usuario_email": usuario_email, "categoria": categoria,
        "titulo": titulo, "descricao": descricao, "prazo": prazo,
        "status": "Pendente", "foto_ref": "", "data_criacao": _now(),
        "data_conclusao": "", "observacao": "",
    })


def concluir_tarefa(id_, foto_bytes, nome_arquivo, observacao):
    s = get_storage()
    ref = s.salvar_foto(foto_bytes, nome_arquivo) if foto_bytes else ""
    s.update("tarefas", id_, {
        "status": "Concluida", "foto_ref": ref,
        "data_conclusao": _now(), "observacao": observacao,
    })


def reabrir_tarefa(id_):
    get_storage().update("tarefas", id_, {
        "status": "Pendente", "data_conclusao": "",
    })


def excluir_tarefa(id_):
    get_storage().delete("tarefas", id_)


# ---------- Metas ----------
def listar_metas(usuario_email: str) -> pd.DataFrame:
    df = get_storage().read("metas")
    if not df.empty:
        df = df[df["usuario_email"] == usuario_email]
    return df


def criar_meta(usuario_email, categoria, titulo, descricao, valor_inicial,
               valor_alvo, unidade, prazo):
    get_storage().append("metas", {
        "id": _new_id(), "usuario_email": usuario_email, "categoria": categoria,
        "titulo": titulo, "descricao": descricao, "valor_inicial": valor_inicial,
        "valor_atual": valor_inicial, "valor_alvo": valor_alvo,
        "unidade": unidade, "prazo": prazo, "status": "Em andamento",
        "data_criacao": _now(),
    })


def atualizar_meta(id_, valor_atual, status):
    get_storage().update("metas", id_, {"valor_atual": valor_atual, "status": status})


def excluir_meta(id_):
    get_storage().delete("metas", id_)


# ---------- Evolucao ----------
def listar_evolucao(usuario_email: str) -> pd.DataFrame:
    df = get_storage().read("evolucao")
    if not df.empty:
        df = df[df["usuario_email"] == usuario_email]
        df = df.sort_values("data")
    return df


def registrar_evolucao(usuario_email, data, peso, cintura, quadril, braco,
                       coxa, peito, observacao):
    get_storage().append("evolucao", {
        "id": _new_id(), "usuario_email": usuario_email, "data": data,
        "peso": peso, "cintura": cintura, "quadril": quadril, "braco": braco,
        "coxa": coxa, "peito": peito, "observacao": observacao,
    })


def excluir_evolucao(id_):
    get_storage().delete("evolucao", id_)


def ler_foto(ref: str) -> bytes | None:
    return get_storage().ler_foto(ref)
