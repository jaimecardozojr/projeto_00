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
def pagina_tarefas(categoria, emoji, dica, email_alvo, modo_admin):
    st.markdown(f"## {emoji} {categoria}")

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


def _card_pendente(t, modo_admin):
    prazo = f"🗓️ Prazo: {t['prazo']}" if t["prazo"] else ""
    st.markdown(f"""
    <div class="card card-pendente">
        <h4>{t['titulo']} {chip_status(t['status'])}</h4>
        <p>{t['descricao'] or 'Sem descrição.'}</p>
        <p>{prazo}</p>
    </div>""", unsafe_allow_html=True)

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
        <p>{t['descricao'] or ''}</p>
        <p>✅ Concluída em: {t['data_conclusao']}</p>
        {f"<p>📝 {t['observacao']}</p>" if t['observacao'] else ""}
    </div>""", unsafe_allow_html=True)

    if t["foto_ref"]:
        foto = db.ler_foto(t["foto_ref"])
        if foto:
            st.image(foto, width=320, caption="Comprovação")
        else:
            st.caption("⚠️ Não foi possível carregar a foto.")

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
    tarefas = db.listar_tarefas(email)
    metas = db.listar_metas(email)
    evo = db.listar_evolucao(email)

    pend = len(tarefas[tarefas["status"] != "Concluida"]) if not tarefas.empty else 0
    ok = len(tarefas[tarefas["status"] == "Concluida"]) if not tarefas.empty else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("⏳ Tarefas pendentes", pend)
    c2.metric("✅ Concluídas", ok)
    c3.metric("🎯 Metas ativas",
              len(metas[metas["status"] == "Em andamento"]) if not metas.empty else 0)
    c4.metric("⚖️ Peso atual", f"{num(evo.iloc[-1]['peso']):.1f} kg" if not evo.empty else "—")

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
        t = geral[geral["usuario_email"] == u["email"]] if not geral.empty else geral
        pend = len(t[t["status"] != "Concluida"]) if not t.empty else 0
        ok = len(t[t["status"] == "Concluida"]) if not t.empty else 0
        st.markdown(f"""
        <div class="card">
            <h4>{u['nome']}</h4>
            <p>📧 {u['email']} &nbsp;•&nbsp; cadastrado em {u['data_cadastro']}</p>
            <p>⏳ {pend} pendentes &nbsp;•&nbsp; ✅ {ok} concluídas</p>
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
def pagina_refeicao_ia():
    st.markdown("## 🍽️ Refeição IA")

    with st.expander("📖 Como usar esta área"):
        st.markdown("""
        Digite os **alimentos** que você quer na refeição e a **meta de calorias**.
        A IA calcula a **porção (em gramas)** de cada alimento para chegar perto da meta,
        com calorias e macronutrientes. Ex: *arroz, feijão, brócolis, peixe tilápia* →
        600 kcal.
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
            return
        try:
            with st.spinner("Calculando porções com a IA..."):
                r = ia.gerar_refeicao(alimentos.strip(), int(calorias), restricoes)
        except Exception as e:
            st.error(f"Não foi possível gerar agora. Detalhe: {e}")
            return

        itens = r.get("itens", [])
        if not itens:
            st.warning("A IA não retornou itens. Tente reescrever os alimentos.")
            return

        tabela = pd.DataFrame(itens)
        rotulos = {"alimento": "Alimento", "gramas": "Porção (g)", "calorias": "Calorias",
                   "proteina_g": "Proteína (g)", "carbo_g": "Carbo (g)",
                   "gordura_g": "Gordura (g)"}
        tabela = tabela.rename(columns=rotulos)
        st.markdown("### Porções sugeridas")
        st.dataframe(tabela, width='stretch', hide_index=True)

        total = r.get("total_calorias")
        if total:
            st.metric("🔥 Total estimado", f"{num(total):.0f} kcal", f"meta: {int(calorias)} kcal")
        if r.get("observacao"):
            st.info(f"📝 {r['observacao']}")


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
                      "Evolução", "Refeição IA"]
            icones = ["house", "people", "egg-fried", "bicycle", "bullseye",
                      "graph-up-arrow", "stars"]
        else:
            opcoes = ["Início", "Alimentação", "Exercícios", "Metas", "Evolução",
                      "Refeição IA"]
            icones = ["house", "egg-fried", "bicycle", "bullseye", "graph-up-arrow", "stars"]

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
        pagina_refeicao_ia()
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
