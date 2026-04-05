# Mapeamento Completo da API InHire

**Gerado em:** 31 de março de 2026 | **Atualizado em:** 1 de abril de 2026
**Método:** Testes diretos via curl + Help Center + informações dos devs (Andre e Marcelo)
**Tenant de teste:** demo
**Service account:** Agente IA (role: Teste ADM Math2)

---

## 1. Autenticação

| Item | Valor |
|---|---|
| Endpoint | `POST https://auth.inhire.app/login` |
| Body | `{"email": "...", "password": "..."}` |
| Header obrigatório | `X-Tenant: demo` |
| Resposta | `{accessToken, refreshToken}` |
| Validade do JWT | 1 hora |
| Validade do refresh | 30 dias |
| Refresh | `POST https://auth.inhire.app/refresh` com `{"refreshToken": "..."}` |

**Observação:** A doc original dizia `/auth/login` — o correto é `/login` direto no `auth.inhire.app`.

---

## 2. Jobs (Vagas)

### Criar vaga
```
POST /jobs
```
**Campos obrigatórios:** `name`, `locationRequired` (bool), `talentSuggestions` (bool)

**Campos opcionais:** `description`, `salaryMin`, `salaryMax`, `sla`, `positions` (array de objetos com `reason`)

**Resposta (201):** Retorna a vaga criada com `id`, `status: "open"`, `stages[]` (pipeline completo), `pendencies`, `customFields[]`

**Pipeline padrão retornado:**
1. Listados (listing)
2. Em abordagem (approach)
3. Inscritos (application)
4. Bate-papo com RH (culturalFit)
5. Entrevista com a Liderança (culturalFit)
6. Entrevista Técnica (technicalFit)
7. Offer (offer)
8. Contratados (hiring)

### Outros endpoints de jobs
```
GET    /jobs/:id        → detalhes da vaga (inclui talentsCount, stages, sla, status)
PATCH  /jobs/:id        → atualizar
DELETE /jobs/:id        → deletar (204)
```

**~~Nota:~~ `GET /jobs` retorna 502 — NÃO USAR.**

### Listar vagas (endpoint correto — atualizado sessão 4)
```
POST /jobs/paginated/lean
```
**Body:** `{"limit": 10}` (opcional: `lastEvaluatedKey`, filtros)

**Resposta (200):**
```json
{
  "results": [...],
  "startKey": {"id": "...", "tenantId": "..."} 
}
```
- Key é `results`, NÃO `items`
- `startKey` é o cursor para paginação (enviar como `lastEvaluatedKey` na próxima request)
- Não faz N+1 query, não causa 502

**Alternativa (sem paginação):**
```
GET /jobs/lean
```
Retorna TODOS os jobs (1321 no tenant demo). Usar só se precisar de lista completa.

**Info do Andre (sessão 4):** `GET /jobs` faz full table scan + N+1 query (busca positions pra cada job). Com muitos jobs, estoura timeout de 30s do API Gateway.

---

## 3. Job Talents (Candidatos na Vaga) — ENDPOINT PRINCIPAL

### Listar candidatos de uma vaga
```
GET /job-talents/{jobId}/talents
```
**Retorna:** Array com TODOS os candidatos (hunting + orgânicos). Cada item contém:
- `id` — formato `{jobId}*{talentId}`
- `talentId`
- `status` — "active", etc.
- `stage` — objeto com `name`, `type`, `order`, `phase`
- `talent` — objeto com `name`, `email`, `phone`, `linkedinUsername`, `location`, `headline`, `picture`, `attributes`
- `screening` — objeto com `score`, `status` (quando disponível)
- `source` — "manual", "jobPage", "api", etc.
- `userName` — quem adicionou o candidato (NÃO é o candidato)

**Nota:** Este endpoint substitui `GET /applications` que retornava vazio para candidatos de hunting.

### Adicionar talento a uma vaga
```
POST /job-talents/{jobId}/talents
```

**Criar talento novo na vaga:**
```json
{
  "source": "api",
  "talent": {
    "name": "Nome Completo",
    "email": "email@exemplo.com",
    "phone": "+5511999999999",
    "linkedinUsername": "perfil-linkedin",
    "location": "São Paulo",
    "headline": "Cargo Atual"
  }
}
```

**Vincular talento existente:**
```json
{
  "source": "manual",
  "talentId": "uuid-do-talento"
}
```

**Resposta (201):** Retorna o job-talent criado com `id`, `talentId`, `stage` (primeira etapa).

**Erro 409:** "Job talent already exists" — talento já está na vaga.

### Adicionar em lote
```
POST /job-talents/{jobId}/talents/batch
```
Mesmo auth, aceita array de talentos.

