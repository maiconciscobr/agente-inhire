# Eli Autonomia v2 — Design Spec

**Data:** 2026-04-15 | **Revisão:** 2026-04-15 (pós-review de especialistas)
**Objetivo:** Transformar o Eli de assistente reativo em agente autônomo que acelera o time-to-fill, reduzindo de 13 para 2-5 pontos de aprovação conforme o modo escolhido.

---

## 1. Dois Modos de Operação

### Copiloto (padrão)

Eli faz tudo que pode automaticamente. Avisa o que fez. Só pede aprovação quando a ação tem **impacto externo ou envolve movimento de candidatos no pipeline**.

Quando há 3+ ações pendentes, Eli **agrupa em lote** e pede 1 clique para confirmar tudo (batch approval):
```
"Tenho 3 ações pendentes:
 • Mover Ana e Pedro para Entrevista
 • Divulgar vaga no LinkedIn e Indeed
 • Enviar shortlist por WhatsApp pro candidato
 [✅ Confirma tudo]  [📝 Quero revisar uma a uma]"
```

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

Tudo do Copiloto, mais: divulga vagas automaticamente, move candidatos com score acima do threshold, e envia comunicações externas sem pedir.

**2 pontos de aprovação:**

| # | Ação | Por que pede |
|---|---|---|
| 1 | Reprovar candidatos | Irreversível + marca empregadora |
| 2 | Emitir carta oferta | Compromisso financeiro/jurídico |

**Faz sozinho adicionalmente:**
- Divulga vaga após criação (portais configurados)
- Move candidatos para próxima etapa se score ≥ threshold do recrutador
- Envia comunicação externa (WhatsApp/email) com templates pré-aprovados + rodapé "mensagem assistida por IA"
- Agenda entrevistas proativamente após shortlist aprovado (propõe horários)

### Troca de Modo

**Sempre com confirmação explícita** (nunca silenciosa):

```
Recrutador: "modo piloto automático"

Eli: "Entendi! No modo *Piloto Automático* eu faço o máximo sozinho:
      • Divulgo vagas, movo candidatos, comunico candidatos
      • Só paro pra reprovar e enviar oferta
      Threshold de auto-advance: score ≥ 4.0
      
      [✈️ Ativar Piloto]  [🧑‍✈️ Manter Copiloto]"
```

Salvo em `user_mapping` no Redis (`autonomy_mode: "copilot" | "autopilot"`). Default: `copilot`.

**Aviso para poucos dados:** Se recrutador tem < 15 decisões registradas:
```
"Posso ativar, mas ainda tenho poucos dados pra calibrar o auto-advance.
 Pode ter mais erros que o normal no começo. Continua?"
```

---

## 2. Cadeia Automática Pós-Criação de Vaga

Quando uma vaga é criada e aprovada, em **ambos os modos**:

### Sequência (fase crítica sequencial, depois paralelo)

```
SEQUENCIAL (obrigatório nesta ordem):
1. Configurar screening IA (critérios do briefing)
2. Criar scorecard (skills do briefing)
3. Gerar formulário IA (perguntas automáticas)

PARALELO (após config completa):
4. Executar Smart Match (buscar top 15-20 no banco)     }
5. Disparar screening nos matches encontrados            } asyncio.gather
6. Gerar string de busca LinkedIn                        }

7. Enviar resumo consolidado ao recrutador
```

**Flag de proteção:** Redis key `inhire:chain_active:{job_id}` com TTL 5min impede que webhooks disparem screening duplicado durante a cadeia.

### Mensagem consolidada (orientada a RESULTADO, não a processo)

```
Vaga *Dev Python Senior* criada! Já estou trabalhando nela 🚀

Encontrei 12 candidatos no banco de talentos — 5 com alto fit.
Estou analisando eles agora e te mando o shortlist em breve.

Enquanto isso, preparei uma busca no LinkedIn pra você:
  Python AND FastAPI AND "senior" AND (remoto OR "São Paulo")

[Copiloto] Quer que eu divulgue no LinkedIn e Indeed?
[Piloto]   Divulguei no LinkedIn e Indeed ✓
```

