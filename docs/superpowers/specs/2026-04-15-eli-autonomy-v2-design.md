# Eli Autonomia v2 — Design Spec

**Data:** 2026-04-15
**Objetivo:** Transformar o Eli de assistente reativo em agente autônomo que acelera o time-to-fill, reduzindo de 13 para 3-5 pontos de aprovação conforme o modo escolhido.

---

## 1. Dois Modos de Operação

### Copiloto (padrão)

Eli faz tudo que pode automaticamente. Avisa o que fez. Só pede aprovação quando a ação tem **impacto externo ou envolve movimento de candidatos no pipeline**.

**5 pontos de aprovação:**

| # | Ação | Por que pede |
|---|---|---|
| 1 | Divulgar vaga em portais | Pode ter custo (job boards pagos) |
| 2 | Mover candidatos de etapa | Decisão de progressão no pipeline |
| 3 | Reprovar candidatos | Irreversível + marca empregadora |
| 4 | Enviar comunicação ao candidato (WhatsApp/email) | LGPD + tom de voz |
| 5 | Emitir carta oferta | Compromisso financeiro/jurídico |

**Faz sozinho e avisa (sem pedir):**
- Configura screening, scorecard, formulário IA pós-vaga
- Dispara Smart Match no banco de talentos
- Executa screening em candidatos de hunting
- Gera shortlist quando threshold é atingido
- Gera string de busca LinkedIn
- Cobra feedback pós-entrevista (follow-up progressivo)
- Pré-monta carta oferta quando candidato chega na etapa final
- Calcula métricas, tempo por etapa, previsão de fechamento
- Sugere próximo passo baseado no estado do pipeline

### Piloto Automático

Tudo do Copiloto, mais: divulga vagas automaticamente e move candidatos com score acima do threshold sem pedir.

**3 pontos de aprovação:**

| # | Ação | Por que pede |
|---|---|---|
| 1 | Reprovar candidatos | Irreversível + marca empregadora |
| 2 | Enviar comunicação ao candidato | LGPD + tom de voz |
| 3 | Emitir carta oferta | Compromisso financeiro/jurídico |

**Faz sozinho adicionalmente:**
- Divulga vaga após criação (portais configurados)
- Move candidatos para próxima etapa se score ≥ threshold do recrutador
- Agenda entrevistas proativamente após shortlist aprovado (sugere horários)

### Troca de Modo

O recrutador diz no Slack:
- "modo piloto automático" / "piloto" / "automático" → ativa
- "modo copiloto" / "copiloto" / "manual" → volta ao padrão

Salvo em `user_mapping` no Redis (`autonomy_mode: "copilot" | "autopilot"`). Default: `copilot`.

---

## 2. Cadeia Automática Pós-Criação de Vaga

Quando uma vaga é criada e aprovada, em **ambos os modos**:

### Sequência (< 2 minutos)

```
1. Configurar screening IA (critérios do briefing)         → já existe
2. Criar scorecard (skills do briefing)                     → já existe
3. Gerar formulário IA (perguntas automáticas)              → já existe
4. Executar Smart Match (buscar top 15-20 no banco)         → NOVO: trigger automático
5. Disparar screening nos matches encontrados               → NOVO: trigger automático
6. Gerar string de busca LinkedIn                           → NOVO: trigger automático
7. Enviar resumo consolidado ao recrutador                  → NOVO
```

### Mensagem consolidada

```
✅ Vaga *Dev Python Senior* criada e configurada!

⚙️ *Setup automático:*
• Triagem IA com 5 critérios do briefing
• Scorecard: Técnico (Python, FastAPI, Docker) + Cultural
• Formulário de inscrição gerado por IA

🔍 *Busca no banco de talentos:*
• 12 talentos compatíveis encontrados (Smart Match)
• 5 com alto fit (≥ 4.0), screening em andamento
• String LinkedIn pronta 👇
  (Python AND FastAPI AND "senior" AND (remoto OR "São Paulo"))

[Copiloto] Quer que eu divulgue no LinkedIn e Indeed?
[Piloto]   Divulguei no LinkedIn e Indeed ✓
```

