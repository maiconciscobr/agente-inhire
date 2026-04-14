# Mapa de Cobertura — Agente Eli vs InHire

> Documento canonical: o que o Eli cobre, o que falta, e o que precisa do time InHire.
> Atualizado: sessao 40 (2026-04-14).
> Fonte: Help Center InHire + site inhire.com.br + API testada.

---

## Como ler este documento

- **Eli FAZ** = funcionalidade implementada e deployada
- **Precisa de endpoint** = agente esta pronto pra implementar, mas API nao oferece
- **Precisa de permissao** = endpoint existe mas service account retorna 403
- **Feature UI** = funcionalidade visual do InHire que nao faz sentido no agente (Slack)
- **Modulo externo** = Mindsight, extensoes Chrome — sem API publica

---

## 1. Criacao e configuracao de vagas

### Eli FAZ
- Briefing conversacional com extracao de dados via Claude
- Geracao de job description completa
- Criacao da vaga no InHire (`POST /jobs`)
- Multiplas posicoes (motivo generico "expansion")

### Gaps

| Funcionalidade | Status | Endpoint necessario | Prioridade |
|---|---|---|---|
| Formulario de inscricao | Sem endpoint | `GET/PUT /jobs/{id}/application-form` | **P1** |
| Perguntas eliminatorias | Sem endpoint | Incluir no endpoint de formulario: `questions[]` | **P1** |
| Configurar triagem IA (criterios) | Sem endpoint | `POST /jobs/{id}/screening-config` | **P1** |
| Divulgacao em portais | Sem endpoint | `POST /jobs/{id}/publish` + `GET channels` | **P1** |
| Scorecard de entrevista | 403 + sem POST | `POST /jobs/{id}/scorecard` + liberar GET | **P2** |
| Campos personalizados (custom fields) | Sem endpoint | `GET /custom-fields` | **P3** |
| Pipeline customizado | Sem endpoint | `PUT /jobs/{id}/stages` | **P3** |
| Templates de vaga | Sem endpoint | `GET /job-templates` + criar com `templateId` | **P3** |
| SLA/prazo na criacao | Nao implementado | Campo pode ja existir no `POST /jobs` — verificar | **P3** |

### Payloads esperados

**Formulario de inscricao:**
```json
GET /jobs/{jobId}/application-form
-> { "fields": [...], "questions": [...] }

PUT /jobs/{jobId}/application-form
{
  "fields": [
    { "name": "phone", "required": true },
    { "name": "salary_expectation", "required": true }
  ],
  "questions": [
    {
      "text": "Disponibilidade para inicio imediato?",
      "type": "yes_no",
      "eliminatory": true,
      "expected_answer": "yes"
    },
    {
      "text": "Anos de experiencia com Python?",
      "type": "numeric",
      "eliminatory": true,
      "min_value": 3
    }
  ]
}
```

**Configurar triagem IA:**
```json
POST /jobs/{jobId}/screening-config
{
  "criteria": [
    { "name": "Python", "weight": "essential", "description": "3+ anos" },
    { "name": "FastAPI", "weight": "important" },
    { "name": "Docker", "weight": "nice_to_have" }
  ],
  "auto_reject_below": 2.0,
  "auto_approve_above": 4.0
}
```

**Divulgacao em portais:**
```json
GET /jobs/{jobId}/publish/channels
-> [{ "id": "linkedin", "connected": true }, { "id": "indeed", "connected": true }]

POST /jobs/{jobId}/publish
{ "channels": ["linkedin", "indeed", "careers_page"] }
-> { "published": ["linkedin", "indeed"], "failed": [] }
```

---

## 2. Divulgacao e atracao

### Eli FAZ
- Gera strings de busca booleanas pro LinkedIn
- Busca no banco de talentos (Typesense full-text, 86k+)
- Analise de perfil colado com fit score
- Fluxo "analisei perfil -> adicionar a vaga" com dedup

### Gaps

