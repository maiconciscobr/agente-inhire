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
│   ├── inhire_client.py       # HTTP client para InHire API (~55 endpoints)
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
- `ver_candidatos` → `_check_candidates()` (foco: pessoas, scores, fit) — aceita `stage_filter` para filtrar por etapa
- `gerar_shortlist` → `_build_shortlist()` (ranking comparativo)
- `status_vaga` → `_job_status_report()` (foco: SLA, pipeline, métricas, funil visual, previsão IA)
- `busca_linkedin` → `_generate_linkedin_search()`
- `analisar_perfil` → `_analyze_profile()` — extrai dados + botão "Adicionar à vaga?" com dedup
- `mover_candidatos` → carrega candidatos → shortlist (inclui sem score) → aprovação → `_move_approved_candidates()` (batch)
- `reprovar_candidatos` → carrega candidatos → filtra não-selecionados → aprovação → `_reject_candidates()` (reason=Haiku classifica motivo, comment=devolutiva personalizada por candidato)
- `ver_memorias` → `_show_memories()` (padrões, config, insights semanais)
- `conversa_livre` → resposta direta do `detect_intent` (tool_choice: auto) ou `claude.chat()` fallback

**Layer 1 — Funcional (resolvido sessão 33):**
- `agendar_entrevista` → `_start_scheduling()` (provider: manual, sem calendário)
- `carta_oferta` → `_start_offer_flow()` (template + ClickSign)

**Layer 1 — Funcional (resolvido sessão 34):**
- `buscar_talentos` → `_search_talents()` (Typesense full-text, 86k+ talentos, scoped key 24h)

**Layer 1 — Funcional (resolvido sessão 36):**
- `gerenciar_rotina` → `_handle_routine()` (criar, listar, cancelar rotinas recorrentes via linguagem natural)

**Layer 1 — Funcional (resolvido sessão 38):**
- `enviar_whatsapp` → `_handle_send_whatsapp()` (mensagem livre + oferta pós-reprovação e agendamento)

**Layer 1 — Funcional (resolvido sessão 40):**
- `comparar_vagas` → `_compare_jobs()` (ranking de vagas ativas por velocidade, SLA, candidatos)

**Layer 1 — Funcional (resolvido sessão 42):**
- `smart_match` → `_smart_match()` (busca IA no banco de talentos 86k+ via `gen_filter_job_talents` + screening automático + tags)
- `processar_linkedin` → `_process_linkedin_profiles()` (recrutador cola URLs → dedup → cria talento → vincula à vaga → BrightData extrai perfil → screening)

**Layer 1 — Funcional (resolvido sessão 43):**
- `duplicar_vaga` → `_duplicate_job()` (copia pipeline, settings, descrição)
- `avaliar_entrevista` → `_evaluate_interview()` (recrutador dita feedback → Claude parseia → preenche scorecard → IA gera parecer)
- `enviar_teste` → `_send_test()` (DISC, formulário de triagem, ou qualquer form por email)
- `pesquisa_candidato` → `_handle_nps_survey()` (enviar pesquisa NPS / ver métricas de satisfação)

**Fluxos enriquecidos (sessão 43):**
- `configurar_vaga` → agora também gera formulário de inscrição com IA (`POST /forms/ai/generate-subscription-form`)
- `agendar_entrevista` → envia kit de entrevista automaticamente após agendar (CV + scorecard + roteiro)
- `criar_vaga` → mostra templates disponíveis se existirem (`GET /jobs/templates`)
- `carta_oferta` → busca variáveis obrigatórias de cada template (`GET /offer-letters/templates/{id}`)

---

## Armadilhas da API InHire

### NUNCA usar

