# Batch Approval + Auto-backoff de Follow-ups — Design Spec

**Data:** 2026-04-16
**Objetivo:** Reduzir ruído no Slack com aprovações agrupadas e follow-ups adaptativos.

---

## 1. Batch Approval na Cadeia Pós-Vaga

### Contexto

No modo copiloto, a cadeia pós-criação de vaga (`_post_creation_chain`) gera múltiplas ações que precisam de aprovação: divulgar, mover candidatos do smart match, enviar WhatsApp. Hoje cada uma é uma mensagem individual. Com 3+ ações, fica poluído.

### Mecânica

- A cadeia pós-vaga acumula ações pendentes numa lista no contexto da conversa ao invés de enviar aprovações individuais
- No final da cadeia, se a lista tem 3+ itens → envia bloco batch. Se tem 1-2 → envia individual (como hoje)
- Não se aplica ao modo piloto automático (ações são auto-aprovadas)

### Formato Slack

```
Fiz o setup da vaga e encontrei 8 candidatos no banco!

Tenho 3 ações pendentes pra sua aprovação:
• Divulgar vaga no LinkedIn e Indeed
• Mover 5 candidatos com alto fit para Entrevista
• Enviar shortlist por WhatsApp

[Confirma tudo]  [Revisar uma a uma]
```

### Dados no contexto

```python
conv.set_context("batch_pending", [
    {"callback_id": "publish_approval", "title": "Divulgar no LinkedIn e Indeed"},
    {"callback_id": "shortlist_approval", "title": "Mover 5 candidatos para Entrevista"},
    {"callback_id": "whatsapp_free_approval", "title": "Enviar shortlist por WhatsApp"},
])
```

Tudo string e dict — serializa no Redis sem problema.

### Interações

- **[Confirma tudo]** (`approve` no `batch_approval`) → itera a lista, chama `_handle_approval(app, user_id, channel_id, "approve", callback_id)` para cada item. Reporta resultado consolidado.
- **[Revisar uma a uma]** (`adjust` no `batch_approval`) → envia cada aprovação individual usando os callbacks existentes (publish_approval, shortlist_approval, etc.)

### Arquivos modificados

- `app/routers/handlers/helpers.py` — nova função `_send_batch_approval()`
- `app/routers/handlers/job_creation.py` — `_post_creation_chain` acumula ações, chama batch no final
- `app/routers/slack.py` — handler `batch_approval` no `_handle_approval`

---

## 2. Auto-backoff de Follow-ups

### Contexto

O `ProactiveMonitor` manda follow-ups proativos (entrevista parada, oferta pendente, candidato excepcional). Se o recrutador ignora repetidamente, os lembretes se tornam ruído. Hoje a `followup_intensity` é estática — o recrutador precisa mudar manualmente.

### Mecânica

Contador de ignores consecutivos por recrutador no Redis:

```
Key: inhire:followup_ignores:{user_id}
Value: int
TTL: 30 dias
```

**Fluxo:**
1. `_send_proactive()` manda follow-up → `record_alert_sent()` registra timestamp
2. Recrutador responde em 30min → `check_alert_response()` detecta → zera contador, restaura intensidade
3. Recrutador NÃO responde → próximo cron incrementa contador
4. Contador = 3 → `followup_intensity` desce um nível (normal → gentle)
5. Contador = 6 → desce de novo (gentle → off)
6. Quando off, `_check_stage_followups` faz early return — só briefing matinal continua

### Escala

| Ignores consecutivos | Intensidade | Efeito |
|---|---|---|
| 0-2 | normal | Cadência padrão |
| 3-5 | gentle | Multiplier 2x (metade da frequência) |
| 6+ | off | Sem follow-ups, só briefing |

### Recuperação

- Recrutador responde a qualquer mensagem do Eli → ignores zera pra 0, intensidade volta pra `normal`
- Um engajamento reseta tudo
- Recuperação é silenciosa (sem meta-notificação)

### Transparência

Quando reduz intensidade, envia uma única mensagem:
```
Percebi que meus lembretes não estão sendo úteis no momento.
Vou reduzir a frequência — quando precisar, é só me chamar!
```

### Arquivos modificados

- `app/services/learning.py` — contador de ignores, lógica de increment/reset, `get_effective_intensity()`
- `app/services/proactive_monitor.py` — `_check_stage_followups` consulta intensidade efetiva ao invés da estática
- `app/routers/slack.py` — `_handle_dm` chama reset de ignores quando recrutador responde (já chama `check_alert_response`)

---

## 3. Testes

### Batch approval (5 testes)
- `test_batch_sends_block_when_3_plus_actions` — 3+ ações → bloco batch
- `test_batch_sends_individual_when_less_than_3` — 1-2 ações → individual
- `test_batch_approve_all_executes_all` — clicar [Confirma tudo] executa todas
- `test_batch_review_sends_individual` — clicar [Revisar] envia cada uma separada
- `test_batch_not_used_in_autopilot` — piloto automático não acumula

### Auto-backoff (5 testes)
- `test_ignore_counter_increments` — follow-up sem resposta incrementa
- `test_response_resets_counter` — resposta zera contador
- `test_3_ignores_downgrades_to_gentle` — 3 ignores → gentle
- `test_6_ignores_downgrades_to_off` — 6 ignores → off
- `test_off_skips_followups` — intensidade off faz early return no _check_stage_followups