### Implementação

**Novo método `_post_creation_chain(conv, app, channel_id, job_id, job_data)`** em `job_creation.py`:
- Chamado após `create_job` retornar sucesso (dentro de `_handle_approval` quando `callback_id == "job_draft_approval"`)
- Executa sequência com `asyncio.gather` onde possível (screening, match, linkedin em paralelo)
- Envia uma única mensagem consolidada
- No modo Piloto, também chama `publish_job()` automaticamente

**Dependência:** precisa do `job_data` (extraído do briefing) e do `job_id` (retornado pela API).

---

## 3. Motor de Confiança (Auto-Advance)

### Conceito

O motor aprende em que faixa de score o recrutador aprova candidatos, e no modo Piloto Automático, avança automaticamente quem estiver dentro dessa faixa.

### Dados

Armazenado em Redis:

```
Key: inhire:confidence:{recruiter_id}
TTL: 365 dias
Value: {
    "auto_advance_threshold": 4.0,        // Score mínimo. Default 4.0, ajustável
    "learned_threshold": null,             // Calculado pelo motor. null = sem dados suficientes
    "decisions_count": 0,                  // Total de decisões de shortlist
    "approval_rate_above_threshold": 0.0,  // % de aprovações acima do threshold
    "reversals_count": 0,                  // Vezes que recrutador reverteu auto-advance
    "last_calibration": null               // Data do último recálculo
}
```

### Calibração

Roda no cron semanal (seg 9:30 BRT), junto com o mini-KAIROS:

1. Buscar todas as decisões de shortlist dos últimos 90 dias
2. Agrupar por faixa de score: [0-2), [2-3), [3-3.5), [3.5-4), [4-4.5), [4.5-5]
3. Calcular taxa de aprovação por faixa
4. O `learned_threshold` é o menor score onde aprovação ≥ 85%
5. Se `reversals_count > 3` nos últimos 30 dias, aumentar threshold em 0.3

### Fluxo no Piloto Automático

```
Candidato com score X chega:
  Se X ≥ auto_advance_threshold:
    → Mover para próxima etapa automaticamente
    → Registrar no audit log
    → Notificação em tempo real: "Movi Ana (4.6) para Entrevista ✓"
  Se X < threshold:
    → Incluir no shortlist, apresentar ao recrutador para decisão
```

### Threshold manual

O recrutador pode definir/ajustar a qualquer momento:
- "Eli, avança automaticamente quem tiver acima de 4.0"
- "Eli, aumenta o threshold pra 4.5"
- "Eli, para de mover automaticamente"

Comando atualiza `auto_advance_threshold` no Redis.

### Reversão

Se o recrutador diz "volta a Ana pra etapa anterior" ou "não devia ter movido":
- Reverter no InHire (mover de volta)
- Incrementar `reversals_count`
- Se 3+ reversões → notificar: "Tô errando nas movimentações automáticas. Quer que eu ajuste o threshold ou volte a pedir aprovação?"

---

## 4. Follow-Up Inteligente por Etapa

### Conceito

Em vez de alertas genéricos "pipeline parado", ações específicas por etapa com cadência progressiva.

### Cadências

**Candidato sem screening (hunting):**
```
T+0:  Disparar screening automático (manual_screening ou analyze_resume)
T+1h: Se screening falhou, tentar método alternativo
      (Nenhuma mensagem ao recrutador — invisível)
```

**Shortlist threshold atingido (5+ alto fit):**
```
T+0:  Gerar shortlist comparativo automaticamente
T+0:  Apresentar ao recrutador com ação clara:
      "Shortlist pronto. [Copiloto: Quer avançar?] [Piloto: Avancei os top 5.]"
```

**Pós-aprovação de shortlist (candidatos esperando entrevista):**
```
T+0:   "Candidatos prontos pra entrevista. Quer que eu agende?"
T+24h: "Ana e Pedro estão esperando desde ontem. Agendar pra quando?"
T+48h: "Candidatos bons recebem propostas em 48h. Melhor não demorar."
T+72h: Incluir no briefing com flag urgente: "⚠️ 3 candidatos há 3 dias sem entrevista"
```

