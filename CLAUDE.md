# Agente InHire — CLAUDE.md

> Lido automaticamente no início de cada sessão. Mantenha atualizado.

---

## O que é este projeto

**Eli** — agente de IA que automatiza recrutamento via Slack, conectando InHire (ATS) + Claude API + Redis.

**Stack:** FastAPI, Python 3.12, Anthropic SDK (claude-sonnet-4-20250514), Redis, Slack Events API, InHire REST API.

**Deploy:** `/var/www/agente-inhire/` no servidor `65.109.160.97`, porta 8100, reverse proxy Nginx, systemd service `agente-inhire`. Subdomínio: `agente.adianterecursos.com.br`.

**Tenant InHire:** `demo` (desenvolvimento, sem recrutadores reais).

---

## Mapa da arquitetura

```
app/
├── main.py                    # FastAPI lifespan, inicializa todos os serviços, cron scheduler (1h + 9h BRT)
├── config.py                  # Pydantic Settings via .env
├── services/
│   ├── inhire_auth.py         # JWT auth com retry + auto-refresh + asyncio lock
│   ├── inhire_client.py       # HTTP client para InHire API (~25 endpoints)
│   ├── slack_client.py        # Slack Web API (mensagens, botões, split de msgs longas)
│   ├── claude_client.py       # Claude API (prompt caching, tool use, extração, JD, shortlist)
│   ├── conversation.py        # Máquina de estados (FlowState) + persistência Redis (TTL 7d)
│   ├── user_mapping.py        # Mapeamento Slack user → InHire user + config por recrutador (Redis)
│   ├── learning.py            # Registro de decisões do recrutador
│   └── proactive_monitor.py   # Cron: briefing diário, SLA, pipeline parado, shortlist, follow-up
└── routers/
    ├── health.py              # GET /health
    ├── slack.py               # POST /slack/events + /slack/interactions (orquestrador, ~1000 linhas)
    ├── webhooks.py            # POST /webhooks/inhire (eventos do InHire + comemoração contratação)
    ├── chrome_extension.py    # POST /extension/analyze
    └── handlers/              # Módulos extraídos do slack.py (sessão 26)
        ├── helpers.py         # _send, _send_approval, _suggest_next_action, constantes
        ├── job_creation.py    # Briefing, draft, criação de vaga
        ├── candidates.py      # Triagem, shortlist, mover, reprovar
        ├── interviews.py      # Agendamento, carta oferta
        └── hunting.py         # Análise de perfil, busca LinkedIn, relatório
```

---

## Como o roteamento funciona

### Fluxo principal (DMs no Slack)

1. Slack envia evento → `slack.py:slack_events()` valida assinatura, deduplica, dispara `_handle_dm()` como asyncio task
2. `_handle_dm()` verifica onboarding → pega conversa do Redis → checa comandos globais (`cancelar`, `toggle comunicação`)
3. Despacha por estado via dict de handlers:

```python
handlers = {
    FlowState.IDLE: _handle_idle,                    # Tool use (Claude decide a ação)
    FlowState.COLLECTING_BRIEFING: _handle_briefing,  # Coleta info da vaga
    FlowState.WAITING_*_APPROVAL: _handle_waiting_approval,  # Espera clique no botão
    FlowState.MONITORING_CANDIDATES: _handle_monitoring,      # Delega pro _handle_idle
    FlowState.SCHEDULING_INTERVIEW: _handle_scheduling_input, # Coleta dados da entrevista
    FlowState.CREATING_OFFER: _handle_offer_input,            # Coleta dados da oferta
}
```

4. `_handle_idle()` usa **Claude tool calling** (`detect_intent()`) para rotear — NÃO usa keywords

### Tools disponíveis (ELI_TOOLS em claude_client.py)

**Layer 1 — Funcional:**
- `listar_vagas` → `_list_jobs()`
- `criar_vaga` → seta COLLECTING_BRIEFING
- `ver_candidatos` → `_check_candidates()` (foco: pessoas, scores, fit)
- `gerar_shortlist` → `_build_shortlist()` (ranking comparativo)
- `status_vaga` → `_job_status_report()` (foco: SLA, pipeline, métricas)
- `busca_linkedin` → `_generate_linkedin_search()`
- `analisar_perfil` → `_analyze_profile()`
- `mover_candidatos` → carrega candidatos → shortlist (inclui sem score) → aprovação → `_move_approved_candidates()` (batch)
- `reprovar_candidatos` → carrega candidatos → filtra não-selecionados → aprovação → `_reject_candidates()` (reason=enum, comment=devolutiva)
- `ver_memorias` → `_show_memories()` (padrões, config, insights semanais)
- `conversa_livre` → `claude.chat()` direto