| Funcionalidade | Status | Detalhes | Prioridade |
|---|---|---|---|
| Publicar em LinkedIn/Indeed/Netvagas/Glassdoor | Sem endpoint | Ver secao 1 — `POST /jobs/{id}/publish` | **P1** |
| Pagina de vagas (careers page) | Feature UI | EMPRESA.inhire.app/vagas | N/A |
| Link de compartilhamento por canal | Sem endpoint | | **P3** |
| Programa de indicacao (links gamificados) | Sem endpoint | `GET/POST /referrals` | **P3** |
| Dashboard de indicacoes | Feature UI | | N/A |
| Extensao Chrome de Hunting | Modulo externo | Agente tem `POST /extension/analyze` proprio | N/A |

---

## 3. Triagem e selecao

### Eli FAZ
- Lista candidatos com scores (alto/medio/baixo fit)
- Filtra por etapa ("quem ta na entrevista?")
- Shortlist comparativo (Claude ranqueia)
- Move candidatos em lote
- Reprova com motivo inteligente (Haiku classifica: overqualified/underqualified/location/other)
- Devolutiva personalizada por candidato (nome, etapa, pontos fortes)
- Consulta sugestao de reprovacao do InHire
- WhatsApp para enviar devolutiva

### Gaps

| Funcionalidade | Status | Endpoint necessario | Prioridade |
|---|---|---|---|
| **Agente de Triagem** (config de criterios) | ✅ Implementado | `PATCH /jobs/{id}` com `screeningSettings` + `resumeAnalyzer` | — |
| Scores detalhados (por criterio + evidencia) | ✅ Implementado | `GET /job-talents/{id}/resume-analysis` + `GET /{id}/screening-analysis` | — |
| Triagem sob demanda (hunting) | ✅ Implementado | `POST /job-talents/{id}/screening/manual` + `POST /resume/analyze/{id}` | — |
| Persistir notas/ranking do Claude | Sem campo | `PATCH /job-talents/{jt}` com campo `notes` | **P3** |
| Tags em candidatos | ✅ Implementado | `POST /job-talents/tags/add/batch` | — |
| Classificar talentos (reacao) | Disponivel | `POST /job-talents/reaction/{id}` — nao implementado no agente | **P3** |

**Payload — Triagem sob demanda:**
```json
POST /job-talents/{jobTalentId}/screening/run
-> { "status": "queued", "estimatedTime": "30s" }

GET /job-talents/{jobTalentId}/screening/status
-> { "status": "completed", "score": 4.2, "details": [...] }
```

**Payload — Scores detalhados:**
```json
GET /jobs/{jobId}/screening-results
-> [{
  "jobTalentId": "...",
  "overallScore": 4.2,
  "criteria": [
    { "name": "Python", "score": 5, "evidence": "10 anos mencionados" },
    { "name": "FastAPI", "score": 3, "evidence": "1 projeto" }
  ]
}]
```

---

## 4. Entrevistas e avaliacoes

### Eli FAZ
- Agendar entrevista (provider: manual)
- Cancelar e remarcar entrevista (PATCH)
- Lembrete automatico 2h antes (APScheduler)
- Listar entrevistas do candidato e recrutador
- Verificar disponibilidade
- WhatsApp pos-agendamento

### Gaps

| Funcionalidade | Status | Endpoint/Acao | Prioridade |
|---|---|---|---|
| **Feedback do entrevistador (Scorecard)** | 403 no GET | `POST /scorecards` + **liberar GET** | **P1** |
| **Kit de Entrevista** (roteiro + CV + scorecard) | Sem endpoint | `GET /jobs/{id}/interview-kit` | **P2** |
| **Parecer com IA** (IA gera parecer no Kit) | Sem API | Feature nova InHire — verificar se tera endpoint | **P2** |
| Integracao calendario (Meet/Zoom) | Provider fixo manual | Liberar `provider: "google"/"microsoft"` no service account | **P2** |
| Enviar teste DISC | Modulo Mindsight | Sem API publica | **P2** |
| Enviar testes Mindsight (BIG FIVE, fit cultural) | Modulo Mindsight | Sem API publica | **P2** |
| Enviar testes personalizados (tecnicos) | Sem endpoint | `GET/POST /jobs/{id}/tests` | **P2** |
| **Automacoes de vaga** (acao por mudanca de etapa) | ✅ Implementado | `POST /workflows/automations` (CRUD completo) | — |
| Entrevistas em cascata | Sem endpoint | `POST /appointments/create-batch` | **P3** |
| Webhook entrevista concluida | Sem webhook | `appointment.completed` com status | **P2** |
| No-show tracking | Sem campo | `PATCH /appointments/{id}` com `status: "no_show"` | **P3** |
| Extensao Scorecard Google Meet | Modulo externo | Fora do escopo | N/A |
| Permissionamento de avaliadores | Sem endpoint | | **P3** |
| **InTerview** (entrevista por WhatsApp) | Sem API testavel | Modulo separado do envio simples — verificar | **P3** |