**Princípio:** O recrutador não precisa saber que screening IA, scorecard e formulário foram configurados — ele precisa saber **quantos candidatos, qual a qualidade, e o que fazer em seguida**.

---

## 3. Motor de Confiança (Auto-Advance)

### Conceito

O motor aprende em que faixa de score o recrutador aprova candidatos, e no modo Piloto Automático, avança automaticamente quem estiver dentro dessa faixa.

**Regra cardinal:** Copilot = sempre pede aprovação para mover, independente do confidence. Autopilot = usa confidence para decidir se auto-avança ou não.

### Dados

```
Key: inhire:confidence:{recruiter_id}
TTL: 365 dias
Value: {
    "auto_advance_threshold": 4.0,
    "learned_threshold": null,
    "decisions_count": 0,
    "approval_rate_above_threshold": 0.0,
    "reversals_count": 0,
    "reversals_recent": 0,          // Últimas 48h (para circuit breaker)
    "auto_advances_recent": 0,      // Últimas 48h
    "last_calibration": null,
    "circuit_breaker_active": false
}
```

### Circuit Breaker

**Se nas últimas 48h, mais de 30% dos auto-advances foram revertidos:**
1. Desativar auto-advance automaticamente (`circuit_breaker_active: true`)
2. Notificar recrutador:
```
"Percebi que estou errando mais do que o normal nas movimentações
automáticas. Vou voltar a pedir aprovação até me recalibrar.
Quer ajustar o threshold ou manter assim?"
```
3. Recalibrar na próxima rodada semanal
4. Recrutador pode reativar manualmente

### Calibração

Roda no cron semanal (seg 9:30 BRT), junto com o mini-KAIROS:

1. Buscar todas as decisões de shortlist dos últimos 90 dias
2. Agrupar por faixa de score: [0-2), [2-3), [3-3.5), [3.5-4), [4-4.5), [4.5-5]
3. Calcular taxa de aprovação por faixa
4. O `learned_threshold` é o menor score onde aprovação ≥ 85%
5. Se `reversals_count > 3` nos últimos 30 dias, aumentar threshold em 0.3
6. Resetar `reversals_recent` e `auto_advances_recent`

### Fluxo no Piloto Automático

```
Candidato com score X chega:
  Se circuit_breaker_active:
    → Tratar como copiloto (pedir aprovação)
  Se X ≥ auto_advance_threshold:
    → Mover para próxima etapa automaticamente
    → Registrar no audit log
    → Notificação com botão [Desfazer]: "Movi Ana (4.6) para Entrevista ✓ [Desfazer]"
    → Incrementar auto_advances_recent
  Se X < threshold:
    → Incluir no shortlist, apresentar ao recrutador para decisão
```

### Botão [Desfazer] (TTL 1h)

Toda ação automática inclui botão de reversão inline:
```
"Movi Ana (4.6) para Entrevista ✓  [Desfazer]"
```
Se clicado dentro de 1 hora:
- Reverter no InHire (mover de volta)
- Incrementar `reversals_recent`
- Confirmar: "Pronto, voltei Ana pra etapa anterior."

### Threshold manual

O recrutador pode definir/ajustar a qualquer momento:
- "Eli, avança automaticamente quem tiver acima de 4.0"
- "Eli, aumenta o threshold pra 4.5"
- "Eli, para de mover automaticamente" → ativa circuit breaker manual

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

**Pós-shortlist — Agendamento inteligente de entrevista:**

O agendamento é o ponto mais sensível do funil. Se for mal feito, atrasa o processo
e irrita o recrutador. O princípio: **Eli prepara tudo e apresenta opções concretas**.