**Layer 1 — Funcional (resolvido sessão 33):**
- `agendar_entrevista` → `_start_scheduling()` (provider: manual, sem calendário)
- `carta_oferta` → `_start_offer_flow()` (template + ClickSign)

---

## Armadilhas da API InHire

### NUNCA usar

| Endpoint | Problema | Alternativa |
|---|---|---|
| `GET /jobs` | Full table scan + N+1 query → **502 timeout** | `POST /jobs/paginated/lean` com `{"limit": N}` |
| `GET /applications` | Retorna vazio para candidatos de hunting | `GET /job-talents/{jobId}/talents` |
| `PATCH /applications/{id}` | Não aceita stageId, não funciona pra hunting | Ver endpoints corretos abaixo |
| `GET /scorecards`, `GET /users`, `GET /team` | 403 — service account sem permissão | Sem alternativa |

### Endpoints CORRETOS (confirmados com André, dev InHire)

| Ação | Endpoint correto |
|---|---|
| Listar vagas | `POST /jobs/paginated/lean` (retorna `{results, startKey}`) |
| Listar candidatos | `GET /job-talents/{jobId}/talents` (hunting + orgânicos) |
| Adicionar talento | `POST /job-talents/{jobId}/talents` (aceita `files: [{id, fileCategory, name}]`) |
| Criar registro de CV | `POST /files` com `{id, category: "resumes", name}` → metadata do arquivo |
| Mover de etapa | `POST /job-talents/talents/{jobTalentId}/stages` com `{stageId}` |
| Mover em lote | `POST /job-talents/talents/stages/batch` |
| Reprovar | `POST /job-talents/talents/{jobTalentId}/statuses` com `{status: "rejected"}` |
| Reprovar em lote | `POST /job-talents/talents/statuses/batch` |
| Agendar entrevista | `POST /job-talents/appointments/{jobTalentId}/create` |
| Carta oferta | `POST /offer-letters` (jobTalentId formato: `{jobId}*{talentId}`) |
| Registrar webhook | `POST /integrations/webhooks` (**obrigatório:** `"rules": {}`) |

### Bugs conhecidos da API

- Webhook payload **não tem campo de tipo de evento** — detectar pela presença de campos
- `userName` no webhook é quem cadastrou, **não** o candidato
- `GET /integrations/webhooks` retorna `[]` mesmo com webhooks registrados
- Screening só funciona para candidatos orgânicos (inscrição via formulário)

---

## Regras de desenvolvimento

### SEMPRE fazer

- Ler `DIARIO_DO_PROJETO.md` para contexto de decisões passadas antes de mudar algo
- Usar `POST /jobs/paginated/lean` para listar vagas (nunca `GET /jobs`)
- Usar `GET /job-talents/{jobId}/talents` para candidatos (nunca `GET /applications`)
- Enviar `"rules": {}` ao registrar webhooks
- Testar com o tenant `demo`
- Manter tom do Eli (AGENT_BEHAVIOR_GUIDE.md) em todas as mensagens
- Atualizar este CLAUDE.md quando implementar algo relevante
- Atualizar DIARIO_DO_PROJETO.md ao final de cada sessão

### NUNCA fazer

- Usar `GET /jobs` (causa 502)
- Expor jargão técnico ao recrutador (endpoint, webhook, JWT, 403, 500)
- Executar ações sem aprovação explícita (5 pontos de pausa: publicar vaga, mover candidatos, reprovar, carta oferta, comunicar candidatos)
- Inventar dados sobre candidatos
- Ignorar erros 502 — o InHire tem endpoints que fazem full scan e morrem

---

## Endpoints corrigidos (Sessão 9)

O `inhire_client.py` foi corrigido — todos os métodos agora usam os endpoints corretos:
- `move_candidate(job_talent_id, stage_id)` → `POST /job-talents/talents/{id}/stages`
- `move_candidates_batch(stage_id, ids)` → `POST /job-talents/talents/stages/batch`
- `reject_candidate(job_talent_id, reason)` → `POST /job-talents/talents/{id}/statuses`
- `bulk_reject(ids, reason)` → `POST /job-talents/talents/statuses/batch` (fallback individual)

Tools `mover_candidatos` e `reprovar_candidatos` agora são **Layer 1 (funcionais)** no slack.py.

---

## Features pendentes de terceiros