**Payload — Feedback do entrevistador:**
```json
POST /scorecards
{
  "jobTalentId": "...",
  "stageId": "...",
  "evaluatorEmail": "entrevistador@empresa.com",
  "scores": [
    { "criteriaId": "uuid", "score": 4, "comment": "Bom tecnicamente" }
  ],
  "recommendation": "advance",
  "overallComment": "Candidato forte"
}
```

**ACAO IMEDIATA:** Liberar `GET /scorecards` para o service account (hoje 403).

---

## 5. Carta oferta

### Eli FAZ
- Criar carta oferta com template (selecao inteligente por nome/numero)
- Coleta salario, data de inicio, aprovador
- Fluxo de aprovacao interna
- Enviar notificacao ao candidato (ClickSign)
- Cancelar oferta
- Mostrar link do documento PDF

### Gaps

| Funcionalidade | Status | Endpoint necessario | Prioridade |
|---|---|---|---|
| Variaveis completas do template | Sem endpoint | `GET /offer-letters/templates/{templateId}` com `requiredVariables[]` | **P2** |
| Webhooks de oferta | Sem webhook | `offer-letter.signed`, `.viewed`, `.approved`, `.rejected` | **P2** |
| Registro de recusa do candidato | Sem endpoint | `POST /offer-letters/{id}/decline` | **P2** |
| Contraproposta/renegociacao | Sem endpoint | `PATCH /offer-letters/{id}` ou `POST /revise` | **P3** |
| Desativar aprovacao (enviar direto) | Nao exposto | `skipApprovalFlow` existe — expor no agente | **P3** |

**Payload — Webhooks:**
```
offer-letter.signed  -> { "offerId", "jobTalentId", "signedAt" }
offer-letter.viewed  -> { "offerId", "viewedAt" }
offer-letter.approved -> { "offerId", "approverEmail", "approvedAt" }
offer-letter.rejected -> { "offerId", "approverEmail", "reason" }
```

**Payload — Registro de recusa:**
```json
POST /offer-letters/{offerId}/decline
{
  "reason": "salary | counter_offer | another_opportunity | personal | other",
  "details": "Aceitou proposta de outra empresa",
  "counterOfferValue": 15000.00
}
```

---

## 6. Comunicacao com candidatos

### Eli FAZ
- Email via Amazon SES (`POST /comms/emails/submissions`)
- Templates de email
- WhatsApp (mensagem livre)
- Notificacao de mudanca de etapa ao candidato (opt-in)
- Devolutiva em massa pos-fechamento
- Comemoracao de contratacao (webhook)

### Gaps

| Funcionalidade | Status | Endpoint/Acao | Prioridade |
|---|---|---|---|
| Historico de comunicacao | Sem endpoint | `GET /comms/{jobTalentId}/history` | **P2** |
| **Agendar email** (futuro) | Nao testado | Verificar se API aceita `scheduledAt` | **P2** |
| Email em massa otimizado | Parcial | API aceita `jobTalentIds[]` mas agente envia 1 a 1 | **P3** |
| Conectar email pessoal (Google/Outlook) | Fora do escopo | Requer OAuth do recrutador | N/A |

---

## 7. Banco de talentos

### Eli FAZ
- Busca full-text (Typesense, 86k+ talentos)
- Buscar por email e LinkedIn
- Buscar multiplos por IDs em batch
- Deduplicacao automatica
- Reaproveitar talento em nova vaga
- Adicionar talento a partir de analise de perfil

### Gaps