```
T+0:  Eli verifica disponibilidade (check_availability) e monta 2-3 opções:
      "Ana, Pedro e João estão prontos pra entrevista! 🎯
       Vi sua agenda e tenho 3 sugestões:
       1. Amanhã (terça) 14h — Ana
       2. Quarta 10h — Pedro
       3. Quinta 14h — João
       Quer que eu agende assim, ou prefere outros horários?"

T+0:  [Piloto] Se recrutador tem slots preferidos salvos (preferred_interview_slots),
      Eli propõe direto nesses horários. Se não tem, pergunta.

      Recrutador responde:
      "Ana e Pedro podem ser amanhã, João quinta"
      → Eli agenda os 3, envia convites, kits, tudo automático.

T+24h: Se recrutador não respondeu:
       "Ana, Pedro e João estão esperando entrevista.
        Sugiro agendar essa semana. Qual o melhor horário?"

T+48h: "Ana (score 4.6) está esperando retorno há 48h.
        Melhor dia essa semana?"

T+72h: Incluir no briefing com flag urgente:
       "⚠️ 3 candidatos há 3 dias sem entrevista"
```

**Lógica de slots preferidos (learned + configurável):**

```
1. Se recrutador tem preferred_interview_slots no user_mapping:
   → Usar esses horários direto (ex: "ter/qui 14h-16h")

2. Se não tem, mas tem 5+ agendamentos históricos:
   → Eli analisa padrões e sugere: "Percebi que você costuma
     entrevistar ter/qui à tarde. Posso usar esses horários?"
   → Se confirmar, salva como preferred_interview_slots.

3. Se não tem nenhum dos dois:
   → Perguntar: "Quais são seus horários preferidos pra entrevista?"
   → Salvar a resposta pra usar dali em diante.
```

**Pipeline com múltiplas rodadas (RH → Liderança → Técnica):**

```
Quando candidato avança de "Bate-papo com RH" pra "Entrevista com Liderança":
  → Eli detecta que a próxima etapa envolve outra pessoa
  → Pergunta uma vez: "Quem faz a entrevista com liderança? (nome ou email)"
  → Salva no contexto da vaga (interview_owners por stage)
  → Nas próximas vezes, usa o mesmo entrevistador
  → Agenda com o entrevistador, envia kit por email, cobra feedback via Slack do recrutador
```

**Pós-entrevista — Micro-feedback:**

```
T+2h após horário da entrevista:
  "Como foi a entrevista com Ana? 🎯
   [Avançar] [Preciso pensar] [Não avançar]"

  Avançar → [Piloto] Auto-avança + marca scorecard como "pendente detalhamento"
            "Movi Ana pra próxima etapa ✓ [Desfazer]
             Se quiser detalhar o feedback, é só me contar."
  Avançar → [Copiloto] "Movo Ana pra próxima etapa?"

  Preciso pensar → "Entendi. Até agora você entrevistou 2 de 4 candidatos.
                    Ana ficou como 'talvez'. Pedro foi aprovado.
                    Quer esperar entrevistar os outros antes de decidir?"

  Não avançar → Prepara reprovação: "Entendido. Preparo a devolutiva?"
                (PEDE APROVAÇÃO — reprovação é sempre humana)

T+24h sem resposta: "Feedback da Ana ainda pendente."
T+48h: "Último lembrete sobre Ana." (Entra no briefing como pendência)
```

**Candidato em etapa de Offer:**
```
T+0:   Pré-montar oferta com template padrão + dados do candidato
T+0:   [Piloto] Apresentar rascunho: "Montei a proposta. Confirma e eu envio."
T+3d:  "A proposta de Ana está aberta há 3 dias. Quer que eu entre em contato com ela?"
T+7d:  "Proposta sem resposta há 1 semana. Candidato pode estar avaliando outras."
```

**Candidato excepcional (score ≥ 4.5):**
```
T+0:   Notificação imediata com contexto de urgência:
       "🚨 Ana Silva — score 4.8.
        Seus próximos slots livres são terça 14h e quinta 10h.
        Quer que eu agende com ela?"
T+8h:  Se sem resposta (fim do dia comercial):
       "Ainda sobre Ana (4.8). Agendo pra quinta 10h?"
T+24h: Incluir no briefing como item vermelho
```

### Implementação

