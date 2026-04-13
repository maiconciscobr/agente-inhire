# Integração WhatsApp — Design Spec

> Aprovado em 13/04/2026. Último gap do projeto resolvido.

**Contexto:** André Gärtner (dev InHire) entregou endpoint de envio proativo de WhatsApp via API da Meta. Endpoint já disponível em produção (`api.inhire.app`). Janela de 24h ativa, sem suporte a templates por enquanto.

---

## 1. Infraestrutura — `inhire_client.py`

### Novo método

```python
async def send_whatsapp(self, phone: str, message: str) -> dict
```

- Usa `_request()` existente (herda JWT auto-refresh, retry 401, timeout)
- Path: `/subscription-assistant/tenant/{tenant}/send`
- Tenant: `self.auth.tenant` (já disponível no InHireAuth)
- Validação local antes de chamar API:
  - `phone`: só dígitos, 10-15 caracteres. Raises `WhatsAppInvalidPhone`
  - `message`: máximo 4096 caracteres. Trunca silenciosamente se exceder
- Retorno sucesso: `{"success": True, "messageId": "wamid.abc123"}`

### Exceções tipadas

```python
class WhatsAppWindowExpired(Exception):
    """422 — Janela de 24h expirada."""
    pass

class WhatsAppInvalidPhone(Exception):
    """400 — Telefone inválido."""
    pass
```

### Tratamento de erros — mensagens pro recrutador

| HTTP | Exceção | Mensagem |
|---|---|---|
| 422 | `WhatsAppWindowExpired` | "Não consegui enviar — o candidato não interagiu com o WhatsApp do InHire nas últimas 24h." |
| 400 | `WhatsAppInvalidPhone` | "O telefone desse candidato não parece válido pra WhatsApp." |
| 502 | (genérico) | "O WhatsApp está fora do ar no momento. Tenta de novo em alguns minutos?" |

### Sem mudança no `config.py`

O endpoint usa o mesmo `api.inhire.app` — não precisa de URL separada.

---

## 2. Tool `enviar_whatsapp` — mensagem livre

### Definição no `ELI_TOOLS` (claude_client.py)

```python
{
    "name": "enviar_whatsapp",
    "description": (
        "Envia mensagem WhatsApp para um candidato. "
        "Use quando o recrutador pedir pra mandar WhatsApp, avisar candidato, "
        "comunicar por WhatsApp, notificar candidato, etc."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "description": "ID da vaga (se mencionada ou em contexto)",
            },
            "candidate_name": {
                "type": "string",
                "description": "Nome do candidato para enviar a mensagem",
            },
            "message_intent": {
                "type": "string",
                "description": "O que o recrutador quer comunicar ao candidato",
            },
        },
        "required": ["message_intent"],
    },
}
```

### Fluxo do handler `_handle_send_whatsapp()`

1. Claude detecta intent → tool `enviar_whatsapp`
2. Resolver candidato:
   - Se `job_id` + `candidate_name`: buscar no job-talents, extrair telefone
   - Se só `candidate_name` + job em contexto: usar `current_job_id`
   - Se não achar: pedir ao recrutador
3. Extrair telefone do candidato (ver seção 5)
4. Claude gera mensagem profissional baseada no `message_intent`
5. **Ponto de pausa** — `_send_approval()` com preview da mensagem + destinatário + telefone
6. Recrutador aprova → `send_whatsapp(phone, message)`
7. Confirma: "Mensagem enviada pro João via WhatsApp ✓"
8. Se 422 → explica janela de 24h sem jargão

---

## 3. Integração nos fluxos existentes

### Regras gerais

- Oferta de WhatsApp só aparece se `comms_enabled == True` (toggle existente)
- Sempre com botão de aprovação — nunca envia automaticamente
- Se candidato não tem telefone → não oferece (silencioso)
- Usa `_send_approval()` com `callback_id` específico para cada fluxo

### 3.1 Após reprovar candidatos (`candidates.py` → `_reject_candidates`)

Após reprovar com sucesso:
```
✅ 3 candidatos reprovados com sucesso.

💬 Quer enviar devolutiva por WhatsApp pra eles?
[Sim, enviar] [Não precisa]
```