| Funcionalidade | Status | Endpoint/Acao | Prioridade |
|---|---|---|---|
| Talent pools nomeados | Sem endpoint | `GET/POST /talent-pools/{poolId}/talents` | **P2** |
| Filtros avancados (cruzar fonte, processo, etapa) | Typesense e texto livre | Filtros estruturados ou endpoint dedicado | **P3** |
| Historico completo do talento | Sem endpoint | `GET /talents/{id}/history` | **P3** |
| Classificar talentos (Gostei/Amei/Nao gostei) | Sem endpoint | `PATCH /talents/{id}` com `classification` | **P3** |
| **Smart CV** (CV padronizado editavel) | Feature UI | Sem API — recrutador monta no InHire | N/A |
| Compartilhar Smart CV com gestor | Feature UI | | N/A |
| Ocultar dados sensiveis (reduzir vies) | Feature UI | | N/A |
| Anexar/download de CV | 403 | Liberar `GET /talents/{id}/files` e `GET /files/{id}` | **P2** |

---

## 8. Analytics e dados

### Eli FAZ
- SLA da vaga (dias aberta)
- Funil de conversao visual (barra por etapa com %)
- Previsao de fechamento (Haiku)
- Comparacao entre vagas (ranking por velocidade)
- Relatorio semanal consolidado (seg 9:30 BRT)
- Alertas de pipeline parado (escalonamento 3d/7d/14d)
- Briefing diario (9h BRT)
- **Tempo medio por etapa** via timeline (sessao 40) — `GET /job-talents/{jt}/timeline`
- **Historico de movimentacao** — endpoint EXISTE: `GET /job-talents/{id}/timeline` + `POST /job-talents/stages/history`

### Gaps restantes

| Funcionalidade | Status | Endpoint/Acao | Prioridade |
|---|---|---|---|
| **Modulo de Reporting** (3 visualizacoes) | Feature UI | Listagem, hunting, periodo | N/A |
| Dashboard personalizado por empresa | Feature UI | | N/A |
| Exportar dados/relatorios | Sem API | | **P3** |
| Dashboard de indicacoes | Feature UI | | N/A |

---

## 9. Diversidade e compliance

| Funcionalidade | Status |
|---|---|
| Vagas afirmativas | Feature UI |
| Dados sensiveis LGPD | Feature UI |
| Politica de privacidade configuravel | Feature UI |
| Acessibilidade (Libras, alto contraste) | Feature UI |
| Modulo de Diversidade completo | Feature UI |

---

## 10. Integracoes e extensoes

### Eli FAZ
- API REST (~55 endpoints implementados)
- Webhooks (stage change, contratacao)
- Slack bot completo (DM + botoes + interacoes)
- Automacoes de vaga (`POST /workflows/automations`)
- Tags em candidatos (`POST /job-talents/tags/add/batch`)

### Fora do escopo
- Extensao Chrome Hunting (LinkedIn) — modulo externo
- Extensao Scorecard Google Meet — modulo externo
- Importacao de dados de ATS antigo — feature de onboarding

---

## Resumo numerico

| Status | Qtd | % |
|---|---|---|
| Funcional no agente | **48** | 51% |
| Parcial | **8** | 8% |
| Precisa de endpoint novo | **12** | 13% |
| Feature UI (fora do escopo) | **22** | 23% |
| Modulo externo (Mindsight/Chrome) | **5** | 5% |
| **Total mapeado** | **95** | 100% |

> **Atualizado sessao 40:** Varredura do codigo-fonte InHire revelou 15 endpoints que existiam mas nao sabiamos. Timeline, screening on-demand, automacoes, tags, scorecards detalhados — todos disponiveis.

---

## Consolidacao — Pedidos ao Time InHire

### Permissoes a liberar (acao imediata, sem desenvolvimento)

| Endpoint | Status | Impacto |
|---|---|---|
| `GET /scorecards` | 403 | Feedback de entrevistadores |
| `GET /users` | 403 | Onboarding sem hack |
| `GET /team` | 403 | Dados do time |
| `GET /talents/{id}/files` | 403 | Acesso a CVs |
| `GET /files/{id}` | 403 (auth S3) | Download de arquivos |

