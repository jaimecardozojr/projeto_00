"""
App de Acompanhamento (multiusuario) - Tarefas, Metas e Evolucao
Login com perfis: ADMIN (gerencia todos) e USUARIO (cumpre as proprias tarefas).
Rode com:  python -m streamlit run app.py
"""
from datetime import date, datetime, timedelta

import extra_streamlit_components as stx
import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_option_menu import option_menu

import auth
import ia
import storage as db

COOKIE = "acomp_token"

# --------------------------------------------------------------------------
# Configuracao da pagina + estilo
# --------------------------------------------------------------------------
st.set_page_config(page_title="Meu Acompanhamento", page_icon="💪",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .block-container {padding-top: 2rem; padding-bottom: 3rem;}
    .card {
        background: #1e293b; border: 1px solid #334155; border-radius: 16px;
        padding: 18px 20px; margin-bottom: 14px;
    }
    .card-pendente {border-left: 6px solid #f59e0b;}
    .card-ok       {border-left: 6px solid #22c55e;}
    .card h4 {margin: 0 0 6px 0; font-size: 1.05rem;}
    .card p  {margin: 2px 0; color: #94a3b8; font-size: 0.88rem;}
    .badge {display:inline-block; padding:3px 10px; border-radius:999px;
            font-size:0.72rem; font-weight:600;}
    .b-pend {background:#78350f; color:#fcd34d;}
    .b-ok   {background:#14532d; color:#86efac;}
    .hero {background: linear-gradient(135deg,#16a34a 0%,#0ea5e9 100%);
           border-radius: 20px; padding: 28px 32px; margin-bottom: 22px; color:white;}
    .hero h1 {margin:0; font-size:1.9rem;}
    .hero p  {margin:6px 0 0 0; opacity:.92;}
    .stButton>button {border-radius: 10px; font-weight:600;}
    div[data-testid="stMetric"] {background:#1e293b; border:1px solid #334155;
            border-radius:14px; padding:14px 16px;}
</style>
""", unsafe_allow_html=True)

# Gerenciador de cookie criado no TOPO para o componente montar cedo e
# conseguir ler o cookie logo no carregamento da pagina.
cookie_mgr = stx.CookieManager(key="cookie_mgr")


def chip_status(status: str) -> str:
    if status == "Concluida":
        return '<span class="badge b-ok">✅ Concluída</span>'
    return '<span class="badge b-pend">⏳ Pendente</span>'


def num(v, padrao=0.0):
    try:
        return float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return padrao


def _streak(datas_iso: set) -> int:
    """Dias consecutivos (terminando hoje ou ontem) com ao menos 1 tarefa concluida."""
    hoje = date.today()
    inicio = hoje if hoje.isoformat() in datas_iso else hoje - timedelta(days=1)
    if inicio.isoformat() not in datas_iso:
        return 0
    n, d = 0, inicio
    while d.isoformat() in datas_iso:
        n += 1
        d -= timedelta(days=1)
    return n


def garantir_recorrentes(email):
    """Gera as tarefas recorrentes de hoje uma vez por sessao/dia (evita reler a planilha)."""
    chave = f"gen_{email}_{date.today().isoformat()}"
    if not st.session_state.get(chave):
        try:
            db.gerar_recorrentes_do_dia(email)
        except Exception:
            pass  # nunca derruba a pagina por causa da geracao
        st.session_state[chave] = True


DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def stats_tarefas(df) -> dict:
    total = len(df)
    ok = int((df["status"] == "Concluida").sum()) if total else 0
    adesao = round(100 * ok / total) if total else 0
    datas = set()
    if total:
        for v in df[df["status"] == "Concluida"]["data_conclusao"]:
            v = str(v)
            if len(v) >= 10:
                datas.add(v[:10])
    return {"total": total, "ok": ok, "pend": total - ok,
            "adesao": adesao, "streak": _streak(datas)}


# ==========================================================================
# TELA DE LOGIN / CADASTRO
# ==========================================================================
def tela_login():
    st.markdown("""
    <div class="hero">
        <h1>💪 Meu Acompanhamento</h1>
        <p>Entre com sua conta ou cadastre-se para começar.</p>
    </div>""", unsafe_allow_html=True)

    _, meio, _ = st.columns([1, 2, 1])
    with meio:
        aba_entrar, aba_cadastrar = st.tabs(["🔑 Entrar", "📝 Cadastrar"])

        with aba_entrar:
            with st.form("login"):
                email = st.text_input("Email")
                senha = st.text_input("Senha", type="password")
                manter = st.checkbox("Manter conectado neste dispositivo", value=True)
                ok = st.form_submit_button("Entrar", width='stretch')
            if ok:
                user = auth.autenticar(email, senha)
                if user:
                    st.session_state["user"] = user
                    if manter:
                        # grava o cookie e PARA o run; o proprio componente de
                        # cookie dispara o rerun depois de gravar no navegador
                        # (chamar st.rerun() aqui cancelaria a gravacao).
                        cookie_mgr.set(COOKIE, auth.gerar_token(user["email"]),
                                       expires_at=datetime.now() + timedelta(days=30))
                        st.success("Entrando...")
                        st.stop()
                    st.rerun()
                else:
                    st.error("Email ou senha incorretos.")

        with aba_cadastrar:
            st.caption("Crie sua conta com o seu email. É rápido!")
            with st.form("cadastro", clear_on_submit=False):
                nome = st.text_input("Seu nome")
                email_c = st.text_input("Email", key="email_cad")
                senha_c = st.text_input("Senha", type="password", key="senha_cad")
                senha_c2 = st.text_input("Confirme a senha", type="password")
                ok_c = st.form_submit_button("Criar conta", width='stretch')
            if ok_c:
                if senha_c != senha_c2:
                    st.error("As senhas não conferem.")
                else:
                    sucesso, msg = auth.registrar(nome, email_c, senha_c)
                    (st.success if sucesso else st.error)(msg)


# ==========================================================================
# PAGINA GENERICA DE TAREFAS
# ==========================================================================
def _bloco_recorrentes(categoria, dica, email_alvo):
    """Painel (admin) para criar/gerenciar tarefas que se repetem sozinhas."""
    with st.expander("🔁 Tarefas recorrentes (repetem sozinhas)"):
        st.caption("Crie um modelo e o app gera a tarefa automaticamente nos dias escolhidos.")
        with st.form(f"rec_{categoria}", clear_on_submit=True):
            titulo = st.text_input("Título *", placeholder=dica, key=f"rt_{categoria}")
            descricao = st.text_area("Descrição / instruções", key=f"rd_{categoria}")
            freq = st.radio("Frequência", ["Diária", "Dias da semana"],
                            horizontal=True, key=f"rf_{categoria}")
            dias_sel = st.multiselect("Dias da semana (se escolher 'Dias da semana')",
                                      DIAS_SEMANA, key=f"rds_{categoria}")
            criar = st.form_submit_button("➕ Criar recorrente", width='stretch')
        if criar:
            if not titulo.strip():
                st.error("Dê um título.")
            elif freq == "Dias da semana" and not dias_sel:
                st.error("Escolha ao menos um dia da semana.")
            else:
                frequencia = "Diária" if freq == "Diária" else "Semanal"
                idxs = (",".join(str(DIAS_SEMANA.index(d)) for d in dias_sel)
                        if frequencia == "Semanal" else "")
                db.criar_recorrente(email_alvo, categoria, titulo.strip(),
                                    descricao.strip(), frequencia, idxs)
                st.success("Recorrente criada! A tarefa de hoje já foi gerada (se for o dia).")
                st.rerun()

        recs = db.listar_recorrentes(email_alvo, categoria)
        if recs.empty:
            st.caption("Nenhuma tarefa recorrente nesta categoria.")
        else:
            st.markdown("**Ativas:**")
            for _, r in recs.iterrows():
                if r["frequencia"] == "Diária":
                    quando = "Todo dia"
                else:
                    quando = "Toda " + ", ".join(
                        DIAS_SEMANA[int(i)] for i in str(r["dias_semana"]).split(",") if i != "")
                cols = st.columns([6, 1])
                cols[0].markdown(f"🔁 **{r['titulo']}** — {quando}")
                if cols[1].button("🗑️", key=f"delrec_{r['id']}"):
                    db.excluir_recorrente(r["id"])
                    st.rerun()


def pagina_tarefas(categoria, emoji, dica, email_alvo, modo_admin):
    st.markdown(f"## {emoji} {categoria}")
    garantir_recorrentes(email_alvo)  # cria as tarefas recorrentes de hoje

    with st.expander("📖 Como usar esta área"):
        if modo_admin:
            st.markdown(f"""
            **Você é admin.** Adicione tarefas para o usuário selecionado na barra lateral.
            Em *➕ Nova tarefa* defina título (ex: *{dica}*), instruções e prazo.
            A pessoa cumpre enviando uma **foto**; aqui você vê a comprovação e pode
            **reabrir** ou **excluir** tarefas.
            """)
        else:
            st.markdown(f"""
            Aqui estão as tarefas que o seu treinador definiu para você.
            Para concluir, clique em **✅ Concluir com foto**, envie a foto que
            comprova (ex: *{dica}*) e confirme. As concluídas ficam na outra aba.
            """)

    if modo_admin:
        with st.expander("➕ Nova tarefa", expanded=False):
            with st.form(f"form_{categoria}", clear_on_submit=True):
                titulo = st.text_input("Título da tarefa *", placeholder=dica)
                descricao = st.text_area("Descrição / instruções")
                prazo = st.date_input("Prazo (opcional)", value=None, format="DD/MM/YYYY")
                enviado = st.form_submit_button("💾 Salvar tarefa", width='stretch')
            if enviado:
                if not titulo.strip():
                    st.error("Dê um título para a tarefa.")
                else:
                    db.criar_tarefa(email_alvo, categoria, titulo.strip(),
                                    descricao.strip(),
                                    prazo.strftime("%Y-%m-%d") if prazo else "")
                    st.success("Tarefa adicionada!")
                    st.rerun()

        _bloco_recorrentes(categoria, dica, email_alvo)

    df = db.listar_tarefas(email_alvo, categoria)
    if df.empty:
        msg = ("Nenhuma tarefa para este usuário ainda." if modo_admin
               else "Você ainda não tem tarefas aqui. 🎉")
        st.info(msg)
        return

    pendentes = df[df["status"] != "Concluida"]
    concluidas = df[df["status"] == "Concluida"]

    c1, c2 = st.columns(2)
    c1.metric("⏳ Pendentes", len(pendentes))
    c2.metric("✅ Concluídas", len(concluidas))

    aba_pend, aba_ok = st.tabs([f"⏳ Pendentes ({len(pendentes)})",
                                f"✅ Concluídas ({len(concluidas)})"])
    with aba_pend:
        if pendentes.empty:
            st.success("Tudo em dia! Nenhuma tarefa pendente. 🎉")
        for _, t in pendentes.iterrows():
            _card_pendente(t, modo_admin)
    with aba_ok:
        if concluidas.empty:
            st.info("Ainda não há tarefas concluídas.")
        for _, t in concluidas.iloc[::-1].iterrows():
            _card_concluida(t, modo_admin)


@st.dialog("Detalhes da tarefa")
def _modal_detalhes(titulo, descricao, foto_ref=""):
    st.markdown(f"### {titulo}")
    if descricao and str(descricao).strip():
        st.markdown(str(descricao).replace("\n", "  \n"))
    else:
        st.caption("Esta tarefa não tem detalhes.")
    if foto_ref:
        foto = db.ler_foto(foto_ref)
        if foto:
            st.image(foto, caption="Comprovação", width='stretch')


def _card_pendente(t, modo_admin):
    prazo = f"🗓️ Prazo: {t['prazo']}" if t["prazo"] else ""
    st.markdown(f"""
    <div class="card card-pendente">
        <h4>{t['titulo']} {chip_status(t['status'])}</h4>
        <p>{prazo}</p>
    </div>""", unsafe_allow_html=True)

    if st.button("👁️ Ver detalhes", key=f"det_{t['id']}", width='stretch'):
        _modal_detalhes(t["titulo"], t["descricao"])

    if modo_admin:
        if st.button("🗑️ Excluir", key=f"del_{t['id']}"):
            db.excluir_tarefa(t["id"])
            st.rerun()
    else:
        with st.expander("✅ Concluir com foto"):
            with st.form(f"concluir_{t['id']}", clear_on_submit=True):
                foto = st.file_uploader("Foto de comprovação",
                                        type=["jpg", "jpeg", "png"], key=f"up_{t['id']}")
                obs = st.text_input("Observação (opcional)", key=f"obs_{t['id']}")
                ok = st.form_submit_button("Confirmar conclusão", width='stretch')
            if ok:
                if not foto:
                    st.error("Envie uma foto para comprovar a conclusão.")
                else:
                    db.concluir_tarefa(t["id"], foto.getvalue(), foto.name, obs.strip())
                    st.success("Tarefa concluída! 💪")
                    st.rerun()
    st.divider()


def _card_concluida(t, modo_admin):
    st.markdown(f"""
    <div class="card card-ok">
        <h4>{t['titulo']} {chip_status(t['status'])}</h4>
        <p>✅ Concluída em: {t['data_conclusao']}</p>
        {f"<p>📝 {t['observacao']}</p>" if t['observacao'] else ""}
    </div>""", unsafe_allow_html=True)

    if st.button("👁️ Ver detalhes e foto", key=f"det_{t['id']}", width='stretch'):
        _modal_detalhes(t["titulo"], t["descricao"], t["foto_ref"])

    col1, col2 = st.columns(2)
    if col1.button("↩️ Reabrir", key=f"reab_{t['id']}"):
        db.reabrir_tarefa(t["id"])
        st.rerun()
    if modo_admin and col2.button("🗑️ Excluir", key=f"delok_{t['id']}"):
        db.excluir_tarefa(t["id"])
        st.rerun()
    st.divider()


# ==========================================================================
# PAGINA METAS
# ==========================================================================
def pagina_metas(email_alvo, modo_admin):
    st.markdown("## 🎯 Metas")

    with st.expander("📖 Como usar esta área"):
        if modo_admin:
            st.markdown("""
            Aqui você vê as metas que **o usuário criou** (as expectativas dele) e também
            pode **criar metas** para ele. Cada meta tem valor inicial, alvo e unidade.
            Dá para atualizar o progresso ou excluir.
            """)
        else:
            st.markdown("""
            **Crie aqui as suas metas** — o que você espera alcançar (ex: *Chegar a 70 kg*,
            *Correr 5 km*). Defina o valor inicial, o alvo e a unidade. Conforme avança,
            abra a meta e registre seu **valor atual**; a barra mostra o quanto já alcançou.
            Seu treinador também acompanha essas metas.
            """)

    with st.expander("➕ Nova meta", expanded=False):
        with st.form("form_meta", clear_on_submit=True):
            col = st.columns(2)
            titulo = col[0].text_input("Nome da meta *", placeholder="Ex: Chegar a 70 kg")
            categoria = col[1].selectbox("Categoria",
                                         ["Alimentação", "Exercícios", "Peso", "Outro"])
            descricao = st.text_input("Descrição (opcional)")
            col2 = st.columns(3)
            v_ini = col2[0].number_input("Valor inicial", value=0.0, step=0.5)
            v_alvo = col2[1].number_input("Valor alvo", value=0.0, step=0.5)
            unidade = col2[2].text_input("Unidade", placeholder="kg, reps, L...")
            prazo = st.date_input("Prazo (opcional)", value=None, format="DD/MM/YYYY")
            ok = st.form_submit_button("💾 Salvar meta", width='stretch')
        if ok:
            if not titulo.strip():
                st.error("Dê um nome para a meta.")
            else:
                db.criar_meta(email_alvo, categoria, titulo.strip(), descricao.strip(),
                              v_ini, v_alvo, unidade.strip(),
                              prazo.strftime("%Y-%m-%d") if prazo else "")
                st.success("Meta criada!")
                st.rerun()

    metas = db.listar_metas(email_alvo)
    if metas.empty:
        st.info("Nenhuma meta ainda." if modo_admin
                else "Você ainda não criou metas. Crie a primeira em *➕ Nova meta*.")
        return

    for _, m in metas.iloc[::-1].iterrows():
        ini, atual, alvo = num(m["valor_inicial"]), num(m["valor_atual"]), num(m["valor_alvo"])
        prog = (atual - ini) / (alvo - ini) if alvo != ini else 1.0
        prog = max(0.0, min(1.0, prog))
        concluida = m["status"] == "Concluida"
        st.markdown(f"""
        <div class="card {'card-ok' if concluida else 'card-pendente'}">
            <h4>{m['titulo']} {'✅' if concluida else ''}
                <span style="color:#64748b;font-size:.8rem">({m['categoria']})</span></h4>
            <p>{m['descricao'] or ''}</p>
            <p>{atual:g} / {alvo:g} {m['unidade']} &nbsp;•&nbsp; {prog*100:.0f}% concluído
               {f"&nbsp;•&nbsp; 🗓️ {m['prazo']}" if m['prazo'] else ""}</p>
        </div>""", unsafe_allow_html=True)
        st.progress(prog)

        with st.expander("✏️ Atualizar progresso"):
            with st.form(f"upd_meta_{m['id']}"):
                novo = st.number_input("Valor atual", value=atual, step=0.5, key=f"v_{m['id']}")
                status = st.selectbox("Status", ["Em andamento", "Concluida"],
                                      index=1 if concluida else 0, key=f"s_{m['id']}")
                colb = st.columns(2)
                salvar = colb[0].form_submit_button("💾 Salvar", width='stretch')
                excluir = colb[1].form_submit_button("🗑️ Excluir meta", width='stretch')
            if salvar:
                db.atualizar_meta(m["id"], novo, status)
                st.rerun()
            if excluir:
                db.excluir_meta(m["id"])
                st.rerun()
        st.divider()


# ==========================================================================
# PAGINA EVOLUCAO
# ==========================================================================
def pagina_evolucao(email_alvo, modo_admin):
    st.markdown("## 📈 Evolução")

    with st.expander("📖 Como usar esta área"):
        st.markdown("""
        Em *➕ Novo registro*, informe a data e preencha **peso** e as **medidas**
        que quiser (deixe em branco as que não medir). Os **gráficos** se atualizam
        sozinhos e a tabela lista o histórico.
        💡 Registre sempre no mesmo horário (ex: de manhã, em jejum).
        """)

    with st.expander("➕ Novo registro", expanded=False):
        with st.form("form_evo", clear_on_submit=True):
            data_reg = st.date_input("Data", value=date.today(), format="DD/MM/YYYY")
            c = st.columns(3)
            peso = c[0].number_input("Peso (kg)", value=0.0, step=0.1)
            cintura = c[1].number_input("Cintura (cm)", value=0.0, step=0.5)
            quadril = c[2].number_input("Quadril (cm)", value=0.0, step=0.5)
            c2 = st.columns(3)
            braco = c2[0].number_input("Braço (cm)", value=0.0, step=0.5)
            coxa = c2[1].number_input("Coxa (cm)", value=0.0, step=0.5)
            peito = c2[2].number_input("Peito (cm)", value=0.0, step=0.5)
            obs = st.text_input("Observação (opcional)")
            ok = st.form_submit_button("💾 Salvar registro", width='stretch')
        if ok:
            db.registrar_evolucao(email_alvo, data_reg.strftime("%Y-%m-%d"), peso,
                                  cintura, quadril, braco, coxa, peito, obs.strip())
            st.success("Registro salvo!")
            st.rerun()

    evo = db.listar_evolucao(email_alvo)
    if evo.empty:
        st.info("Nenhum registro ainda.")
        return

    df = evo.copy()
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    for col in ["peso", "cintura", "quadril", "braco", "coxa", "peito"]:
        df[col] = df[col].apply(lambda v: num(v, None))
    df = df.sort_values("data")

    primeiro, ultimo = df.iloc[0], df.iloc[-1]
    cols = st.columns(4)
    if pd.notna(ultimo["peso"]):
        delta = (f"{ultimo['peso'] - primeiro['peso']:+.1f} kg desde o início"
                 if pd.notna(primeiro["peso"]) else None)
        cols[0].metric("⚖️ Peso atual", f"{ultimo['peso']:.1f} kg", delta, delta_color="inverse")
    cols[1].metric("📅 Registros", len(df))
    if pd.notna(ultimo["cintura"]):
        d = (f"{ultimo['cintura'] - primeiro['cintura']:+.1f} cm"
             if pd.notna(primeiro["cintura"]) else None)
        cols[2].metric("📏 Cintura", f"{ultimo['cintura']:.1f} cm", d, delta_color="inverse")
    cols[3].metric("🗓️ Último", ultimo["data"].strftime("%d/%m/%Y")
                   if pd.notna(ultimo["data"]) else "—")

    st.markdown("### Gráficos")
    if df["peso"].notna().any():
        fig = px.line(df, x="data", y="peso", markers=True, title="Peso (kg)")
        fig.update_traces(line_color="#22c55e")
        fig.update_layout(template="plotly_dark", height=320,
                          margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width='stretch')

    medidas = ["cintura", "quadril", "braco", "coxa", "peito"]
    presentes = [m for m in medidas if df[m].notna().any()]
    if presentes:
        long = df.melt(id_vars="data", value_vars=presentes,
                       var_name="Medida", value_name="cm").dropna(subset=["cm"])
        long["Medida"] = long["Medida"].str.capitalize()
        fig2 = px.line(long, x="data", y="cm", color="Medida", markers=True,
                       title="Medidas (cm)")
        fig2.update_layout(template="plotly_dark", height=340,
                           margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig2, width='stretch')

    st.markdown("### Histórico")
    tabela = df.copy()
    tabela["data"] = tabela["data"].dt.strftime("%d/%m/%Y")
    tabela = tabela.rename(columns={
        "data": "Data", "peso": "Peso", "cintura": "Cintura", "quadril": "Quadril",
        "braco": "Braço", "coxa": "Coxa", "peito": "Peito", "observacao": "Obs"})
    st.dataframe(tabela[["Data", "Peso", "Cintura", "Quadril", "Braço", "Coxa", "Peito", "Obs"]],
                 width='stretch', hide_index=True)

    with st.expander("🗑️ Excluir um registro"):
        opcoes = {f"{r['data'].strftime('%d/%m/%Y') if pd.notna(r['data']) else '?'} — "
                  f"{r['peso'] if pd.notna(r['peso']) else '-'} kg": r["id"]
                  for _, r in df.iterrows()}
        if opcoes:
            escolha = st.selectbox("Registro", list(opcoes.keys()))
            if st.button("Excluir registro selecionado"):
                db.excluir_evolucao(opcoes[escolha])
                st.rerun()


# ==========================================================================
# PAGINAS DE INICIO
# ==========================================================================
def pagina_inicio_usuario(user):
    st.markdown(f"""
    <div class="hero">
        <h1>Olá, {user['nome']}! 💪</h1>
        <p>Cumpra suas tarefas, acompanhe metas e registre sua evolução.</p>
    </div>""", unsafe_allow_html=True)

    email = user["email"]
    garantir_recorrentes(email)  # garante as tarefas recorrentes de hoje
    tarefas = db.listar_tarefas(email)
    metas = db.listar_metas(email)
    evo = db.listar_evolucao(email)
    s = stats_tarefas(tarefas)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔥 Sequência", f"{s['streak']} dia(s)")
    c2.metric("📊 Adesão", f"{s['adesao']}%")
    c3.metric("⏳ Pendentes", s["pend"])
    c4.metric("⚖️ Peso atual", f"{num(evo.iloc[-1]['peso']):.1f} kg" if not evo.empty else "—")
    c5, c6 = st.columns(2)
    c5.metric("✅ Tarefas concluídas", s["ok"])
    c6.metric("🎯 Metas ativas",
              len(metas[metas["status"] == "Em andamento"]) if not metas.empty else 0)

    st.markdown("""
    <div class="card"><h4>🧭 Como usar</h4>
    <p>Use o menu à esquerda: <b>Alimentação</b> e <b>Exercícios</b> trazem suas tarefas
    (conclua com foto), <b>Metas</b> mostra seus objetivos e <b>Evolução</b> é onde você
    registra peso e medidas. Cada área tem um botão <b>📖 Como usar</b>.</p></div>
    """, unsafe_allow_html=True)


def pagina_inicio_admin(user):
    st.markdown(f"""
    <div class="hero">
        <h1>Painel do Admin 👋</h1>
        <p>Bem-vindo, {user['nome']}. Gerencie tarefas, metas e evolução dos usuários.</p>
    </div>""", unsafe_allow_html=True)

    usuarios = db.listar_usuarios()
    geral = db.listar_todas_tarefas()
    n_users = len(usuarios[usuarios["perfil"] != "admin"]) if not usuarios.empty else 0
    pend = len(geral[geral["status"] != "Concluida"]) if not geral.empty else 0
    ok = len(geral[geral["status"] == "Concluida"]) if not geral.empty else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("👥 Usuários", n_users)
    c2.metric("⏳ Tarefas pendentes (todos)", pend)
    c3.metric("✅ Tarefas concluídas (todos)", ok)

    st.markdown("""
    <div class="card"><h4>🧭 Como gerenciar</h4>
    <p><b>1.</b> Selecione um usuário na barra lateral (campo <b>👤 Gerenciando</b>).<br>
    <b>2.</b> Vá em <b>Alimentação</b>/<b>Exercícios</b> para criar tarefas, em <b>Metas</b>
    para definir objetivos e em <b>Evolução</b> para ver/registrar peso e medidas dele.<br>
    <b>3.</b> Em <b>Usuários</b> você vê todos os cadastrados. Envie o link do app para
    novas pessoas se cadastrarem.</p></div>
    """, unsafe_allow_html=True)


def pagina_usuarios():
    st.markdown("## 👥 Usuários")
    usuarios = db.listar_usuarios()
    comuns = usuarios[usuarios["perfil"] != "admin"] if not usuarios.empty else usuarios
    if comuns.empty:
        st.info("Nenhum usuário cadastrado ainda. Envie o link do app para se cadastrarem.")
        return

    geral = db.listar_todas_tarefas()
    for _, u in comuns.iterrows():
        t = geral[geral["usuario_email"] == u["email"]] if not geral.empty else geral.copy()
        s = stats_tarefas(t)
        st.markdown(f"""
        <div class="card">
            <h4>{u['nome']} &nbsp;<span style="color:#22c55e;font-size:.85rem">🔥 {s['streak']} dia(s) · {s['adesao']}% adesão</span></h4>
            <p>📧 {u['email']} &nbsp;•&nbsp; cadastrado em {u['data_cadastro']}</p>
            <p>⏳ {s['pend']} pendentes &nbsp;•&nbsp; ✅ {s['ok']} concluídas</p>
        </div>""", unsafe_allow_html=True)

        with st.expander("🔑 Redefinir senha desta pessoa"):
            with st.form(f"reset_{u['email']}", clear_on_submit=True):
                nova = st.text_input("Nova senha provisória", type="password",
                                     key=f"ns_{u['email']}")
                ok_reset = st.form_submit_button("Redefinir senha", width='stretch')
            if ok_reset:
                sucesso, msg = auth.redefinir_senha(u["email"], nova)
                (st.success if sucesso else st.error)(msg)


# ==========================================================================
# PAGINA REFEICAO IA (DeepSeek)
# ==========================================================================
def _totais_macros(r):
    p = sum(num(it.get("proteina_g")) for it in r.get("itens", []))
    c = sum(num(it.get("carbo_g")) for it in r.get("itens", []))
    g = sum(num(it.get("gordura_g")) for it in r.get("itens", []))
    return p, c, g


def _descricao_refeicao(r, calorias):
    total = num(r.get("total_calorias"), calorias)
    linhas = [f"Refeição de ~{total:.0f} kcal:"]
    for it in r.get("itens", []):
        p, c, g = num(it.get("proteina_g")), num(it.get("carbo_g")), num(it.get("gordura_g"))
        linhas.append(f"• {it.get('alimento')}: {it.get('gramas')} g "
                      f"(~{it.get('calorias')} kcal | P {p:.0f}g · C {c:.0f}g · G {g:.0f}g)")
    tp, tc, tg = _totais_macros(r)
    linhas.append(f"Totais de macros → Proteína {tp:.0f}g · Carboidrato {tc:.0f}g · "
                  f"Gordura {tg:.0f}g")
    if r.get("observacao"):
        linhas.append(f"Obs: {r['observacao']}")
    return "\n".join(linhas)


def pagina_refeicao_ia(user):
    st.markdown("## 🍽️ Refeição IA")

    with st.expander("📖 Como usar esta área"):
        st.markdown("""
        Digite os **alimentos** que você quer na refeição e a **meta de calorias**.
        A IA calcula a **porção (em gramas)** de cada alimento para chegar perto da meta,
        com calorias e macronutrientes. Ex: *arroz, feijão, brócolis, peixe tilápia* →
        600 kcal. Depois você pode **salvar como tarefa de alimentação**.
        💡 Os valores são estimativas para orientação, não substituem um nutricionista.
        """)

    if not ia.tem_chave():
        st.warning("A chave do DeepSeek ainda não foi configurada. "
                   "Adicione `[deepseek]` com `api_key` no `secrets.toml`.")
        return

    with st.form("form_refeicao"):
        alimentos = st.text_area("Alimentos da refeição *",
                                 placeholder="Ex: arroz, feijão, brócolis, peixe tilápia")
        col = st.columns(2)
        calorias = col[0].number_input("Meta de calorias (kcal)", min_value=50,
                                       max_value=3000, value=600, step=50)
        restricoes = col[1].text_input("Observações (opcional)",
                                       placeholder="ex: pouco óleo, sem sal")
        gerar = st.form_submit_button("✨ Gerar refeição", width='stretch')

    if gerar:
        if not alimentos.strip():
            st.error("Digite ao menos um alimento.")
        else:
            try:
                with st.spinner("Calculando porções com a IA..."):
                    r = ia.gerar_refeicao(alimentos.strip(), int(calorias), restricoes)
                st.session_state["refeicao_ia"] = {"r": r, "calorias": int(calorias)}
            except Exception as e:
                st.session_state.pop("refeicao_ia", None)
                st.error(f"Não foi possível gerar agora. Detalhe: {e}")

    dados = st.session_state.get("refeicao_ia")
    if not dados:
        return
    r, calorias = dados["r"], dados["calorias"]
    itens = r.get("itens", [])
    if not itens:
        st.warning("A IA não retornou itens. Tente reescrever os alimentos.")
        return

    tabela = pd.DataFrame(itens).rename(columns={
        "alimento": "Alimento", "gramas": "Porção (g)", "calorias": "Calorias",
        "proteina_g": "Proteína (g)", "carbo_g": "Carbo (g)", "gordura_g": "Gordura (g)"})
    st.markdown("### Porções sugeridas")
    st.dataframe(tabela, width='stretch', hide_index=True)

    tp, tc, tg = _totais_macros(r)
    m = st.columns(4)
    if r.get("total_calorias"):
        m[0].metric("🔥 Calorias", f"{num(r['total_calorias']):.0f}",
                    f"meta: {int(calorias)} kcal")
    m[1].metric("🥩 Proteína", f"{tp:.0f} g")
    m[2].metric("🍞 Carboidrato", f"{tc:.0f} g")
    m[3].metric("🥑 Gordura", f"{tg:.0f} g")
    if r.get("observacao"):
        st.info(f"📝 {r['observacao']}")

    # ---- salvar como tarefa de alimentacao ----
    st.markdown("### 📌 Salvar como tarefa de alimentação")
    admin = user["perfil"] == "admin"
    if admin:
        usuarios = db.listar_usuarios()
        comuns = usuarios[usuarios["perfil"] != "admin"] if not usuarios.empty else usuarios
        if comuns.empty:
            st.info("Cadastre um usuário para poder criar a tarefa.")
            return
        mapa = {f"{x['nome']} ({x['email']})": x["email"] for _, x in comuns.iterrows()}
        rotulo = st.selectbox("Criar tarefa para qual usuário?", list(mapa.keys()),
                              key="ref_alvo")
        email_alvo = mapa[rotulo]
    else:
        email_alvo = user["email"]

    titulo = st.text_input("Título da tarefa", value=f"Refeição ~{int(calorias)} kcal",
                           key="ref_titulo")
    if st.button("💾 Salvar como tarefa", key="ref_salvar", width='stretch'):
        db.criar_tarefa(email_alvo, "Alimentação",
                        titulo.strip() or f"Refeição ~{int(calorias)} kcal",
                        _descricao_refeicao(r, calorias), "")
        st.success("Tarefa de alimentação criada! ✅")


# ==========================================================================
# PAGINA PLANO IA (treino + dieta)
# ==========================================================================
DIAS_FULL = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
_DIA_BASE = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3,
             "sexta": 4, "sabado": 5, "domingo": 6}


def _dia_para_idx(nome):
    """Converte 'Segunda', 'segunda-feira', 'Terça' etc. no indice 0..6 (ou None)."""
    n = str(nome).strip().lower()
    for a, b in [("á", "a"), ("ã", "a"), ("â", "a"), ("é", "e"), ("ê", "e"),
                 ("í", "i"), ("ó", "o"), ("ô", "o"), ("ú", "u"), ("ç", "c")]:
        n = n.replace(a, b)
    n = n.replace("-feira", "").replace("feira", "").strip()
    return _DIA_BASE.get(n)


def _alvo_para_salvar(user, key, rotulo="Salvar para qual usuário?"):
    """Retorna (email_alvo, nome) ou (None, None). Admin escolhe; usuario e ele mesmo."""
    if user["perfil"] != "admin":
        return user["email"], user["nome"]
    usuarios = db.listar_usuarios()
    comuns = usuarios[usuarios["perfil"] != "admin"] if not usuarios.empty else usuarios
    if comuns.empty:
        st.info("Nenhum usuário cadastrado ainda.")
        return None, None
    mapa = {f"{x['nome']} ({x['email']})": x["email"] for _, x in comuns.iterrows()}
    escolha = st.selectbox(rotulo, list(mapa.keys()), key=key)
    return mapa[escolha], escolha.split(" (")[0]


def pagina_perfil(user):
    st.markdown("## 👤 Perfil")
    with st.expander("📖 Como usar esta área"):
        st.markdown("""
        Preencha seus **dados pessoais** (sexo, idade, altura) — eles ficam salvos e o
        **Plano IA** usa automaticamente. Logo abaixo, as **medidas atuais** (peso e
        medidas) aparecem sozinhas a partir do seu último registro em **📈 Evolução** e
        se atualizam conforme você registra.
        """)

    email_alvo, nome_alvo = _alvo_para_salvar(user, "perfil_alvo",
                                              "Ver/editar perfil de qual usuário?")
    if not email_alvo:
        return
    if user["perfil"] == "admin":
        st.caption(f"Editando perfil de: **{nome_alvo}**")

    pf = db.perfil_fisico(email_alvo)
    OP_SEXO = ["—", "Feminino", "Masculino"]
    nasc_atual = None
    try:
        nasc_atual = datetime.strptime(pf.get("nascimento", ""), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        nasc_atual = None

    st.markdown("#### Dados pessoais")
    with st.form(f"form_perfil_{email_alvo}"):
        c = st.columns(3)
        sexo = c[0].selectbox("Sexo", OP_SEXO,
                              index=OP_SEXO.index(pf["sexo"]) if pf.get("sexo") in OP_SEXO else 0)
        nascimento = c[1].date_input("Data de nascimento", value=nasc_atual,
                                     min_value=date(1900, 1, 1), max_value=date.today(),
                                     format="DD/MM/YYYY")
        altura = c[2].number_input("Altura (cm)", 0, 250,
                                   max(0, min(250, int(num(pf.get("altura"), 0)))))
        if nascimento:
            ida = db.idade_de_nascimento(nascimento.strftime("%Y-%m-%d"))
            st.caption(f"Idade: **{ida} anos** (calculada automaticamente).")
        ok = st.form_submit_button("💾 Salvar perfil", width='stretch')
    if ok:
        db.salvar_perfil_fisico(email_alvo, sexo if sexo != "—" else "",
                                nascimento.strftime("%Y-%m-%d") if nascimento else "",
                                int(altura))
        st.success("Perfil salvo! ✅")
        st.rerun()

    st.markdown("#### 📏 Medidas atuais")
    st.caption("Atualizam automaticamente conforme os registros em 📈 Evolução.")
    evo = db.listar_evolucao(email_alvo)
    if evo.empty:
        st.info("Nenhuma medida ainda. Registre em 📈 Evolução para aparecer aqui.")
        return
    u = evo.iloc[-1]

    def _med(rotulo, campo, unidade="cm"):
        v = num(u[campo], None)
        return rotulo, (f"{v:.1f} {unidade}" if v else "—")

    linha1 = [("⚖️ Peso", f"{num(u['peso']):.1f} kg" if num(u['peso'], None) else "—"),
              _med("📏 Cintura", "cintura"), _med("Quadril", "quadril")]
    linha2 = [_med("Braço", "braco"), _med("Coxa", "coxa"), _med("Peito", "peito")]
    for linha in (linha1, linha2):
        cols = st.columns(3)
        for col, (rot, val) in zip(cols, linha):
            col.metric(rot, val)
    st.caption(f"Último registro: {u['data']}")


def _desc_treino_dia(dia):
    linhas = [f"Foco: {dia.get('foco', '')}"]
    for ex in dia.get("exercicios", []):
        desc = f"• {ex.get('nome')}: {ex.get('series')}x{ex.get('reps')}"
        if ex.get("descanso"):
            desc += f" (descanso {ex.get('descanso')})"
        linhas.append(desc)
    return "\n".join(linhas)


def _desc_uma_refeicao(ref):
    """Descrição de uma única refeição (para virar uma tarefa própria)."""
    linhas = []
    for it in ref.get("itens", []):
        linhas.append(f"• {it.get('alimento')}: {it.get('porcao')} "
                      f"(~{it.get('calorias')} kcal)")
    if ref.get("observacao"):
        linhas.append(f"Obs: {ref['observacao']}")
    return "\n".join(linhas)


def pagina_plano_ia(user):
    st.markdown("## 🤖 Plano IA (treino e dieta)")

    with st.expander("📖 Como usar esta área"):
        st.markdown("""
        Escolha gerar **Treino**, **Dieta** ou **Ambos**, informe objetivo, nível e
        preferências, e a IA monta um plano semanal. Depois você pode **salvar** o treino
        como tarefas recorrentes (nos dias da semana) e a dieta como tarefa diária.
        💡 É uma sugestão automática — revise antes de aplicar.
        """)

    if not ia.tem_chave():
        st.warning("A chave do DeepSeek ainda não foi configurada. "
                   "Adicione `[deepseek]` com `api_key` no `secrets.toml`.")
        return

    # Usuario do plano (no topo) -> usado para pre-preencher e para salvar
    email_alvo, nome_alvo = _alvo_para_salvar(user, "plano_alvo", "Usuário do plano:")
    if not email_alvo:
        return
    if user["perfil"] == "admin":
        st.caption(f"Plano para: **{nome_alvo}**")

    # Dados fisicos vem do Perfil (sexo/idade/altura) + peso da Evolucao
    pf = db.perfil_fisico(email_alvo)
    perfil = []
    if pf.get("sexo"):
        perfil.append(f"Sexo: {pf['sexo']}")
    if pf.get("idade") is not None:
        perfil.append(f"Idade: {pf['idade']} anos")
    if num(pf.get("altura"), 0):
        perfil.append(f"Altura: {num(pf['altura']):g}cm")
    if num(pf.get("peso"), 0):
        perfil.append(f"Peso: {num(pf['peso']):g}kg")
    if perfil:
        st.success("📋 Dados do perfil (puxados automaticamente): " + " · ".join(perfil))
    else:
        st.warning("Sem dados de perfil. Preencha em 👤 **Perfil** para um plano melhor "
                   "(o plano ainda funciona sem eles).")

    with st.form("form_plano"):
        tipo = st.radio("O que gerar?", ["Treino", "Dieta", "Ambos"], horizontal=True)
        c = st.columns(2)
        objetivo = c[0].selectbox("Objetivo",
                                  ["Emagrecer", "Ganhar massa muscular",
                                   "Manter / condicionamento"])
        nivel = c[1].selectbox("Nível", ["Iniciante", "Intermediário", "Avançado"])
        c3 = st.columns(3)
        dias_treino = c3[0].number_input("Treinos/semana", 1, 7, 3)
        local = c3[1].selectbox("Local do treino", ["Academia", "Casa", "Ar livre"])
        calorias = c3[2].number_input("Calorias/dia (0 = IA decide)", 0, 6000, 0, step=50)
        refeicoes = st.multiselect(
            "Refeições da dieta (escolha quais quer)",
            ["Café da manhã", "Lanche da manhã", "Almoço", "Lanche da tarde",
             "Jantar", "Ceia"],
            default=["Café da manhã", "Almoço", "Lanche da tarde", "Jantar"])
        restricoes = st.text_input("Restrições/preferências alimentares (opcional)")
        obs = st.text_input("Observações (opcional)")
        gerar = st.form_submit_button("✨ Gerar plano", width='stretch')

    if gerar:
        params = {
            "objetivo": objetivo, "nivel": nivel, "perfil": "; ".join(perfil),
            "dias_treino": int(dias_treino), "local": local,
            "calorias": int(calorias), "restricoes": restricoes, "obs": obs,
            "refeicoes": refeicoes}
        try:
            with st.spinner("Montando o plano com a IA... (pode levar alguns segundos)"):
                plano = ia.gerar_plano(tipo, params)
            st.session_state["plano_ia"] = {"plano": plano, "tipo": tipo, "params": params}
        except Exception as e:
            st.session_state.pop("plano_ia", None)
            st.error(f"Não foi possível gerar agora. Detalhe: {e}")

    dados = st.session_state.get("plano_ia")
    if not dados:
        return
    plano = dados["plano"]
    treino = plano.get("treino")
    dieta = plano.get("dieta")

    if treino and treino.get("dias"):
        st.markdown("### 🏋️ Treino")
        st.caption("Você pode mudar o dia da semana de cada treino e/ou trocar os exercícios.")
        for i, dia in enumerate(treino["dias"]):
            cur = _dia_para_idx(dia.get("dia", ""))
            if cur is None:
                cur = i % 7
            cab = st.columns([2, 3])
            novo_dia = cab[0].selectbox("Dia da semana", DIAS_FULL, index=cur,
                                        key=f"diasel_{i}")
            dia["dia"] = novo_dia  # plano vive na sessao (mesma referencia)
            cab[1].markdown(f"**Foco:** {dia.get('foco', '')}")
            ex = pd.DataFrame(dia.get("exercicios", []))
            if not ex.empty:
                ex = ex.rename(columns={"nome": "Exercício", "series": "Séries",
                                        "reps": "Reps", "descanso": "Descanso"})
                st.dataframe(ex, width='stretch', hide_index=True)
            if st.button("🔄 Trocar os exercícios deste dia", key=f"troca_{i}"):
                try:
                    with st.spinner("Gerando nova variação..."):
                        novo = ia.regenerar_treino_dia(novo_dia, dados.get("params", {}))
                    treino["dias"][i] = novo
                    st.rerun()
                except Exception as e:
                    st.error(f"Não foi possível trocar agora. Detalhe: {e}")
            st.divider()
        if treino.get("observacao"):
            st.info(f"📝 {treino['observacao']}")

    if dieta and dieta.get("refeicoes"):
        st.markdown("### 🥗 Dieta")
        if dieta.get("calorias_alvo"):
            st.metric("🔥 Meta diária", f"{num(dieta['calorias_alvo']):.0f} kcal")
        for ref in dieta["refeicoes"]:
            st.markdown(f"**{ref.get('nome', '')}**")
            its = pd.DataFrame(ref.get("itens", []))
            if not its.empty:
                its = its.rename(columns={"alimento": "Alimento", "porcao": "Porção",
                                          "calorias": "Calorias"})
                st.dataframe(its, width='stretch', hide_index=True)
        if dieta.get("observacao"):
            st.info(f"📝 {dieta['observacao']}")

    # ---- salvar como tarefas (email_alvo ja definido no topo) ----
    st.markdown(f"### 📌 Salvar plano como tarefas — {nome_alvo}")

    if treino and treino.get("dias"):
        st.caption("Cada dia vira uma tarefa recorrente separada, que aparece "
                   "automaticamente no seu dia da semana.")
        if st.button("🏋️ Salvar treino (uma tarefa por dia da semana)",
                     key="save_treino", width='stretch'):
            criados, ignorados = [], []
            for dia in treino["dias"]:
                idx = _dia_para_idx(dia.get("dia", ""))
                if idx is None:
                    ignorados.append(dia.get("dia", "?"))
                    continue
                nome_dia = DIAS_FULL[idx]
                db.criar_recorrente(email_alvo, "Exercícios",
                                    f"Treino {nome_dia}: {dia.get('foco', 'do dia')}",
                                    _desc_treino_dia(dia), "Semanal", str(idx))
                criados.append(f"{nome_dia} ({dia.get('foco', '')})")
            if criados:
                st.success(f"{len(criados)} treino(s) criado(s) para {nome_alvo}:")
                for c in criados:
                    st.markdown(f"- 🗓️ {c}")
                st.caption("Cada um aparece em Exercícios no respectivo dia (e fica "
                           "listado em 🔁 Tarefas recorrentes).")
            if ignorados:
                st.caption(f"Não consegui identificar o dia de: {', '.join(ignorados)}.")

    if dieta and dieta.get("refeicoes"):
        st.caption("Cada refeição vira uma tarefa diária separada (ex: Café da manhã, "
                   "Almoço, Lanche da tarde, Jantar).")
        if st.button("🥗 Salvar cada refeição como tarefa diária", key="save_dieta",
                     width='stretch'):
            n = 0
            for ref in dieta["refeicoes"]:
                nome = str(ref.get("nome", "Refeição")).strip() or "Refeição"
                db.criar_recorrente(email_alvo, "Alimentação", nome,
                                    _desc_uma_refeicao(ref), "Diária", "")
                n += 1
            st.success(f"{n} refeição(ões) criada(s) como tarefas diárias para {nome_alvo}. ✅")


# ==========================================================================
# BARRA LATERAL + ROTEAMENTO
# ==========================================================================
def app_principal(user):
    admin = user["perfil"] == "admin"

    with st.sidebar:
        st.markdown("### 💪 Meu Acompanhamento")
        st.caption(f"👤 {user['nome']}" + (" • **Admin**" if admin else ""))

        if admin:
            opcoes = ["Início", "Usuários", "Alimentação", "Exercícios", "Metas",
                      "Evolução", "Refeição IA", "Plano IA", "Perfil"]
            icones = ["house", "people", "egg-fried", "bicycle", "bullseye",
                      "graph-up-arrow", "stars", "robot", "person-circle"]
        else:
            opcoes = ["Início", "Alimentação", "Exercícios", "Metas", "Evolução",
                      "Refeição IA", "Plano IA", "Perfil"]
            icones = ["house", "egg-fried", "bicycle", "bullseye", "graph-up-arrow",
                      "stars", "robot", "person-circle"]

        escolha = option_menu(
            menu_title=None, options=opcoes, icons=icones, default_index=0,
            key="menu_nav",
            styles={
                "container": {"background-color": "#0f172a"},
                "icon": {"color": "#22c55e", "font-size": "17px"},
                "nav-link": {"font-size": "15px", "--hover-color": "#1e293b"},
                "nav-link-selected": {"background-color": "#16a34a"},
            }) or "Início"

        # Admin escolhe qual usuario gerenciar nas paginas por-usuario
        email_alvo, nome_alvo = None, None
        if admin and escolha in ["Alimentação", "Exercícios", "Metas", "Evolução"]:
            usuarios = db.listar_usuarios()
            comuns = usuarios[usuarios["perfil"] != "admin"] if not usuarios.empty else usuarios
            if comuns.empty:
                st.warning("Nenhum usuário cadastrado ainda.")
            else:
                mapa = {f"{r['nome']} ({r['email']})": r["email"]
                        for _, r in comuns.iterrows()}
                rotulo = st.selectbox("👤 Gerenciando", list(mapa.keys()), key="alvo_sel")
                email_alvo, nome_alvo = mapa[rotulo], rotulo.split(" (")[0]

        st.divider()
        if st.button("🚪 Sair", width='stretch'):
            try:
                cookie_mgr.delete(COOKIE)
            except Exception:
                pass
            st.session_state.clear()
            st.rerun()

    # ---- roteamento ----
    if escolha == "Início":
        pagina_inicio_admin(user) if admin else pagina_inicio_usuario(user)
        return
    if escolha == "Usuários":
        pagina_usuarios()
        return
    if escolha == "Refeição IA":
        pagina_refeicao_ia(user)
        return
    if escolha == "Plano IA":
        pagina_plano_ia(user)
        return
    if escolha == "Perfil":
        pagina_perfil(user)
        return

    # paginas por-usuario
    if admin:
        if not email_alvo:
            st.info("⬅️ Cadastre/seleciona um usuário na barra lateral para gerenciar.")
            return
        st.caption(f"Gerenciando: **{nome_alvo}**")
    else:
        email_alvo = user["email"]

    if escolha == "Alimentação":
        pagina_tarefas("Alimentação", "🍎", "Ex: Comer 3 frutas hoje", email_alvo, admin)
    elif escolha == "Exercícios":
        pagina_tarefas("Exercícios", "🏋️", "Ex: Caminhar 30 minutos", email_alvo, admin)
    elif escolha == "Metas":
        pagina_metas(email_alvo, admin)
    elif escolha == "Evolução":
        pagina_evolucao(email_alvo, admin)


# ==========================================================================
# ENTRADA
# ==========================================================================
# Auto-login: se ja tem um cookie valido, entra sem pedir senha de novo.
if "user" not in st.session_state:
    try:
        token = cookie_mgr.get(COOKIE)
    except Exception:
        token = None
    if token:
        email_cookie = auth.validar_token(token)
        if email_cookie:
            u = auth.carregar_usuario(email_cookie)
            if u:
                st.session_state["user"] = u
                # rerun "limpo": redesenha tudo num ciclo normal, evitando que o
                # menu da barra lateral nao pinte por causa do ciclo do componente.
                st.rerun()

if "user" not in st.session_state:
    tela_login()
else:
    app_principal(st.session_state["user"])