### Outros endpoints de acesso (info do Andre)
| Endpoint | Auth | Uso |
|---|---|---|
| `POST /job-talents/{jobId}/talents` | JWT + CASL (create:JobTalent) | Principal |
| `POST /job-talents/private/{tenantId}/{jobId}/talents` | API Key | Service-to-service |
| `POST /job-talents/public/{jobId}/talents` | reCAPTCHA | Job page pública |
| `POST /job-talents/authenticated/{jobId}/talents` | JWT only | Integrações externas |

---

## 4. Talents (Banco de Talentos)

```
GET  /talents          → lista todos os talentos do tenant (cuidado: resposta grande)
GET  /talents/:id      → detalhes de um talento (name, email, linkedinUsername, location, phone, headline)
POST /talents          → criar talento no banco (required: name)
```

**Campos aceitos no POST:** `name`, `email`, `phone`, `linkedinUsername`, `location`, `headline`

**Campos NÃO aceitos:** `jobId` (usar `/job-talents/{jobId}/talents` para vincular a vaga)

---

## 5. Appointments (Agendamento de Entrevistas)

**Base path:** `/job-talents/appointments/`

### Criar agendamento
```
POST /job-talents/appointments/{jobTalentId}/create
```
**Campos obrigatórios:**
```json
{
  "name": "Entrevista - Nome do Candidato",
  "startDateTime": "2026-04-05T14:00:00",
  "endDateTime": "2026-04-05T15:00:00",
  "hasCallLink": true,
  "userEmail": "email@recrutador.com",
  "guests": [
    {"email": "candidato@email.com", "type": "talent", "name": "Nome Candidato"},
    {"email": "gestor@empresa.com", "type": "user", "name": "Gestor"}
  ]
}
```

**⚠️ IMPORTANTE (corrigido sessão 4):** O campo `guests` é array de **objetos**, NÃO array de strings.

**Campos de cada guest:**
- `email` (string) — obrigatório
- `type` ("talent" | "user" | "external") — obrigatório na prática
- `name` (string) — opcional
- `originId` (string) — opcional
- `status` — NÃO enviar, handler seta "invited" automaticamente

**Tipos de guest:**
- `talent` — o próprio candidato
- `user` — usuário do InHire (recrutador, hiring manager)
- `external` — participante externo

**Integração automática:** Google Calendar (Meet) ou Outlook (Teams) conforme provider do recrutador.

**Pré-requisito:** O user indicado em `userEmail` precisa ter integração de calendário configurada no InHire (Configurações → Integrações → Agenda). Sem isso retorna: `{"message": "Calendar integration not found for user"}`.

**⚠️ Limitação atual:** O endpoint busca a integração de calendário pelo user autenticado no JWT. Se o JWT é do service account, o service account precisaria ter calendário próprio. Investigando com Andre como agendar em nome de outro user.

### Outros endpoints
```
GET  /job-talents/appointments/{id}/get              → obter agendamento
PATCH /job-talents/appointments/{id}/patch            → atualizar
POST /job-talents/appointments/{id}/cancel            → cancelar
GET  /job-talents/appointments/job-talent/{jt_id}     → listar agendamentos de um candidato
GET  /job-talents/appointments/availability/check     → verificar disponibilidade
GET  /job-talents/appointments/my-appointments        → agendamentos do recrutador logado
```

**Nota:** O path original era `/appointments/*` — correto é `/job-talents/appointments/*`. O Andre confirmou que o serviço é o `job-talents-svc`.

---

## 6. Offer Letters (Carta Oferta)

### Criar carta oferta
```
POST /offer-letters
```
**Campos obrigatórios:**
```json
{
  "name": "Oferta - Nome - Vaga",
  "templateId": "uuid-do-template",
  "jobTalentId": "{jobId}*{talentId}",
  "talent": {
    "id": "uuid-do-talento",
    "email": "email@candidato.com"
  },
  "approvals": [
    {"email": "aprovador@empresa.com", "name": "Nome Aprovador"}
  ],
  "language": "pt-BR",
  "templateVariableValues": {
    "nomeCandidato": "Nome",
    "nomeCargo": "Cargo",
    "salario": "R$ 20.000",
    "dataInicio": "15/04/2026"
  }
}
```

**IMPORTANTE:** O campo `jobTalentId` é obrigatório e tem formato `{jobId}*{talentId}`. Sem ele: `"Cannot read properties of undefined (reading 'split')"`.

**Campo opcional:** `skipApprovalFlow: true` — pula aprovação, vai direto para envio ao candidato.

### Fluxo de status
```
POST /offer-letters → status: awaiting_approvals
  (com skipApprovalFlow=true → status: approved_awaiting_send_talent)
Aprovadores assinam via ClickSign → approved_awaiting_send_talent
POST /offer-letters/{id}/talents/notifications → status: awaiting_acceptance
Candidato assina → accepted
Candidato recusa → rejected_by_acceptance
PATCH /offer-letters/{id}/cancel → canceled (qualquer momento)
```