**Expandir `ProactiveMonitor`** com novo método `_check_stage_followups(recruiter_id, job)`:
- Usa `get_job_talent_timeline()` para calcular tempo em cada etapa
- Compara com cadências definidas acima
- Envia mensagens via `_queue_or_send()` (respeita horário comercial)
- **Checa `inhire:stage_changed:{jt_id}`** antes de enviar (evita follow-up sobre candidato que acabou de ser movido por webhook)

**Novo campo na conversa:** `conv.set_context("followup_timestamps", {job_talent_id: last_followup_ts})` para evitar spam.

**Cadências configuráveis por recrutador:** campo `followup_intensity` em user_mapping:
- `"gentle"` — cadências 2x mais longas
- `"normal"` — cadências padrão (acima)
- `"aggressive"` — cadências 50% mais curtas

**Auto-detecção:** Se recrutador ignora 3 follow-ups seguidos, baixar automaticamente para `gentle` e avisar: "Percebi que os lembretes estão frequentes. Vou reduzir."

---

## 5. Notificações

### Controle de volume

**Problema:** No autopilot com 3 vagas ativas, o recrutador pode receber 7-20 mensagens/dia. Sem controle, isso vira spam.

**Solução:**

1. **Consolidar ações automáticas em blocos** — em vez de 5 msgs separadas ("Movi X", "Screening de Y"), agrupar a cada 30min:
```
"🤖 Nos últimos 30 min:
 • Movi Ana (4.6) e Pedro (4.3) para Entrevista
 • Rodei screening em 5 candidatos de hunting
 • Encontrei 2 matches no banco pra vaga UX"
```

2. **Cap unificado por dia:**
   - Proativos (alertas, follow-ups): max 3/dia (já existe)
   - Ações automáticas: max 5 blocos/dia
   - Total: max 8 interações iniciadas pelo Eli/dia
   - Briefing matinal e notificações de contratação não contam no cap

3. **Snooze/Silenciar:**
   - Botão `[🔇 Silenciar 2h]` em toda notificação proativa
   - Comando "Eli, silencia" → pausa tudo por 4h
   - "Silencia a vaga Dev Python" → pausa só aquela vaga
   - Auto-backoff: se 5+ msgs sem resposta no mesmo dia → para e consolida tudo no briefing seguinte

4. **Modo digest como alternativa:**
   `notification_mode: "realtime" | "digest" | "hybrid"`
   - realtime: tudo em tempo real (padrão)
   - digest: uma msg às 17h com tudo do dia
   - hybrid: urgentes em tempo real, resto no digest

### Em tempo real (imediatas, ambos os modos)

| Evento | Mensagem |
|---|---|
| Candidato excepcional (≥ 4.5) | "🚨 [Nome] — score X.X. Slots livres: [horários]" |
| Entrevista agendada | "📅 Entrevista com [Nome] agendada pra [data]. Kit enviado." |
| Bloco de ações automáticas (Piloto) | "🤖 Nos últimos 30min: [resumo consolidado]" |
| Contratação detectada (webhook) | "🎉 [Nome] contratado(a)! Parabéns!" |
| Circuit breaker ativado | "⚠️ Auto-advance pausado. Voltei a pedir aprovação." |
| SLA expirando (3 dias restantes) | "⏰ Vaga [Nome] — SLA expira em 3 dias." |

### Briefing matinal (9h BRT) — Two-tier

**Mensagem principal (5-7 linhas):**
```
☀️ Bom dia! 3 vagas ativas, 2 precisam de você:

📋 *Dev Python* — 3 novos candidatos, 2 alto fit
📋 *Designer UX* — SLA em 4 dias, shortlist pronto pra revisar
📋 *QA Senior* — tudo em dia ✓

[Ver detalhes]  [Ir pro shortlist do Designer]
```

**Detalhes (expandível via botão ou thread):**
```
📋 *Dev Python Senior* — Dia 12 de 30 | 🟢
• Novos: 3 candidatos | Alto fit: 2 | Total: 18
• Ontem: rodei screening em 5, movi Ana pra entrevista
• Etapa mais lenta: Entrevista (média 4.2 dias)

⚡ *Preciso de você:*
• Feedback da entrevista de Ana (foi ontem 14h)
• Shortlist do Designer UX (5 candidatos, pronto desde ontem)

📊 *Métricas:*
• Triagem 1.2d → Entrevista 4.2d → Offer 2.1d
• No ritmo atual, Dev Python fecha em ~18 dias
```