**Pós-entrevista (feedback pendente):**
```
T+2h:  "Como foi a entrevista com João? Me conta que eu preencho o scorecard."
T+24h: "Feedback do João ainda pendente. Se foi bom, posso já montar a oferta."
T+48h: "Último lembrete sobre João. Tá esperando retorno."
       (Inclui no briefing diário como pendência)
```

**Candidato em etapa de Offer:**
```
T+0:   Pré-montar oferta com template padrão + dados do candidato
T+0:   [Piloto] Apresentar rascunho: "Montei a proposta. Confirma e eu envio."
T+3d:  "A proposta de Ana está aberta há 3 dias. Quer que eu envie um follow-up?"
T+7d:  "Proposta sem resposta há 1 semana. Candidato pode estar avaliando outras."
```

**Candidato excepcional (score ≥ 4.5):**
```
T+0:   Notificação imediata com contexto de urgência:
       "🚨 Ana Silva — score 4.8. Perfis assim somem em 48h."
T+0:   [Piloto] Adicionar ao shortlist e sugerir entrevista imediata
T+4h:  Se sem resposta: escalar com proposta concreta de horário
T+24h: Incluir no briefing como item vermelho
```

### Implementação

**Expandir `ProactiveMonitor`** com novo método `_check_stage_followups(recruiter_id, job)`:
- Usa `get_job_talent_timeline()` para calcular tempo em cada etapa
- Compara com cadências definidas acima
- Envia mensagens via `_queue_or_send()` (respeita horário comercial)

**Novo campo na conversa:** `conv.set_context("followup_timestamps", {job_talent_id: last_followup_ts})` para evitar spam.

**Cadências configuráveis por recrutador:** campo `followup_intensity` em user_mapping:
- `"gentle"` — cadências 2x mais longas
- `"normal"` — cadências padrão (acima)
- `"aggressive"` — cadências 50% mais curtas

---

## 5. Notificações

### Em tempo real (imediatas, ambos os modos)

| Evento | Mensagem |
|---|---|
| Candidato excepcional (≥ 4.5) | "🚨 [Nome] — score X.X. Perfis assim somem rápido." |
| Entrevista agendada | "📅 Entrevista com [Nome] agendada pra [data]. Kit enviado." |
| Ação automática completada (Piloto) | "Movi [Nome] (X.X) para [Etapa] ✓" |
| Contratação detectada (webhook) | "🎉 [Nome] contratado(a)! Parabéns!" |
| Candidato desistiu/declinou | "⚠️ [Nome] declinou da vaga [Vaga]." |
| SLA expirando (3 dias restantes) | "⏰ Vaga [Nome] — SLA expira em 3 dias." |

### Briefing matinal (9h BRT, consolidado)

Estrutura:

```
☀️ Bom dia, [Nome]! Resumo das suas vagas:

[Para cada vaga ativa:]
📋 *[Nome da Vaga]* — Dia [N] de [SLA] | [🟢/🟡/🔴]
• Novos: X candidatos | Alto fit: Y | Total: Z
• [O que Eli fez ontem: screening, match, movimentações]
• [Etapa mais lenta: "Entrevista média 4.2 dias"]

⚡ *Preciso de você:*
• [Lista de aprovações pendentes]
• [Feedbacks de entrevista pendentes]
• [Shortlists para revisar]

📊 *Métricas da semana:*
• Tempo médio por etapa: Triagem X.Xd → Entrevista X.Xd → Offer X.Xd
• Conversão: X% triagem→entrevista, Y% entrevista→offer
• [Previsão: "No ritmo atual, fecha em ~N dias"]
```

**Gate:** só envia se há novidades ou pendências. Se tudo está parado e não há ação necessária, não envia briefing vazio.

### Implementação

**Expandir `_daily_briefing()` no ProactiveMonitor:**
- Novo formato com seções separadas (fez / precisa de você / métricas)
- Incluir audit log das ações automáticas das últimas 24h
- Incluir métricas de velocidade e conversão