### Outros endpoints
```
GET    /offer-letters                    → listar ofertas
GET    /offer-letters/:id               → obter oferta
DELETE /offer-letters/:id               → remover (204)
GET    /offer-letters/document/:id      → URL do documento gerado
GET    /offer-letters/templates         → listar templates com variáveis
GET    /offer-letters/settings          → configurações do tenant
POST   /offer-letters/templates         → cadastrar template DOCX
```

---

## 7. Requisitions (Requisições)

```
GET  /requisitions                → listar (retorna array com approvers, status, customFields)
POST /requisitions                → criar
```

**Campos do objeto:** `id`, `name`, `description`, `status` (pending/approved/rejected), `approvers[]`, `salaryMin`, `salaryMax`, `userId`, `userName`, `customFields[]`

---

## 8. Mover Candidatos de Etapa (atualizado sessão 4)

**⚠️ NÃO usar `PATCH /applications/{id}` — não aceita stageId. Info do Andre.**

### Mover individual
```
POST /job-talents/talents/{jobTalentId}/stages
```
```json
{
  "stageId": "uuid-da-etapa",
  "comment": "opcional"
}
```

### Mover em lote
```
POST /job-talents/talents/stages/batch
```
```json
{
  "stageId": "uuid-da-etapa",
  "jobTalents": [{"id": "jobTalentId1"}, {"id": "jobTalentId2"}]
}
```

### Automação (service-to-service)
```
PATCH /job-talents/private/{tenantId}/jobTalents/{jobTalentId}/update/stage/{stageId}/automation
```

**Auth:** Bearer token ou API key (authenticated-private). Funciona para hunting + orgânicos.

---

## 9. Reprovar Candidatos (atualizado sessão 4)

**⚠️ NÃO usar `PATCH /applications/{id}` com rejected. Info do Andre.**

### Reprovar individual
```
POST /job-talents/talents/{jobTalentId}/statuses
```
```json
{
  "status": "rejected",
  "reason": "texto de devolutiva",
  "comment": "comentário interno opcional"
}
```

**Statuses válidos:** `active`, `rejected`, `declined`

### Reprovar em lote
```
POST /job-talents/talents/statuses/batch
```

### Automação com email ao candidato
```
PATCH /job-talents/private/{tenantId}/jobTalents/{jobTalentId}/reprove/automation
```
Já seta `rejected` e envia email ao candidato automaticamente.

### Sugestão IA de email de reprovação
```
POST /job-talents/reproval/suggestion/{jobTalentId}
```
Retorna sugestão gerada por IA para o email de devolutiva.

---

## 10. Webhooks

### Registrar webhook
```
POST /integrations/webhooks
```
```json
{
  "url": "https://seu-servidor.com/webhook",
  "event": "JOB_TALENT_ADDED",
  "name": "nome-descritivo",
  "rules": {}
}
```

**IMPORTANTE:** O campo `"rules": {}` é obrigatório por bug da API. Sem ele retorna 500. O Andre confirmou: "campo opcional mas se não mandar ele tenta validar e dá erro porque não existe".

### Eventos disponíveis (confirmado via validação do enum)
| Evento | Quando dispara |
|---|---|
| `JOB_TALENT_ADDED` | Candidato adicionado à vaga |
| `JOB_TALENT_STAGE_ADDED` | Candidato mudou de etapa |
| `FORM_RESPONSE_ADDED` | Formulário de triagem respondido |
| `REQUISITION_CREATED` | Requisição criada |
| `REQUISITION_STATUS_UPDATED` | Requisição aprovada/rejeitada |
| `JOB_ADDED` | Vaga criada |
| `JOB_UPDATED` | Vaga atualizada |
| `JOB_REMOVED` | Vaga removida |
| `JOB_PAGE_CREATED` | Página de vaga criada |

### Formato do payload recebido
O InHire **NÃO envia campo de tipo de evento** no payload. Exemplo para JOB_TALENT_ADDED:
```json
{
  "jobId": "uuid",
  "jobName": "Nome da Vaga",
  "linkedinUsername": "perfil-linkedin",
  "talentId": "uuid",
  "tenantId": "demo",
  "userId": "uuid-de-quem-cadastrou",
  "userName": "Nome de quem cadastrou",
  "source": "manual",
  "location": "Cidade, Estado, Brasil",
  "stageName": "Listados"
}
```

**Atenção:** `userName` é quem cadastrou o candidato, NÃO o nome do candidato. Para obter o nome do candidato, usar `GET /talents/{talentId}`.

### Listar webhooks registrados
```
GET /integrations/webhooks
```
**Nota:** Retorna array vazio mesmo com webhooks registrados. Os webhooks funcionam (testamos com eventos reais), mas a listagem não os mostra. Possível bug.