**Gate:** só envia se há novidades ou pendências. Não envia briefing vazio.

---

## 6. Novos Campos em User Mapping

Expandir `DEFAULT_SETTINGS` em `user_mapping.py`:

```python
# Autonomia
"autonomy_mode": "copilot",               # "copilot" | "autopilot"
"auto_advance_threshold": 4.0,            # Score mínimo para auto-advance (Piloto)

# Entrevistas
"preferred_interview_slots": [],           # [{"day": "tue", "hour": 14}, ...]
"default_interview_duration": 60,          # Minutos

# Follow-up
"followup_intensity": "normal",            # "gentle" | "normal" | "aggressive"

# Notificações
"realtime_notifications": True,            # Notificações em tempo real
"daily_briefing": True,                    # Briefing matinal
"notification_mode": "realtime",           # "realtime" | "digest" | "hybrid"
"muted_until": null,                       # Timestamp até quando está silenciado
```

**Campos por vaga (no contexto da conversa):**
```python
conv.set_context("interview_owners", {
    "Entrevista com Liderança": {"name": "João Silva", "email": "joao@empresa.com"},
    "Entrevista Técnica": {"name": "Pedro Dev", "email": "pedro@empresa.com"},
})
```

---

## 7. Novos Métodos no Claude (Tool Additions)

### Tool: `modo_autonomia`

```python
{
    "name": "modo_autonomia",
    "description": "Troca entre modo copiloto e piloto automático, ou ajusta threshold/silenciar.",
    "input_schema": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "description": "'copilot' ou 'autopilot'"},
            "threshold": {"type": "number", "description": "Score mínimo para auto-advance (0-5)"},
            "mute_hours": {"type": "number", "description": "Silenciar notificações por N horas"},
            "mute_job_id": {"type": "string", "description": "Silenciar notificações de uma vaga específica"},
        },
    },
}
```

---

## 8. Wrapper de Autonomia

**Novo helper `_request_or_auto_approve`** centraliza toda decisão de aprovação:

```python
async def _request_or_auto_approve(conv, app, channel_id, action, title, details,
                                    callback_id, execute_fn):
    """Decide se executa automaticamente ou pede aprovação, baseado no modo."""
    user = app.state.user_mapping.get_user(conv.user_id) or {}
    
    if _should_auto_approve(user, action):
        await execute_fn()
        app.state.audit_log.log_action(conv.user_id, action, ...)
        # Notificação com botão [Desfazer]
    else:
        await _send_approval(conv, slack, channel_id, title, details, callback_id)
        conv.state = FlowState.WAITING_*_APPROVAL
```

Isso evita que o FlowState entre em WAITING quando a ação é auto-aprovada.

---

## 9. Proteções Técnicas

### Webhook thundering herd (import de 50 candidatos)

```python
_SCREENING_SEMAPHORE = asyncio.Semaphore(5)

async def _auto_screen_candidate(app, job_talent_id):
    async with _SCREENING_SEMAPHORE:
        await app.state.inhire.manual_screening(job_talent_id)
```

### Race condition cron vs webhook

O webhook seta `inhire:stage_changed:{jt_id}` com TTL 2h ao processar mudança de etapa. O cron checa essa key antes de enviar follow-up — se existe, pula (candidato moveu recentemente).

### Cron vs DM handler — conversation.save

O `_send_proactive` deve adquirir o lock do user antes de modificar a conversa, ou skip history se lock indisponível.

### Chain pós-vaga vs webhook

Redis key `inhire:chain_active:{job_id}` com TTL 5min. Webhook checa antes de disparar auto-screening. Se chain ativa, adiciona candidato a `inhire:screening_pending:{job_id}` (lista Redis). Chain processa a fila ao finalizar.

---

## 10. Compliance LGPD

### Obrigatório antes de produção

