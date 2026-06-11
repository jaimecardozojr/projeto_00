# 💪 Meu Acompanhamento

App **multiusuário** em **Python + Streamlit** para acompanhar tarefas (alimentação e
exercícios) com **comprovação por foto**, **metas** e **evolução de peso e medidas**.

### Perfis e login
- **Login com senha** (hash seguro PBKDF2). Qualquer pessoa se **cadastra** com o próprio email.
- **Admin** (emails definidos no config): cria/edita/exclui tarefas e metas de cada usuário,
  e acompanha a evolução de todos. Seleciona na barra lateral qual usuário gerenciar.
- **Usuário**: vê só as próprias tarefas, conclui com foto, registra peso/medidas e
  acompanha suas metas.

Áreas do app:
- 🏠 **Início** — visão geral e instruções de uso
- 👥 **Usuários** (admin) — lista de cadastrados e progresso de cada um
- 🍎 **Alimentação** / 🏋️ **Exercícios** — tarefas + foto de comprovação
- 🎯 **Metas** — objetivos com barra de progresso
- 📈 **Evolução** — peso e medidas com gráficos

> O admin é definido em `.streamlit/secrets.toml`, bloco `[auth] admin_emails = [...]`.
> Quem se cadastrar com um email dessa lista entra como admin; os demais, como usuário.

O app funciona em **dois modos automáticos**:
- **Modo local** (padrão): salva tudo na pasta `data/` deste computador. Ótimo para testar.
- **Modo nuvem**: salva os dados **e as fotos** no **Google Sheets**
  (as fotos são compactadas e guardadas numa aba `fotos` da planilha). Ativa sozinho
  quando existe o `service_account.json` + os IDs no `secrets.toml`.

> 💡 **Por que as fotos vão na planilha e não no Drive?** Uma conta de serviço do Google
> não tem cota de armazenamento própria, então não consegue subir arquivos para uma pasta
> comum do Drive. Guardar a foto compactada na própria planilha resolve isso sem custo e
> sem depender de Google Workspace.

---

## 1) Rodar localmente (teste rápido)

Pré-requisito: ter o **Python 3.10+** instalado.

No PowerShell, dentro da pasta do projeto:

```powershell
# (opcional, recomendado) criar ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# instalar dependências
pip install -r requirements.txt

# rodar o app
streamlit run app.py
```

O navegador abre em `http://localhost:8501`. Pronto para usar! 🎉

---

## 2) Ativar o modo nuvem (Google Sheets)

Faça isso quando quiser publicar o app online e manter os dados salvos de verdade.

### 2.1 Criar a conta de serviço do Google
1. Acesse <https://console.cloud.google.com/> e crie um **projeto** (ou use um existente).
2. Em **APIs e serviços → Biblioteca**, ative a **Google Sheets API**.
3. Em **APIs e serviços → Credenciais → Criar credenciais → Conta de serviço**.
   Dê um nome e finalize.
4. Abra a conta de serviço criada → aba **Chaves → Adicionar chave → Criar nova chave → JSON**.
   Um arquivo `.json` será baixado. **Renomeie para `service_account.json` e coloque na raiz do projeto.**
5. Copie o **e-mail da conta de serviço** (algo como
   `nome@projeto.iam.gserviceaccount.com`).

### 2.2 Criar e compartilhar a planilha
1. Crie uma **planilha** no Google Sheets (pode ficar vazia — o app cria as abas sozinho).
   Na URL `https://docs.google.com/spreadsheets/d/`**`ESTE_ID`**`/edit`, copie o `ESTE_ID`.
2. **Compartilhe a planilha** com o e-mail da conta de serviço, como **Editor**.

> As fotos são guardadas (compactadas) numa aba `fotos` dessa mesma planilha —
> não é preciso configurar o Google Drive.

### 2.3 Configurar o app
1. Na pasta `.streamlit/`, renomeie `secrets.toml.example` para **`secrets.toml`**.
2. Preencha apenas `sheet_id` no bloco `[google]` (o `drive_folder_id` é opcional/ignorado).
   A chave é lida automaticamente do `service_account.json`.
3. Rode `python -m streamlit run app.py`. Na tela **Início** deve aparecer
   *"☁️ Modo nuvem ativo"*.

> ⚠️ **Nunca** envie o `secrets.toml` nem o `service_account.json` para o GitHub.
> O `.gitignore` já protege isso.

---

## 3) Publicar online (grátis) — Streamlit Community Cloud

1. Suba o projeto para um repositório no **GitHub** (sem o `secrets.toml` e sem o `service_account.json`).
2. Acesse <https://share.streamlit.io>, conecte o GitHub e selecione o repositório,
   apontando para `app.py`.
3. Em **Advanced settings → Secrets**, cole o bloco `[google]` (com o `sheet_id`)
   **e também** o bloco `[gcp_service_account]` com os campos do `service_account.json`
   (na nuvem não dá para subir o arquivo `.json`, então a chave vai aqui — veja o
   modelo comentado em `secrets.toml.example`).
4. Deploy. O app fica com um link público que você pode enviar para a pessoa usar. 🚀

---

## Estrutura do projeto

```
app.py                      # interface (todas as telas)
storage.py                  # camada de dados (local ou Google)
requirements.txt            # dependências
README.md                   # este arquivo
.streamlit/
  config.toml               # tema visual
  secrets.toml.example      # modelo de credenciais Google
data/                       # (criado no modo local) CSVs + fotos
```

## Dúvidas comuns
- **As fotos não aparecem no modo nuvem?** Confirme que a **pasta do Drive** foi
  compartilhada com a conta de serviço como Editor.
- **Erro ao conectar no Google?** O app cai automaticamente para o modo local e
  mostra um aviso com o motivo. Reveja os passos 2.1–2.3.
- **Quero mudar as cores?** Edite `.streamlit/config.toml`.