---

## 11. Screening (Triagem IA)

### Onde encontrar
Os scores de screening estão dentro do objeto retornado por `GET /job-talents/{jobId}/talents`, no campo `screening` de cada candidato.

### Formato
```json
{
  "screening": {
    "score": 4.2,
    "status": "pre-aproved",
    "metadata": {
      "resumeAnalysisScore": {"score": 4.5, "weight": 1},
      "salaryScore": {"score": 3.8, "weight": 1},
      "formScore": {"score": 4.3, "weight": 1}
    }
  }
}
```

### Status e significado
| Status | Score | Significado |
|---|---|---|
| `pre-aproved` | >= 4.0 | Alto fit |
| `need-aproval` | 2.0 a 4.0 | Médio fit |
| `pre-rejected` | <= 2.0 | Baixo fit |
| `approved-by-hunter` | manual | Aprovado pelo recrutador |

**Limitação:** Screening só roda para candidatos orgânicos (inscrição via formulário). Candidatos adicionados por hunting ficam sem score.

---

## 12. Files (Upload de CV) — Descoberto sessão 17

### Criar registro de arquivo
```
POST /files
```
**Campos obrigatórios:**
```json
{
  "id": "uuid-gerado-pelo-client",
  "category": "resumes",
  "name": "cv_candidato.pdf"
}
```

**Categorias válidas:** `"resumes"`, `"job-talent-general-files"`

**Resposta (201):**
```json
{
  "id": "uuid",
  "category": "resumes",
  "name": "cv_candidato.pdf",
  "userId": "uuid-do-service-account",
  "userName": "Agente IA",
  "createdAt": "...",
  "updatedAt": "..."
}
```

**⚠️ Limitação:** Este endpoint cria apenas o metadata do arquivo. O upload do conteúdo binário parece usar S3 pre-signed URLs (endpoints `/files/{id}` retornam 403 com erro de autenticação S3, não JWT). **Pendente: perguntar ao Andre como enviar o binário e vincular ao talento.**

### Endpoints que retornam 403 (service account sem permissão)
```
GET  /files/{id}                    → 403 (auth S3, não JWT)
GET  /files/{id}/upload-url         → 403
GET  /talents/{id}/files            → 403
GET  /talents/{id}/resumes          → 403
GET  /talents/{id}/attachments      → 403
POST /talents/{id}/files            → 403
POST /attachments                   → 403
```

---

## 13. Endpoints que NÃO funcionam

| Endpoint | Erro | Motivo |
|---|---|---|
| `GET /applications` | Retorna `[]` | Só tem candidatos orgânicos. Usar `/job-talents/{jobId}/talents` |
| `GET /scorecards` | 403 | Service account sem permissão |
| `GET /users` | 403 | Service account sem permissão |
| `GET /team` | 403 | Service account sem permissão |
| `GET /members` | 403 | Service account sem permissão |
| `GET /pipelines` | 403 | Não existe como endpoint separado. Stages vêm dentro de `GET /jobs/:id` |
| `GET /stages` | 403 | Idem |

---

## 13. Endpoints que NÃO existem na API

| Funcionalidade | Confirmado por |
|---|---|
| InTerview — listar, ler resultados, disparar, cancelar | Marcelo (dev InHire) |
| Busca full-text no Banco de Talentos | Doc original do projeto |
| GraphQL | "Disponível apenas para uso interno" |

---

## 14. Bugs e comportamentos inesperados

| Bug | Impacto | Workaround |
|---|---|---|
| `POST /integrations/webhooks` exige `"rules": {}` | Retorna 500 sem ele | Sempre enviar `"rules": {}` |
| Payload de webhook não tem tipo de evento | Não dá pra rotear por event type | Detectar pelo conteúdo dos campos |
| `userName` no webhook é quem cadastrou, não o candidato | Nome errado na notificação | Buscar nome real via `GET /talents/{id}` |
| `POST /offer-letters` exige `jobTalentId` como `{jobId}*{talentId}` | Retorna erro de parsing sem ele | Concatenar IDs com `*` |
| ~~`GET /jobs` retorna 502 intermitente~~ | ~~Listagem falha~~ | ✅ **RESOLVIDO sessão 4:** Usar `POST /jobs/paginated/lean` |
| `GET /integrations/webhooks` retorna `[]` com webhooks registrados | Não é possível listar webhooks | Ignorar, webhooks funcionam |
| Endpoints usam paths em inglês, não português | `/jobs` não `/vagas` | Usar nomes em inglês |

---

## 15. Documentação oficial

- Help Center: https://help.inhire.app/pt-BR/
- API pública (candidaturas paginadas): https://docs.inhire.com.br/api/obter-candidaturas-paginadas
- Endpoints internos: não documentados publicamente, obtidos via Andre (dev backend)