1. **RIPD** (Relatório de Impacto à Proteção de Dados) — elaborar proativamente
2. **DPA com Anthropic** incluindo cláusulas-padrão da ANPD (Resolução 19/2024)
3. **Aviso de IA** no formulário de inscrição do InHire
4. **Canal de revisão humana** — email dedicado para candidatos contestarem decisões

### Pseudonimização

Antes de enviar dados ao Claude, substituir nomes por IDs quando possível. Manter mapeamento local.

### Comunicações externas (autopilot)

- Todo WhatsApp/email automatizado inclui rodapé: "Mensagem assistida por inteligência artificial. Para revisão humana: [email]"
- Templates pré-aprovados pela empresa (não texto livre do Claude sem guardrail)
- Log completo no audit log
- Opt-out sem prejuízo à candidatura

### Art. 20 LGPD (decisão automatizada)

O candidato pode solicitar revisão humana de qualquer decisão automatizada. A empresa deve fornecer explicação dos critérios utilizados.

---

## 11. Arquivos a Modificar

| Arquivo | Mudança |
|---|---|
| `services/user_mapping.py` | +7 campos (autonomia, entrevistas, notificações) |
| `services/audit_log.py` | NOVO — registro de ações autônomas |
| `services/proactive_monitor.py` | Follow-up por etapa, briefing two-tier, consolidação, snooze |
| `services/learning.py` | Motor de confiança + circuit breaker |
| `services/claude_client.py` | +1 tool `modo_autonomia`, SYSTEM_PROMPT com modos |
| `routers/handlers/job_creation.py` | `_post_creation_chain()` (sequencial→paralelo) |
| `routers/handlers/candidates.py` | Auto-advance via `_request_or_auto_approve` |
| `routers/handlers/interviews.py` | Smart scheduling, micro-feedback, botão desfazer |
| `routers/handlers/helpers.py` | `_should_auto_approve`, `_request_or_auto_approve` |
| `routers/slack.py` | Handler `modo_autonomia`, batch approval, snooze |
| `routers/webhooks.py` | Auto-screening com semáforo, flag `stage_changed` |

---

## 12. Métricas de Sucesso

| Métrica | Baseline (hoje) | Meta (v2) |
|---|---|---|
| Pontos de aprovação por contratação | ~13 | 2-5 |
| Tempo vaga criada → recebendo candidatos | 1-3 dias | < 5 minutos |
| Tempo shortlist pronto → entrevista | 3-10 dias | 1-2 dias |
| Tempo pós-entrevista → feedback | 2-5 dias | < 24 horas |
| Mensagens do recrutador por contratação | ~50 | ~15 |
| Ações automáticas por vaga | ~5 | ~25 |
| Mensagens do Eli por dia (cap) | sem cap | max 8 + briefing |

---

## 13. Riscos e Mitigações

| Risco | Mitigação |
|---|---|
| Auto-advance move candidato errado | Circuit breaker (30% reversões → desliga) + botão [Desfazer] + audit log |
| Recrutador perde visibilidade | Briefing two-tier + audit log + notificações consolidadas |
| Follow-up excessivo irrita recrutador | Auto-backoff + snooze + `followup_intensity` configurável + cap 8/dia |
| Score InHire descalibra | Circuit breaker detecta e desliga auto-advance automaticamente |
| Smart Match encontra candidatos ruins | Screening filtra antes de apresentar + recrutador revisa shortlist |
| Modo piloto com poucos dados | Aviso explícito se < 15 decisões + confirmação com botões |
| 50 webhooks simultâneos (import CSV) | Semáforo(5) + fila Redis |
| Cron envia follow-up sobre candidato recém-movido | Redis key `stage_changed:{jt_id}` TTL 2h |
| Race condition conversation.save | Lock no `_send_proactive` |
| Comunicação externa sem consentimento | Templates pré-aprovados + rodapé IA + opt-out + LGPD Art. 7º V/IX |
| Viés algorítmico no motor de confiança | Auditoria trimestral + circuit breaker de disparidade (futuro) |
| Transferência internacional de dados | DPA com Anthropic + pseudonimização |
