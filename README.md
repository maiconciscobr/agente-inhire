# Eli — Agente de Recrutamento IA

Agente que automatiza o recrutamento operacional via Slack, conectando InHire (ATS) + Claude (IA) + Redis.

O recrutador nunca sai do Slack. O Eli cuida do resto. Quando não consegue fazer algo, guia o recrutador com passo a passo e link direto pro InHire.

---

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | FastAPI (Python 3.12) |
| IA | Anthropic Claude Sonnet 4 (SDK Python) |
| ATS | InHire REST API (JWT auth, tenant `demo`) |
| Interface | Slack Events API + Block Kit (botões) |
| Persistência | Redis (conversas, users, alerts, learning) |
| Cron | APScheduler (monitoramento proativo a cada 1h) |
| MCP | Context7 (docs atualizadas de libs) |
| Deploy | Hetzner VPS, Nginx reverse proxy, systemd, SSL |

---

## Arquitetura

```
Recrutador (Slack DM)
       │
       ▼
  FastAPI (/slack/events)
       │
       ├─→ Claude API (detect_intent → 13 tools)
       │        │
       │        ├─→ listar_vagas, criar_vaga, ver_candidatos...
       │        ├─→ guia_inhire (passo a passo quando não consegue)
       │        └─→ conversa_livre (fallback)
       │
       ├─→ InHire API (CRUD vagas, candidatos, mover, reprovar)
       │
       └─→ Redis (estado, resumos comprimidos, alertas)

InHire Webhooks ──→ FastAPI (/webhooks/inhire) ──→ Slack (notificações)

APScheduler (1h) ──→ ProactiveMonitor (paralelo) ──→ Slack (SLA, pipeline)
```

---

## Mapa de arquivos

```
app/
├── main.py                    # Lifespan, inicializa serviços, cron
├── config.py                  # Pydantic Settings via .env
├── services/
│   ├── claude_client.py       # Prompt caching, 13 tools (ELI_TOOLS), detect_intent()
│   ├── inhire_auth.py         # JWT auto-refresh com lock e retry
│   ├── inhire_client.py       # HTTP client (~25 endpoints InHire)
│   ├── slack_client.py        # Mensagens, botões, split de msgs longas
│   ├── conversation.py        # FlowState (11 estados), resumo auto, Redis
│   ├── user_mapping.py        # Slack user → InHire user
│   ├── learning.py            # Registro de decisões do recrutador
│   └── proactive_monitor.py   # SLA, pipeline parado, shortlist auto (paralelo)
└── routers/
    ├── slack.py               # Handler principal (tool dispatch, handlers de estado, guias InHire)
    ├── webhooks.py            # Eventos do InHire (candidato novo, mudança de etapa)
    ├── health.py              # GET /health
    └── chrome_extension.py    # Análise de perfil via extensão
```

---

## Como funciona o roteamento

1. Mensagem chega → `_handle_dm()` valida onboarding e comandos globais
2. Estado `IDLE` → `detect_intent()` envia ao Claude com 13 tools definidas
3. Claude escolhe a tool → handler correspondente executa
4. Outros estados (COLLECTING_BRIEFING, WAITING_APPROVAL, etc.) têm handlers próprios

**Tools Layer 1 (11 funcionais):** listar_vagas, criar_vaga, ver_candidatos, gerar_shortlist, status_vaga, busca_linkedin, analisar_perfil, mover_candidatos, reprovar_candidatos, guia_inhire, conversa_livre

**Tools Layer 2 (2 — guia InHire com passo a passo):** agendar_entrevista, carta_oferta

---

## O que funciona hoje (15/15 testes PASS)

| Funcionalidade | Status |
|---|---|
| Onboarding (email → registro) | ✅ |
| Abertura de vaga (briefing → JD → aprovação → API) | ✅ |
| Triagem / shortlist comparativo | ✅ |
| Mover candidatos entre etapas (individual + batch) | ✅ |
| Reprovar em lote com devolutiva | ✅ |
| Upload de CV (PDF/DOCX → cadastra na vaga com CV anexado) | ✅ |
| Busca LinkedIn (strings booleanas) | ✅ |
| Análise de perfil (fit com vaga) | ✅ |
| Status/SLA da vaga | ✅ |
| Listar vagas | ✅ |
| Conversa livre | ✅ |
| Monitoramento proativo (SLA, pipeline, shortlist) | ✅ |
| Guia InHire (passo a passo com links) | ✅ |
| Agendar entrevistas | ⚠️ Guia InHire (service account sem calendário) |
| Carta oferta | ⚠️ Guia InHire (pendente validação) |