### P1 — ~~Criticos~~ RESOLVIDOS (descobertos no codigo-fonte)

| # | Endpoint | Status |
|---|---|---|
| ~~1~~ | ~~Formulario de inscricao~~ | ✅ `GET /forms/job-id/{jobId}` + `PATCH /forms/{formId}` + `POST /forms` |
| ~~2~~ | ~~Triagem IA~~ | ✅ `PATCH /jobs/{id}` com `screeningSettings` + `resumeAnalyzer` |
| ~~3~~ | ~~Divulgacao em portais~~ | ✅ `GET /integrations` + `POST /job-posts/pages` |
| ~~4~~ | ~~Historico de movimentacao~~ | ✅ `GET /job-talents/{id}/timeline` + `POST /stages/history` |
| ~~5~~ | ~~Scorecards~~ | ✅ `GET/POST /forms/scorecards/jobs/{jobId}` + avaliacao por candidato |

### Pendentes — Ainda precisam do InHire

| # | Endpoint | O que falta | Prioridade |
|---|---|---|---|
| 1 | Liberar `GET /scorecards` (403) | Permissao do service account | **P1** |
| 2 | Liberar `GET /users` (403) | Onboarding sem hack | **P1** |
| 3 | Liberar `GET /talents/{id}/files` (403) | Acesso a CVs | **P2** |
| 4 | `POST /talent-pools/{poolId}/talents` | Talent pools / silver medalist | **P2** |
| 5 | `GET /comms/emails/submissions/{jobTalentId}` | Historico de comunicacao por candidato | **P2** |
| 6 | `POST /offer-letters/{id}/decline` | Registro de recusa com motivo | **P2** |
| 7 | Contraproposta de oferta | `PATCH /offer-letters/{id}` ou `POST /revise` | **P3** |
| 8 | Campos personalizados | `GET /custom-fields` — verificar se ja existe no jobs service | **P3** |
| 9 | `POST /job-talents/reaction/{id}` | Classificar candidatos (implementar no agente) | **P3** |
| 10 | Envio de testes Mindsight via API | Modulo externo — verificar se tem rota publica | **P3** |

### Endpoints descobertos no codigo que o agente ainda nao usa (proximos a implementar)

| # | Endpoint | O que faz |
|---|---|---|
| 1 | `POST /forms/ai/generate-subscription-form` | IA gera perguntas do formulario a partir da JD |
| 2 | `POST /search-talents/ai/generate-job-talent-filter` | IA gera filtros Typesense |
| 3 | `GET /forms/scorecards/interview-kit-fill/{id}/jobTalent/{jt}` | Kit de entrevista completo |
| 4 | `POST /forms/scorecards/jobTalent/{jt}/{interviewId}` | Registrar avaliacao de entrevista |
| 5 | `POST /forms/ai/generate-feedback` | IA gera feedback de scorecard |
| 6 | `POST /forms/surveys` | Agendar pesquisa de experiencia (NPS) |
| 7 | `GET /forms/surveys/jobs/{jobId}/metrics` | Metricas de surveys |
| 8 | `POST /forms/comms/disc/send/email` | Enviar teste DISC |
| 9 | `POST /forms/{typeformId}/comms/send/email` | Enviar qualquer formulario por email |
| 10 | `GET /jobs/templates` + `POST /jobs/templates` | Templates de vaga |
| 11 | `POST /jobs/stages` + `PATCH /jobs/stages` | Pipeline customizado |
| 12 | `POST /jobs/duplicate` | Duplicar vaga |
| 13 | `GET /talents/smartcv` + `POST /talents/smartcv` | Smart CV |
| 14 | `GET /referrals` + `POST /referrals` | Programa de indicacao |
| 15 | `GET /offer-letters/templates/{id}` | Template com variaveis detalhadas |

---

## Historico

- **Sessao 40 (2026-04-14):** Criacao do mapeamento + 18 features + pesquisa Help Center + varredura codigo-fonte InHire
- Varredura revelou ~500 rotas HTTP em 10+ servicos. 15 endpoints que achavamos inexistentes ja existiam
- Cobertura saltou de 35% para 51% das funcionalidades mapeadas
