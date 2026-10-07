# TaskAI — Guia rápido (leia antes de subir)

## ⚠️ Sobre a chave de IA

A chave da Groq que veio no projeto anterior foi trocada de lugar (o app estava usando Gemini
temporariamente). Agora o app está **de volta para a Groq**, como você pediu — mas gere uma
**chave nova**, pois a antiga passou por outras ferramentas e é mais seguro tratá-la como
comprometida. Gere a nova em **console.groq.com/keys** (gratuito, sem cartão). Nunca suba o
arquivo `.env` para o GitHub (ele já está no `.gitignore`).

---

## O que foi feito nesta rodada

1. **IA trocada para Groq** — `GROQ_API_KEY` / `GROQ_MODEL` (padrão `llama-3.3-70b-versatile`). Rápida e gratuita.
2. **Plano anual com desconto** — na página **Planos**, o card Pro agora tem um seletor Mensal/Anual.
   O anual sai com **20% de desconto** (configurável via `PRO_ANNUAL_DISCOUNT_PCT`), mostrando o valor
   equivalente por mês e o total cobrado no ano. Continua sendo uma ativação de demonstração — nenhuma
   cobrança real acontece.
3. **Relatório da equipe em .docx com texto + mini planilha + gráficos, tudo no mesmo arquivo** — o botão
   "Relatório da equipe" (em Equipe) e "Relatório" (em Minhas Tarefas) agora geram um Word com:
   - Um **resumo executivo em texto**, escrito automaticamente a partir dos dados (quem está liderando
     a equipe, quantas tarefas estão atrasadas, quem ainda não tem tarefa atribuída etc.)
   - **Gráficos** (barras e pizza) da distribuição de tarefas por status, e um gráfico de progresso por
     funcionário nos relatórios de equipe
   - **"Mini planilhas"**: tabelas com cabeçalho colorido e linhas alternadas, mostrando o resumo geral
     e o detalhamento de tarefas feitas, em andamento e não feitas — tudo dentro do mesmo `.docx`, pronto
     para abrir no Word.
4. **Acessibilidade** — um botão flutuante (ícone de acessibilidade universal) aparece no canto inferior
   esquerdo em **todas as páginas**, com um painel contendo:
   - Aumento de fonte (4 níveis)
   - Alto contraste (preto e amarelo) — para baixa visão
   - Sublinhar links, redução de animações
   - **Leitura da página em voz alta** (Text-to-Speech do navegador, em português) — para pessoas com
     baixa visão ou dificuldade de leitura
   - **Tradução em Libras (VLibras)** — widget oficial do governo federal, ativado sob demanda, para
     pessoas surdas ou com deficiência auditiva
   - Preferências salvas no navegador da pessoa (não exige login)
   - Também foram adicionados: link de "pular para o conteúdo", rótulos (`aria-label`) em botões que só
     tinham ícone, `alt` nas fotos de perfil, e contraste de foco mais visível para navegação por teclado.
5. **Estrutura ajustada para o Render + banco gratuito do Render** — veja a seção de deploy abaixo. O
   `render.yaml` agora provisiona o **Postgres gratuito do próprio Render** automaticamente, com o campo
   `runtime: python` (o nome atual desse campo — `env` é a versão antiga e depreciada), a versão do
   Python fixada em `3.12.7` e um endpoint `/healthz` que o Render usa para confirmar que o app e o
   banco estão de fato respondendo. Também corrigi a versão do `psycopg2-binary`: a que estava fixada
   (2.9.9) não tem build pronto para Python 3.13 — que é a versão padrão mais recente do Render — e
   isso quebraria o build; agora está livre para pegar uma versão mais nova e compatível.
6. **Correções de responsividade / mobile** — a tabela de tarefas agora rola na horizontal em vez de
   cortar colunas em telas pequenas; a tela de Chat empilha a lista de conversas acima do chat no celular
   em vez de espremer tudo; os filtros/botões da tela de Tarefas quebram linha em vez de vazar da tela;
   espaçamentos reduzidos em telas muito pequenas (abaixo de 480px).

## O que já vinha do projeto (mantido)

- Tipo de conta (Comum × Corporativo), tema claro/escuro, sistema de planos com limites diários de IA,
  aba de Chat com histórico, notificações do sino, foto de perfil.

---

## Passo a passo para subir (Render)

Este projeto é um app **Flask + banco de dados** (login, tarefas, IA). Isso **não roda no Netlify**,
porque o Netlify só hospeda sites estáticos (HTML/CSS/JS), sem Python nem banco de dados. O deploy
principal é sempre no **Render**.