| Endpoint | Problema | Alternativa |
|---|---|---|
| `GET /jobs` | Full table scan + N+1 query → **502 timeout** | `POST /jobs/paginated/lean` com `{"limit": N}` |
| `GET /applications` | Retorna vazio para candidatos de hunting | `GET /job-talents/{jobId}/talents` |
| `PATCH /applications/{id}` | Não aceita stageId, não funciona pra hunting | Ver endpoints corretos abaixo |
| `GET /scorecards` | 403 — service account sem ability `ScorecardJob` | `GET /forms/scorecards/jobs/{jobId}` funciona! André vai liberar ability |
| `GET /users` (api.inhire.app) | 403 — rota no domínio errado | `GET https://auth.inhire.app/users` funciona (200) |
| `GET /talents/{id}/files` | 404 — rota não existe | `POST /files/search` com `{id, fileCategory}` |

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
| Scoped key Typesense | `GET /search-talents/security/key/talents?engine=typesense` (24h TTL, read-only) |
| Buscar talento por email | `GET /talents/email/{email}` (retorna talento ou 404) |
| Buscar talento por LinkedIn | `GET /talents/linkedin/{username}` (retorna talento ou 404) |
| Buscar talentos por IDs | `POST /talents/ids` com `{ids: [...]}` |
| Criar talento | `POST /talents` com `{name, linkedinUsername}` |
| Busca IA talentos | `POST /search-talents/ai/generate-job-talent-filter` com `{jobId, query}` |
| Listar talentos paginado | `POST /talents/paginated` com `{limit, startKey}` |
| Sugestão de reprovação | `POST /job-talents/reproval/suggestion/{jobTalentId}` |
| Atualizar entrevista | `PATCH /job-talents/appointments/{id}/patch` |
| URL documento oferta | `GET /offer-letters/document/{offerId}` |
| Settings oferta | `GET /offer-letters/settings` |
| Listar users InHire | `GET https://auth.inhire.app/users` (**domínio auth**, não api) |
| Buscar arquivo por ID | `POST /files/search` com `{id, fileCategory}` |
| Scorecard da vaga | `GET /forms/scorecards/jobs/{jobId}` |
| Criar scorecard | `POST /forms/scorecards/jobs` com `{jobId, skillCategories}` |
| Formulário da vaga | `GET /forms/job-id/{jobId}` |
| Atualizar formulário | `PATCH /forms/{formId}` |
| Divulgar vaga | `POST /job-posts/pages` com `{jobId, careerPageId, activeJobBoards}` |
| Integrações disponíveis | `GET /integrations` |
| Timeline do candidato | `GET /job-talents/{jobTalentId}/timeline` |
| Screening manual | `POST /job-talents/{jobTalentId}/screening/manual` |
| Análise de CV | `POST /job-talents/resume/analyze/{jobTalentId}` |
| Criar automação | `POST /workflows/automations` |
| Tags em batch | `POST /job-talents/tags/add/batch` |
| Busca IA talentos | `POST /search-talents/ai/generate-job-talent-filter` |
| Duplicar vaga | `POST /jobs/duplicate` |
| Templates de vaga | `GET /jobs/templates` |
| Stages customizados | `POST /jobs/stages` + `PATCH /jobs/stages` |
| Gerar formulário IA | `POST /forms/ai/generate-subscription-form` |
| Kit de entrevista | `GET /forms/scorecards/interview-kit-fill/{id}/jobTalent/{jt}` |
| Avaliar entrevista | `POST /forms/scorecards/jobTalent/{jt}/{interviewId}` |
| Feedback IA scorecard | `POST /forms/ai/generate-feedback` |
| Enviar DISC | `POST /forms/comms/disc/send/email` |
| Enviar formulário email | `POST /forms/{typeformId}/comms/send/email` |
| Pesquisa NPS | `POST /forms/surveys` + `GET /forms/surveys/jobs/{jobId}/metrics` |
| Reagir candidato | `POST /job-talents/reaction/{id}` |
| Smart CV | `GET/POST /talents/{id}/smartcv` (descoberto, a testar) |
| Template oferta detail | `GET /offer-letters/templates/{id}` |

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
| ~~InTerview (WhatsApp)~~ | ~~Em desenvolvimento por outro time~~ | ~~InHire~~ | ✅ Resolvido (sessão 38) — endpoint 502 no tenant demo (credenciais Meta pendentes) |
| ~~Busca full-text no Banco de Talentos~~ | ~~Endpoint já existia~~ | ~~André Gärtner~~ | ✅ Resolvido (sessão 34) |

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
| 25 | **Email para candidatos** — base path /comms/, emailProvider:amazon (SES) | ✅ | 33 |
| 26 | **Busca full-text talentos** — Typesense scoped key + busca direta, 86k+ talentos | ✅ | 34 |
| 27 | **Rotinas dinâmicas** — RoutineService (CRUD Redis + APScheduler), 4 tipos, linguagem natural | ✅ | 36 |
| 28 | **UX conversacional** — remover keywords expostas, briefing por intent via Claude | ✅ | 37 |
| 29 | **WhatsApp integration** — envio via API InHire, tool livre + oferta pós-reprovação e agendamento | ✅ | 38 |
| 30 | **Instrumentação de custo** — `_log_usage()` em todas as chamadas Claude, JSON com tokens/custo/latência | ✅ | 39 |
| 31 | **tool_choice auto** — elimina double-call no `conversa_livre`, detect_intent responde direto | ✅ | 39 |
| 32 | **Multi-modelo** — Haiku para `classify_briefing_reply` e `parse_routine_request` (3x mais barato) | ✅ | 39 |
| 33 | **Compressão de tools** — 8 de 15 descriptions encurtadas (~600-900 tokens/chamada economizados) | ✅ | 39 |
| 34 | **Busca por email/LinkedIn** — `get_talent_by_email`, `get_talent_by_linkedin`, `get_talents_by_ids`, `list_talents_paginated` | ✅ | 40 |
| 35 | **Filtro por etapa** — `ver_candidatos` aceita `stage_filter`, Claude extrai da linguagem natural | ✅ | 40 |
| 36 | **Rejeição inteligente** — Haiku classifica motivo (overqualified/underqualified/location/other) por candidato | ✅ | 40 |
| 37 | **Devolutiva personalizada** — cada candidato recebe mensagem individual com nome, etapa, pontos fortes | ✅ | 40 |
| 38 | **Sugestão de reprovação** — `get_reproval_suggestion()` consulta InHire antes de gerar devolutiva própria | ✅ | 40 |
| 39 | **URL documento oferta** — mostra link do PDF gerado ao criar carta oferta | ✅ | 40 |
| 40 | **Seleção de template** — múltiplos templates: match por nome ou número, fallback pro primeiro | ✅ | 40 |
| 41 | **Data de início na oferta** — coleta e envia `dataInicio` nos `templateVariableValues` | ✅ | 40 |
| 42 | **Remarcar entrevista** — `update_appointment()` via PATCH sem cancelar | ✅ | 40 |
| 43 | **Lembrete entrevista** — APScheduler agenda Slack 2h antes do `startDateTime` | ✅ | 40 |
| 44 | **Analisar → adicionar** — perfil analisado → extrai dados (Haiku) → botão → dedup email/LinkedIn → cria | ✅ | 40 |
| 45 | **Devolutiva pós-fechamento** — webhook contratação → notifica sobre candidatos remanescentes | ✅ | 40 |
| 46 | **Notificação de etapa** — webhook stage change → email ao candidato (opt-in `auto_stage_notification`) | ✅ | 40 |
| 47 | **Funil de conversão** — barra visual █░ por etapa no relatório de status | ✅ | 40 |
| 48 | **Previsão de fechamento** — Haiku estima quando vaga fecha baseado em dados do funil | ✅ | 40 |
| 49 | **Comparação de vagas** — tool `comparar_vagas`, ranking por velocidade (cand/dia) | ✅ | 40 |
| 50 | **Relatório semanal** — cron seg 9:30 BRT, consolida todas as vagas ativas com SLA e risco | ✅ | 40 |
| 51 | **Mapeamento de gaps** — 95 funcionalidades mapeadas, 15 endpoints descobertos no código-fonte InHire | ✅ | 40 |
| 52 | **Config triagem IA pós-vaga** — `PATCH /jobs/{id}` com `screeningSettings` + `resumeAnalyzer` auto | ✅ | 41 |
| 53 | **Config scorecard pós-vaga** — `POST /forms/scorecards/jobs` com skills do briefing | ✅ | 41 |
| 54 | **Divulgação em portais** — `GET /integrations` + `POST /job-posts/pages` (LinkedIn, Indeed, Netvagas) | ✅ | 41 |
| 55 | **Timeline do candidato** — `GET /job-talents/{id}/timeline` (histórico cronológico completo) | ✅ | 41 |
| 56 | **Tempo médio por etapa** — calculado a partir do timeline no relatório de status | ✅ | 41 |
| 57 | **Screening on-demand** — `POST /job-talents/{id}/screening/manual` (triagem pra hunting!) | ✅ | 41 |
| 58 | **Análise de CV detalhada** — `GET /job-talents/{id}/resume-analysis` (score por critério + evidência) | ✅ | 41 |
| 59 | **Automações de vaga** — `POST /workflows/automations` (CRUD: trigger + action + conditions) | ✅ | 41 |
| 60 | **Tags em candidatos** — `POST /job-talents/tags/add/batch` + DELETE batch | ✅ | 41 |
| 61 | **Memória hierárquica** — extract_facts (Haiku) + perfil recrutador + session summaries (Redis 4 níveis) | ✅ | 41 |
| 62 | **Injeção de contexto hierárquica** — perfil + fatos + sessão anterior + insight semanal no system prompt | ✅ | 41 |
| 63 | **Smart Match** — tool `smart_match`, busca IA no banco 86k+ (`gen_filter_job_talents` + fallback Typesense) + screening + tags | ✅ | 42 |
| 64 | **Processar LinkedIn** — tool `processar_linkedin`, cola URLs → dedup → cria talento → vincula vaga → BrightData extrai → screening | ✅ | 42 |
| 63 | **TTLs em todas as keys Redis** — decisões 180d, users 365d, insights 10d, interaction 30d, threshold 90d | ✅ | 41 |
| 64 | **Atomicidade Redis** — pipeline atômico no counter, `set(nx=True, ex=ttl)` nos alertas | ✅ | 41 |
| 65 | **Limpeza de contexto** — `conv.context` limpa 18 keys ao trocar de vaga ativa | ✅ | 41 |
| 66 | **Duplicar vaga** — `POST /jobs/duplicate` via tool `duplicar_vaga` | ✅ | 43 |
| 67 | **Avaliar entrevista via Slack** — feedback livre → Claude parseia → preenche scorecard + IA gera parecer | ✅ | 43 |
| 68 | **Enviar DISC/testes** — `POST /forms/comms/disc/send/email` + formulários por email | ✅ | 43 |
| 69 | **Pesquisa NPS** — `POST /forms/surveys` + `GET /forms/surveys/jobs/{id}/metrics` | ✅ | 43 |
| 70 | **Formulário IA pós-vaga** — `POST /forms/ai/generate-subscription-form` integrado em `configurar_vaga` | ✅ | 43 |
| 71 | **Kit de entrevista automático** — `GET /forms/scorecards/interview-kit-fill/{id}/jobTalent/{jt}` pós-agendamento | ✅ | 43 |
| 72 | **Templates de vaga** — `GET /jobs/templates` oferecidos ao criar vaga | ✅ | 43 |
| 73 | **Template oferta detalhado** — `GET /offer-letters/templates/{id}` com variáveis obrigatórias | ✅ | 43 |
| 74 | **Limpeza código morto** — removidos `list_applications`, `update_application`, `get_scorecards`, FlowStates orfãos | ✅ | 43 |
| 75 | **Migração proactive_monitor** — `list_applications` → `list_job_talents` (endpoint correto) | ✅ | 43 |

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
| Claude | Modelo principal: `claude-sonnet-4-20250514`, fast: `claude-haiku-4-5-20251001` — Key no `.env` |
| Redis | `redis://localhost:6379/2` |