- Filtra candidatos que têm telefone válido
- Claude gera devolutiva via `generate_rejection_message()` (já existe)
- Mostra preview da mensagem antes de enviar
- Envia em sequência (não em paralelo — respeitar rate limit da Meta)
- Reporta: "Devolutiva enviada pra 2 de 3 candidatos (1 sem telefone)"

### 3.2 Após agendar entrevista (`interviews.py` → `_handle_scheduling_input`)

Após agendar com sucesso:
```
✅ Entrevista agendada com João Silva — 15/04 às 14h.

💬 Quer confirmar por WhatsApp com o candidato?
[Sim, enviar] [Não precisa]
```

- Claude gera mensagem de confirmação com data/hora/detalhes
- Mostra preview → aprovação → envia

### 3.3 Após mover candidatos de etapa (`candidates.py` → `_move_approved_candidates`)

Após mover com sucesso:
```
✅ 2 candidatos movidos para Entrevista Técnica.

💬 Quer avisar eles por WhatsApp da próxima etapa?
[Sim, enviar] [Não precisa]
```

- Claude gera mensagem genérica sobre avanço no processo
- Envia em sequência para cada candidato com telefone

---

## 4. Interação nos botões (`slack.py` → `_handle_interaction`)

Novos `callback_id`s no handler de interações:

- `whatsapp_rejection_approval` — devolutiva após reprovação
- `whatsapp_interview_approval` — confirmação de entrevista
- `whatsapp_move_approval` — aviso de avanço de etapa
- `whatsapp_free_approval` — mensagem livre via tool

Cada um:
- Se "aprovar": busca dados do contexto da conversa, chama `send_whatsapp()`, reporta resultado
- Se "rejeitar": "Ok, não enviei nada."

---

## 5. Extração de telefone do candidato

### Cadeia de resolução

1. `talent.phone` no response de `GET /job-talents/{jobId}/talents` (campo nested no objeto talent)
2. Se não vier: `GET /talents/{talentId}` para buscar dados completos
3. Se não tiver telefone: não oferecer WhatsApp

### Normalização

- Remover `+`, espaços, parênteses, hífens
- Se começa com `0`: assumir Brasil, prefixar com `55`
- Validar: só dígitos, 10-15 chars
- Exemplos: `+55 (11) 99999-8888` → `5511999998888`

---

## 6. Atualizar system prompt do Claude

### Remover da lista "O QUE VOCÊ NÃO CONSEGUE FAZER":

```
- Enviar WhatsApp para candidatos — não existe API pública do InTerview ainda
```

### Adicionar às capabilities:

```
- Enviar mensagens por WhatsApp para candidatos (requer aprovação do recrutador, funciona apenas se o candidato interagiu com o WhatsApp do InHire nas últimas 24h)
```

---

## 7. Premissas e limitações

- **Janela de 24h:** sem suporte a templates da Meta por enquanto. Candidatos que não interagiram com o WhatsApp do InHire nas últimas 24h receberão erro 422, tratado com mensagem amigável.
- **Rate limit:** envio sequencial (não paralelo) para respeitar limites da Meta API.
- **Telefone obrigatório:** candidatos sem telefone cadastrado são silenciosamente excluídos das ofertas de WhatsApp.
- **Mesmo JWT:** endpoint usa a mesma autenticação do InHire. Sem credencial adicional.
- **Sem fallback pra email:** se WhatsApp falhar, não tenta email automaticamente (são canais diferentes, recrutador decide).

---

## Arquivos a modificar

| Arquivo | Mudança |
|---|---|
| `services/inhire_client.py` | +`send_whatsapp()`, +exceções tipadas |
| `services/claude_client.py` | +tool `enviar_whatsapp`, +capability no system prompt, -limitação WhatsApp |
| `routers/handlers/helpers.py` | +`_normalize_phone()`, +`_extract_candidate_phone()` |
| `routers/handlers/candidates.py` | +oferta WhatsApp após reprovar e mover |
| `routers/handlers/interviews.py` | +oferta WhatsApp após agendar |
| `routers/slack.py` | +handler `_handle_send_whatsapp`, +callback_ids de WhatsApp no interactions, +dispatch no `_handle_idle` |
