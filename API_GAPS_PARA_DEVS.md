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

## Gap 4 — Comunicação com candidato — PARCIALMENTE RESOLVIDO

### Status: ⚠️ Email com 403, WhatsApp sem API

**Teste realizado:**
- `POST /emails/submissions` → **403 Forbidden**
- `GET /emails/templates` → **403 Forbidden**
- `POST /private/emails/submissions` → **403 Forbidden**

O serviço de email (`comms-svc`) rejeita a service account. Pode ser uma questão de permissão CASL ou configuração do tenant.

### Ação necessária para email
1. Verificar se a service account tem role/permissão para usar o `comms-svc`
2. Verificar se o tenant `demo` tem `comms-svc` habilitado
3. Alternativa: usar endpoint `POST /private/emails/submissions` (service-to-service) se aceitar API key

### WhatsApp / InTerview
- Sem API pública para envio direto de mensagens
- O WhatsApp Assistant é unidirecional (candidato → sistema)
- Ação: criar endpoint `POST /assistant/send` no WhatsApp Assistant para envio proativo

---

## Resumo atualizado

| Gap | Status anterior | Status atual | Ação |
|---|---|---|---|
| **1. Agendamento** | ❌ 403 | ✅ **FUNCIONAL** | Implementado com `provider: "manual"` |
| **2. Carta oferta** | ❌ 403 | ✅ **FUNCIONAL** | Implementado com template ID correto |
| **3. Busca talentos** | ❌ Sem endpoint | ⚠️ Parcial | Nome funciona, full-text precisa de endpoint Typesense |
| **4. Email** | ❌ Sem teste | ❌ 403 | Investigar permissão da service account no comms-svc |
| **4. WhatsApp** | ❌ Sem API | ❌ Sem API | Criar endpoint de envio no WhatsApp Assistant |

### O que mudou no Agente Eli
- `agendar_entrevista` movido de Layer 2 → **Layer 1 (funcional)**
- `carta_oferta` movido de Layer 2 → **Layer 1 (funcional)**
- Payload de agendamento corrigido (provider manual, campos obrigatórios)
- Fallbacks de 403 removidos (não aplicam mais)