1. Crie uma chave grátis da IA em **https://console.groq.com/keys** (login gratuito, sem cartão).
2. Suba a pasta `taskfinal/` para um repositório no GitHub (inclua o `render.yaml` que já está pronto).
3. No [render.com](https://render.com): **New +** → **Blueprint** → conecte o repositório e selecione
   o `render.yaml`. Isso cria **de uma vez**: o serviço web e o banco Postgres gratuito, já conectados
   (a variável `DATABASE_URL` é preenchida automaticamente).
   - Se preferir criar manualmente em vez de usar o Blueprint: **New +** → **Web Service**, Build Command
     `pip install -r requirements.txt`, Start Command `gunicorn app:app`.
4. Quando o Render pedir, cole sua `GROQ_API_KEY` (é a única variável marcada como secreta que você
   precisa preencher manualmente — as demais já vêm definidas no `render.yaml`).
5. Clique em **Deploy**. O link gerado (`https://taskai-xxxx.onrender.com`) já é o site funcionando.

### ⚠️ Sobre o banco gratuito do Render
O Postgres gratuito do Render **expira 30 dias após a criação** (é assim que o Render libera o plano
grátis — depois disso, ele para de aceitar conexões, mas os dados continuam existindo por um tempo até
serem apagados). Para uma apresentação de TCC isso raramente é problema, mas fique de olho na data se
for usar o mesmo banco por mais de um mês; se precisar, é só criar um banco novo no Render e apontar o
`DATABASE_URL` pra ele.

> Fotos de perfil e relatórios `.docx` gerados ficam salvos em disco enquanto o serviço estiver no ar,
> mas o plano gratuito do Render também pode limpar esses arquivos quando o serviço reinicia/dorme por
> inatividade — isso é normal e não afeta os dados do banco.

## Sobre o `index.html` para o Netlify

A pasta **`netlify-landing/`** tem uma página de entrada (vitrine) no mesmo estilo visual do TaskAI,
com um botão "Abrir o TaskAI":
1. Depois de publicar no Render, copie o link gerado (ex.: `https://taskai-seunome.onrender.com`).
2. Abra `netlify-landing/index.html`, ache `const APP_URL = "https://SEU-APP.onrender.com";` perto do
   final do arquivo, e troque pela sua URL real do Render.
3. Suba a pasta `netlify-landing/` no Netlify (arrastar e soltar em app.netlify.com funciona).

---

## Testando localmente (opcional)

```bash
cd taskfinal
pip install -r requirements.txt
# edite o arquivo .env e coloque sua chave da Groq em GROQ_API_KEY
python app.py
```
Acesse `http://localhost:5000`. Sem configurar `DATABASE_URL`, o app usa SQLite local automaticamente.

---

## Como funcionam os planos (resumo técnico rápido)

| | Comum — Grátis | Corporativo — Grátis | Pro mensal (demo) | Pro anual (demo) |
|---|---|---|---|---|
| Mensagens de IA/dia | 15 | 60 | Ilimitado | Ilimitado |
| Funcionários na equipe | — | até 3 | Ilimitado | Ilimitado |
| Relatório .docx (texto + planilha + gráficos) | pessoal | pessoal + equipe | pessoal + equipe | pessoal + equipe |
| Preço exibido | R$ 0 | R$ 0 | R$ 29,90/mês | R$ 23,92/mês (R$ 287,04/ano) |

Esses números são configuráveis nas variáveis de ambiente `AI_LIMIT_COMUM`, `AI_LIMIT_CORP_FREE`,
`FREE_EMPLOYEE_LIMIT`, `PRO_PRICE_MONTHLY` e `PRO_ANNUAL_DISCOUNT_PCT`.

Qualquer conta pode ativar o "Pro" (mensal ou anual) pela página **Planos** — é um interruptor de
demonstração no banco de dados (`user.plan` e `user.plan_cycle`), sem cobrança real, pensado para você
liberar tudo na hora da apresentação sem se preocupar com limites.

---

## Arquivos que mudaram nesta rodada

```
taskfinal/app.py                       → Groq no lugar do Gemini, plano anual, relatório com gráficos/planilha
taskfinal/requirements.txt             → + matplotlib (gráficos do relatório)
taskfinal/render.yaml                  → Groq + banco Postgres gratuito do Render
taskfinal/.env / .env.example          → variáveis da Groq e do plano anual
taskfinal/static/css/style.css         → toggle mensal/anual, correções de responsividade mobile
taskfinal/static/css/accessibility.css → NOVO — estilos do painel de acessibilidade
taskfinal/static/js/accessibility.js   → NOVO — lógica do painel de acessibilidade
taskfinal/templates/base.html          → inclui acessibilidade, aria-labels, skip-link
taskfinal/templates/login.html         → inclui acessibilidade, labels associados aos campos
taskfinal/templates/planos.html        → toggle mensal/anual com desconto
taskfinal/templates/settings.html      → aba "Acessibilidade", mostra ciclo do plano Pro
taskfinal/templates/equipe.html        → aria-label no botão de remover funcionário
taskfinal/templates/tasks.html         → aria-label nos botões de editar/excluir tarefa
taskfinal/templates/chat.html          → texto "TaskAI · Groq"
taskfinal/templates/dashboard.html     → texto "TaskAI · Groq"
```


---

## Atualização — planos, acessibilidade e senha

- **Planos:** Básico (Pessoal, gratuito), Especial (Pessoal) e PRO (Corporativo), com abas Mensal/Anual,
  preço original riscado ao lado do preço com desconto e benefícios em verde (✓) / vermelho riscado (✕).
  - Especial: R$ 35,80/mês · R$ 390,50 → R$ 273,00/ano
  - PRO: R$ 48,90/mês · R$ 586,00 → R$ 410,76/ano
  - Valores configuráveis por variáveis de ambiente: `ESPECIAL_PRICE_MONTHLY`, `ESPECIAL_ANNUAL_OLD`,
    `ESPECIAL_ANNUAL_PRICE`, `PRO_PRICE_MONTHLY`, `PRO_ANNUAL_OLD`, `PRO_ANNUAL_PRICE`
    (as antigas `PRO_ANNUAL_DISCOUNT_PCT` não são mais usadas).
  - `users.plan` agora aceita `free | especial | pro`. Especial só para contas Pessoais e PRO só para Empresariais.
  - Mensagens de IA ilimitadas: Especial e PRO. Relatório das tarefas: Especial e PRO (conta pessoal gratuita não gera relatório).
- **Acessibilidade:** o botão "Abrir painel de acessibilidade agora" (Configurações) agora abre o painel
  (`window.openA11yPanel()`).
- **Senhas:** `static/js/pw-eye.js` coloca o olho de mostrar/ocultar em todos os campos de senha (login, cadastro,
  alterar senha, excluir conta), inclusive campos criados depois.


---

## Deploy no Render (v5) — passo a passo

1. Suba a pasta `taskfinal/` para um repositório no GitHub (o `.env` **não** vai junto: já está no `.gitignore`;
   este pacote já vem **sem chave**).
2. No Render: **New + → Blueprint** e escolha o repositório. Ele lê o `render.yaml` e cria o site + o banco.
3. Abra o serviço `taskai` → **Environment** e preencha `GROQ_API_KEY` (chave gratuita em console.groq.com/keys).
   `SECRET_KEY` e `DATABASE_URL` são preenchidas automaticamente.
4. Teste em `https://SEU-APP.onrender.com/healthz` → deve responder `{"status":"ok"}`.

### Correções desta versão (erro "depois de um tempo")
- **Driver do banco:** o SQLAlchemy 2.1 passou a usar `psycopg` (v3) por padrão e o projeto usa `psycopg2`;
  o app agora força `postgresql+psycopg2://` e o `requirements.txt` fixa `SQLAlchemy<2.1`.
- **Conexões que caem:** o Postgres do Render derruba conexões ociosas. Adicionados `pool_pre_ping`, `pool_recycle`
  e keepalive — antes, a 1ª requisição após um período parado dava erro 500.
- **Sessão órfã:** se o banco for recriado/expirar, o cookie antigo não causa mais erro 500 (volta para o login).
- **Erros amigáveis:** handlers para 500/404/413 com rollback automático da sessão do banco.
- **Relatórios .docx:** não acumulam mais no disco (são gerados, enviados e apagados) e a geração é serializada
  (matplotlib não é thread-safe).
- **Gunicorn:** `--workers 1 --threads 8 --timeout 120` (uso de memória ~250 MB, cabe nos 512 MB do plano Free;
  o timeout padrão de 30 s derrubava a requisição quando a IA demorava).
- **Foto de perfil:** o disco do plano Free é apagado a cada reinício; se a foto sumir, aparece a inicial do nome
  em vez de imagem quebrada.

### Limites do plano Free do Render (não dá para resolver no código)
- O site "dorme" após ~15 min sem acesso; o 1º acesso depois disso leva até ~1 min.
- O **Postgres Free expira 30 dias após criado** — faça upgrade ou troque por Neon/Supabase (ver `render.yaml`).
- Fotos de perfil enviadas não persistem entre reinícios.


---

## v7 — correção da IA e planos só informativos

**Por que a IA parou de responder:** a Groq desativou o modelo `llama-3.3-70b-versatile` em 16/08/2026 (o modelo
que o projeto usava). Toda chamada passou a voltar erro 400. Continua sendo a **mesma API da Groq**
(`https://api.groq.com/openai/v1`), só mudou o modelo.

- Modelo padrão agora: `openai/gpt-oss-120b` (substituto recomendado pela Groq). Variável `GROQ_MODEL` para trocar.
- Se `GROQ_MODEL` (no `.env` ou no Render) ainda apontar para um modelo desativado, o app troca sozinho para o novo.
- Se o modelo configurado deixar de existir no futuro, o app consulta `GET /models` da Groq e escolhe outro disponível.
- O `.env` agora é lido pelo caminho do próprio `app.py` (antes dependia da pasta de onde o app era iniciado).
- Chave com aspas/espaços sobrando é aceita; os erros da Groq aparecem com o motivo real (401, 403, 429, rede...).
- **IA sem limites:** removido o limite diário de mensagens, o limite de tamanho curto (agora até 3000 tokens por
  resposta, `AI_MAX_TOKENS`) e as restrições do prompt (ela responde sobre qualquer assunto, no tamanho necessário).
- **Benefícios dos planos são só texto:** nada é bloqueado na prática (mensagens, relatório, funcionários e equipes
  ficam liberados em qualquer plano). A página Planos continua mostrando a comparação escrita.
- Variáveis removidas: `AI_LIMIT_COMUM`, `AI_LIMIT_CORP_FREE`, `FREE_EMPLOYEE_LIMIT`.
