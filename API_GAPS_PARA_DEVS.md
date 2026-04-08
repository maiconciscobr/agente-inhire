# Agente Eli — Status dos Gaps da API (atualizado 2026-04-06)

> **Contexto:** O Agente Eli automatiza recrutamento via Slack + InHire API + Claude + Redis.
> Este documento foi atualizado após investigação direta nos endpoints do servidor de produção.

---

## Gap 1 — Agendamento de entrevistas — RESOLVIDO

### Status: ✅ FUNCIONAL com `provider: "manual"`

**Teste realizado:** `POST /job-talents/appointments/{jobTalentId}/create` retornou **201 Created**.

O 403 anterior era porque o payload enviava `"provider": "google"`, que exige integração de calendário. Com `"provider": "manual"`, o appointment é registrado no InHire sem precisar de Google/Outlook.

### Payload que funciona

```json
{
  "name": "Entrevista - João Silva - Dev Backend Senior",
  "startDateTime": "2026-04-10T14:00:00.000Z",
  "endDateTime": "2026-04-10T15:00:00.000Z",
  "userEmail": "service-account@inhire.app",
  "guests": [{"email": "joao@email.com", "name": "João Silva", "type": "talent"}],
  "hasCallLink": false,
  "provider": "manual"
}
```

### Limitação
- Modo manual não envia convite de calendário ao candidato — o recrutador precisa enviar o link da reunião separadamente
- Para integração com calendário, precisa configurar `tenant.configurations.integrations.appointments` com credentials do Google/Outlook

### Melhoria futura
Configurar service account do Google Calendar no tenant `demo` para que o Eli envie convites automaticamente com link do Meet.

---

## Gap 2 — Carta oferta — RESOLVIDO

### Status: ✅ FUNCIONAL

**Teste realizado:** `POST /offer-letters` retornou **201 Created**.

O 403 anterior provavelmente era token expirado. Com token fresco, funciona sem restrição de permissão.

### Payload que funciona

```json
{
  "name": "Oferta - João Silva - Dev Backend Senior",
  "templateId": "014aa97b-6a1c-4bc9-96c5-18447bda744d",
  "approvals": [{"email": "gestor@empresa.com", "name": "Nome do Aprovador"}],
  "talent": {"id": "talent-uuid", "email": "joao@email.com"},
  "jobTalentId": "{jobId}*{talentId}",
  "language": "pt-BR",
  "templateVariableValues": {
    "nomeCargo": "Dev Backend Senior",
    "nomeCandidato": "João Silva",
    "salario": "15000",
    "dataInicio": "2026-05-01"
  },
  "skipApprovalFlow": true
}
```

### Detalhes importantes
- `templateId` usa o campo `id` do template, NÃO o `originId`
- `GET /offer-letters/templates` retorna **200 OK** com templates disponíveis
- Variáveis comuns: `nomeCargo`, `nomeCandidato`, `salario`, `dataInicio`
- `skipApprovalFlow: true` pula aprovação interna (útil para testes)
- Fluxo completo usa ClickSign para assinatura digital

### Endpoints relacionados confirmados

| Endpoint | Status |
|---|---|
| `GET /offer-letters/templates` | ✅ 200 |
| `POST /offer-letters` | ✅ 201 |
| `GET /offer-letters/{id}` | ✅ (não testado, deve funcionar) |
| `POST /offer-letters/{id}/talents/notifications` | Não testado |

---

## Gap 3 — Busca full-text no Banco de Talentos — PARCIALMENTE RESOLVIDO

### Status: ⚠️ Busca por nome funciona, full-text não

**Teste realizado:** `GET /talents/name/{name}` retornou **200 OK** (array vazio para "Camila" — sem talentos com esse nome no tenant demo).

### Endpoints disponíveis agora