| Feature | Bloqueio | Quem resolve | Status |
|---|---|---|---|
| Agendamento de entrevistas | ~~Service account sem calendário~~ | ~~André~~ | ✅ Resolvido (provider: manual) |
| Mover candidatos via API | ~~Endpoints errados~~ | ~~Corrigido sessão 9~~ | ✅ Corrigido |
| Reprovar em lote via API | ~~Endpoints errados~~ | ~~Corrigido sessão 9~~ | ✅ Corrigido |
| InTerview (WhatsApp) | Sem API pública | InHire | Sem previsão |
| Busca full-text no Banco de Talentos | API não é pública | InHire | Sem previsão |

---

## Melhorias arquiteturais

| # | Melhoria | Status | Sessão |
|---|---|---|---|
| 1 | **Prompt caching** — system prompt estático cacheado via `cache_control: ephemeral` | ✅ | 7 |
| 2 | **Tool use nativo** — `detect_intent()` com `ELI_TOOLS`, substitui keyword matching | ✅ | 7 |
| 3 | **Resumo de conversa** — a cada 20 msgs, resumir em 5 linhas, injetar após 2h de inatividade | ✅ | 7 |
| 4 | **Monitor paralelo** — `asyncio.gather()` no ProactiveMonitor | ✅ | 7 |
| 5 | **Briefing diário** — cron 9h BRT, resumo de vagas ativas, só envia se há novidades | ✅ | 25 |
| 6 | **Horário comercial** — mensagens proativas só 8h-19h BRT seg-sex | ✅ | 25 |
| 7 | **Escalonamento de alertas** — pipeline parado 3d→7d→14d com TTLs progressivos | ✅ | 25 |
| 8 | **Dedup eventos Redis** — `SET NX EX 300` atômico, fallback em memória | ✅ | 25 |
| 9 | **Lock de concorrência** — `SET NX EX 30` por user_id, retry loop 10s | ✅ | 26 |
| 10 | **Comemoração contratação** — webhook detecta stage "Contratado", envia celebração | ✅ | 26 |
| 11 | **Limite proativo 3/dia** — contador Redis por dia, config por recrutador | ✅ | 26 |
| 12 | **Fila fora horário** — Redis list, flush no próximo horário comercial | ✅ | 26 |
| 13 | **Config por recrutador** — 8 campos em user_mapping (horário, limite, threshold) | ✅ | 26 |
| 14 | **Follow-up entrevista** — detecta candidato 3d+ em etapa entrevista | ✅ | 26 |
| 15 | **Refatoração slack.py** — 2101→1008 linhas, 5 módulos em handlers/ | ✅ | 26 |
| 16 | **Recrutador inativo** — alerta 2d/5d/10d com tom progressivo | ✅ | 29 |
| 17 | **Candidato excepcional** — score >= 4.5 → notificação imediata | ✅ | 29 |
| 18 | **Horário configurável** — _is_business_hours usa config por recrutador | ✅ | 29 |
| 19 | **Tier 4 stop** — após 21d, para de insistir (só briefing) | ✅ | 29 |
| 20 | **Tool ver_memorias** — recrutador vê padrões aprendidos, config e contexto ativo | ✅ | 30 |
| 21 | **Registro utilidade alertas** — salva tipo/timestamp de cada alerta, infere resposta em 30min | ✅ | 30 |
| 22 | **Consolidação semanal (mini KAIROS)** — cron seg 9:30 BRT, Claude resume padrões em 3 frases | ✅ | 30 |
| 23 | **Agendamento funcional** — provider:manual, sem calendário, registra no InHire | ✅ | 33 |
| 24 | **Carta oferta funcional** — template + ClickSign + aprovação + envio ao candidato | ✅ | 33 |

---

## Context7 (documentação atualizada de bibliotecas)

MCP server `context7` configurado em `.mcp.json`. Busca docs atualizadas direto dos repos oficiais.

**Quando usar:** Sempre que trabalhar com qualquer uma destas libs, adicione "use context7" no prompt:
- `anthropic` (SDK Python) — especialmente para tool use, cache_control, streaming
- `fastapi` — routers, lifespan, middleware
- `redis-py` — comandos, pub/sub, pipelines
- `apscheduler` — AsyncIOScheduler, triggers, job stores
- `httpx` — async client, redirects, streaming
- `pydantic` — BaseSettings, validators, model_config

**Exemplo:** "use context7 — como usar cache_control no SDK anthropic python?"

---

## Credenciais (referência rápida)

| Serviço | Detalhe |
|---|---|
| Servidor | `ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97` |
| InHire API | `https://api.inhire.app` — Tenant: `demo` — Auth: `POST https://auth.inhire.app/login` |
| Slack Bot | Token no `.env` do servidor |
| Claude | Modelo: `claude-sonnet-4-20250514` — Key no `.env` |
| Redis | `redis://localhost:6379/2` |