---

## O que o Eli não faz (e guia o recrutador)

Quando o recrutador pede algo que o Eli ainda não consegue fazer, ele explica como fazer no InHire com link:

- **Divulgação** — publicar em portais (LinkedIn, Indeed, Netvagas)
- **Formulário** — configurar perguntas de inscrição
- **Triagem IA** — definir critérios de avaliação automática
- **Scorecard** — configurar kit de entrevista
- **Automações** — gatilhos e emails automáticos

Detalhes completos dos gaps: `API_GAPS_PARA_DEVS.md`

---

## Melhorias arquiteturais

| Melhoria | Descrição |
|---|---|
| Prompt caching | System prompt estático cacheado (cache_control: ephemeral, 5 min TTL) |
| Tool use nativo | Claude decide a ação via 13 tools — sem keywords |
| Resumo de conversa | A cada 20 msgs gera resumo; após 2h injeta resumo comprimido |
| Monitor paralelo | asyncio.gather() checa todos os recrutadores simultaneamente |
| Teste inteligente | Claude como juiz semântico + adaptativo (detecta estados pendentes) |

---

## Testes

```bash
# Agente inteligente de testes (Claude como juiz)
cd /var/www/agente-inhire
ANTHROPIC_API_KEY=sk-... python3 test_agent.py
```

15 cenários com avaliação semântica. O teste se adapta automaticamente quando o Eli fica em estado de aprovação.

---

## Documentação do projeto

| Documento | O que cobre |
|---|---|
| `PITCH.md` | Documento de venda para stakeholders, recrutadores e devs |
| `API_GAPS_PARA_DEVS.md` | 11 gaps da API InHire priorizados para o time de dev |
| `CLAUDE.md` | Referência técnica (lido automaticamente pelo Claude) |
| `DIARIO_DO_PROJETO.md` | Histórico completo (22 sessões) |
| `MAPEAMENTO_API_INHIRE.md` | Todos os endpoints testados, bugs e workarounds |
| `AGENT_BEHAVIOR_GUIDE.md` | Persona Eli, tom, proatividade e limites |
| `Agente InHire — Especificação Técnica.md` | Status de implementação por etapa |
| `Agente InHire — Trabalho do Recrutador.md` | 18 tarefas humanas e pontos de pausa |
| `Agente InHire — Simulação de Interação.md` | Dia a dia no Slack com exemplos reais |

---

## Armadilhas da API InHire

- **NUNCA** usar `GET /jobs` (causa 502). Usar `POST /jobs/paginated/lean`
- **NUNCA** usar `GET /applications` (vazio para hunting). Usar `GET /job-talents/{jobId}/talents`
- Rejection reason é **enum** (overqualified, underqualified, location, other), não texto livre
- Webhook payload não tem tipo de evento — detectar pelos campos
- `POST /integrations/webhooks` exige `"rules": {}` (bug da API)

---

## Setup

```bash
# Servidor
ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97

# Logs
journalctl -u agente-inhire -f

# Restart
systemctl restart agente-inhire

# Health check
curl https://agente.adianterecursos.com.br/health

# Testes
cd /var/www/agente-inhire && ANTHROPIC_API_KEY=sk-... python3 test_agent.py
```

---

## Pendências

- **API InHire** — 11 gaps documentados em `API_GAPS_PARA_DEVS.md` (4 críticos, 3 altos, 4 médios)
- **Appointments** — service account sem calendário (aguardando Andre)
- **Deduplicação de eventos** — deveria usar Redis (atualmente em memória)
- **Lock de concorrência** — sem lock por conversa
- **Features do Guide** — briefing diário, escalonamento de alertas, horário comercial

> **Última atualização:** 4 de abril de 2026 — Sessão 22