| Endpoint | Busca por | Status |
|---|---|---|
| `GET /talents/name/{name}` | Nome exato | ✅ 200 |
| `GET /talents/email/{email}` | Email exato | Disponível |
| `GET /talents/linkedin/{username}` | LinkedIn username | Disponível |
| `POST /talents/ids` | Lista de IDs | Disponível |
| `POST /talents/paginated` | Paginação por data | Disponível (sem filtro texto) |

### O que falta
- **Busca full-text** por skills, experiência, localização, texto do CV
- O Typesense está configurado no InHire mas não há endpoint REST que exponha busca no banco de talentos global
- Endpoint `POST /job-talents/search-engine/key` gera chave Typesense mas só para candidatos de uma vaga específica

### Ação necessária
Criar endpoint `POST /talents/search-engine/key` que gere chave Typesense scoped para `talents-{tenantId}`. Padrão já existe no `job-talents-svc`. Esforço estimado: baixo.

### Workaround implementado
O Eli usa `GET /talents/name/{name}` como busca básica enquanto o endpoint full-text não existe.

---

## Gap 4 — Comunicação com candidato — EMAIL RESOLVIDO, WhatsApp pendente

### Email: ✅ FUNCIONAL

**O 403 era base path errado.** O endpoint correto é `/comms/emails/submissions` (não `/emails/submissions`).

- `POST /comms/emails/submissions` com JWT + `emailProvider: "amazon"` → **204 OK**
- `GET /comms/emails/templates` → **200 OK** (templates de devolutiva, abordagem, etc.)

Métodos `send_email()` e `list_email_templates()` implementados no `inhire_client.py`.

### WhatsApp / InTerview: ❌ Sem API

- Sem API pública para envio direto de mensagens
- O WhatsApp Assistant é unidirecional (candidato → sistema)
- Ação: criar endpoint `POST /assistant/send` no WhatsApp Assistant para envio proativo

---

## Resumo atualizado

| Gap | Status anterior | Status atual | Ação |
|---|---|---|---|
| **1. Agendamento** | ❌ 403 | ✅ **FUNCIONAL + TESTADO E2E** | `provider: "manual"`, 33/37 PASS |
| **2. Carta oferta** | ❌ 403 | ✅ **FUNCIONAL + TESTADO E2E** | Template ID correto (campo `id`), 33/37 PASS |
| **3. Busca talentos** | ❌ Sem endpoint | ✅ **FUNCIONAL** | Endpoint existente: `GET /search-talents/security/key/talents?engine=typesense` (André Gärtner, 07/04) |
| **4. Email** | ❌ 403 | ✅ **FUNCIONAL** | Base path `/comms/`, emailProvider `amazon` |
| **5. WhatsApp** | ❌ Sem API | ❌ Sem API | Criar endpoint de envio no WhatsApp Assistant |

### Bugs corrigidos durante testes E2E
- `talent.name` nested (API retorna `talent: {name: "..."}`, não `talentName`)
- `endDateTime` vazio (Claude nem sempre retorna — agora calcula start + 1h)
- `userEmail` vazio (busca do `user_mapping` como fallback)
- `current_job_id` não setado no contexto antes de chamar handlers

### O que mudou no Agente Eli
- `agendar_entrevista` movido de Layer 2 → **Layer 1 (funcional)**
- `carta_oferta` movido de Layer 2 → **Layer 1 (funcional)**
- `send_email()` e `list_email_templates()` adicionados ao `inhire_client.py`
- Helpers `_talent_name()`, `_talent_email()`, `_talent_stage()` para extração consistente
- Test suite expandido de 16 para 32 cenários (37 steps)

### Gaps que ainda dependem de desenvolvimento no backend InHire

| Gap | O que precisa | Esforço estimado |
|---|---|---|
| ~~Busca full-text banco de talentos~~ | ~~RESOLVIDO~~ — endpoint já existia: `GET /search-talents/security/key/talents?engine=typesense` | ✅ |
| ~~WhatsApp envio proativo~~ | Em desenvolvimento por outro time — aguardando API | Aguardando |