**Novo: audit log Redis:**
```
Key: inhire:audit:{recruiter_id}:{date}
TTL: 30 dias
Value: [
    {"ts": "...", "action": "auto_advance", "job": "...", "candidate": "...", "detail": "score 4.3"},
    {"ts": "...", "action": "auto_screening", "job": "...", "count": 5},
    {"ts": "...", "action": "smart_match", "job": "...", "found": 12, "high_fit": 5},
]
```

---

## 6. Novos Campos em User Mapping

Expandir `DEFAULT_SETTINGS` em `user_mapping.py`:

```python
# Autonomia
"autonomy_mode": "copilot",               # "copilot" | "autopilot"
"auto_advance_threshold": 4.0,            # Score mínimo para auto-advance (Piloto)

# Follow-up
"followup_intensity": "normal",            # "gentle" | "normal" | "aggressive"

# Notificações
"realtime_notifications": True,            # Notificações em tempo real
"daily_briefing": True,                    # Briefing matinal
```

---

## 7. Novos Métodos no Claude (Tool Additions)

### Tool: `modo_autonomia`

```python
{
    "name": "modo_autonomia",
    "description": "Troca entre modo copiloto e piloto automático, ou ajusta threshold de auto-advance.",
    "input_schema": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "description": "'copilot' ou 'autopilot'"},
            "threshold": {"type": "number", "description": "Score mínimo para auto-advance (0-5)"},
        },
    },
}
```

Quando recrutador diz "modo piloto automático", "confia em mim", "pode ir sozinho", "quero mais autonomia" → Claude chama `modo_autonomia` com `mode: "autopilot"`.

Quando diz "volta pro copiloto", "prefiro aprovar", "menos autonomia" → `mode: "copilot"`.

Quando diz "avança quem tiver acima de 4.5" → `threshold: 4.5`.

---

## 8. Arquivos a Modificar

| Arquivo | Mudança |
|---|---|
| `services/user_mapping.py` | +4 campos de autonomia em DEFAULT_SETTINGS |
| `services/proactive_monitor.py` | Cadeia pós-vaga, follow-up por etapa, briefing expandido, audit log |
| `services/learning.py` | Motor de confiança (calibração semanal, reversões) |
| `services/claude_client.py` | +1 tool `modo_autonomia`, SYSTEM_PROMPT com modos |
| `routers/handlers/job_creation.py` | `_post_creation_chain()`, auto-publish no Piloto |
| `routers/handlers/candidates.py` | Auto-advance no Piloto, auto-screening hunting |
| `routers/handlers/hunting.py` | Smart Match trigger automático pós-vaga |
| `routers/handlers/helpers.py` | `_should_auto_approve()` helper que checa modo + threshold |
| `routers/slack.py` | Handler pra `modo_autonomia`, check de modo nos approval flows |
| `routers/webhooks.py` | Auto-screening em JOB_TALENT_ADDED, enrich audit log |

---

## 9. Métricas de Sucesso

| Métrica | Baseline (Level 2) | Meta (v2) |
|---|---|---|
| Pontos de aprovação por contratação | ~13 | 3-5 |
| Tempo vaga criada → recebendo candidatos | 1-3 dias | < 5 minutos |
| Tempo shortlist pronto → entrevista | 3-10 dias | 1-2 dias |
| Tempo pós-entrevista → feedback | 2-5 dias | < 24 horas |
| Mensagens do recrutador por contratação | ~50 | ~15 |
| Ações automáticas por vaga | ~5 | ~25 |

---

## 10. Riscos e Mitigações

| Risco | Mitigação |
|---|---|
| Auto-advance move candidato errado | Reversão fácil + ajuste de threshold + audit log |
| Recrutador perde visibilidade | Briefing matinal mostra tudo + notificações em tempo real |
| Follow-up excessivo irrita recrutador | `followup_intensity` configurável + respeita daily cap |
| Smart Match encontra candidatos ruins | Screening filtra antes de apresentar + recrutador revisa shortlist |
| Modo piloto em recrutador inexperiente | Default é copiloto, piloto requer ativação explícita |
