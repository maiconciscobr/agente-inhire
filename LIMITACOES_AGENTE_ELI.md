# Agente Eli — Mapa de Limitacoes e Pedidos de API

> Comparacao entre o que o InHire oferece vs o que o Agente Eli cobre.
> Atualizado: sessao 40 (2026-04-14).
> **Uso duplo:** referencia interna + guia para o time InHire (Andre) sobre endpoints necessarios.

---

## Estado atual do agente

O Eli cobre o core do ciclo de recrutamento: criar vaga, listar candidatos, triagem com score inteligente, mover/reprovar em lote com devolutiva personalizada, agendar entrevista com lembrete, carta oferta com template, e comunicacao com candidatos via email + WhatsApp.

**15 tools funcionais**, **~40 endpoints** implementados, **51 melhorias arquiteturais**.

---

## 1. Criacao e configuracao de vagas

### O que o Eli FAZ
- Extrai dados do briefing (cargo, salario, modelo, requisitos, senioridade)
- Gera job description completa via Claude
- Cria a vaga no InHire via API (`POST /jobs`)

### O que FALTA — precisa de endpoint novo

| Funcionalidade | Endpoint necessario | Impacto | Prioridade |
|---|---|---|---|
| **Formulario de inscricao** | `GET/PUT /jobs/{id}/application-form` | Sem formulario, candidatos entram sem filtro | **P1** |
| **Perguntas eliminatorias** | Incluir no endpoint de formulario: `questions[]` com tipo e resposta esperada | Candidatos nao qualificados passam pela triagem | **P1** |
| **Configurar triagem IA** | `POST /jobs/{id}/screening-config` com criterios (essencial/importante/diferencial) e pesos | Triagem IA nao roda — candidatos ficam "Pendente" | **P1** |
| **Divulgacao em portais** | `POST /jobs/{id}/publish` com lista de canais + `GET /jobs/{id}/publish/channels` | Recrutador precisa entrar no InHire UI pra publicar | **P1** |
| **Scorecard de entrevista** | `POST /jobs/{id}/scorecard` com criterios por etapa | Entrevistadores nao tem criterios estruturados | **P2** |
| **Pipeline customizado** | `PUT /jobs/{id}/stages` | Eli usa pipeline padrao | **P3** |
| **Templates de vaga** | `GET /job-templates` + `POST /jobs` com `templateId` | Nao reutiliza config de vagas similares | **P3** |
| **Custom fields** | `GET /custom-fields` | Eli nao sabe quais campos a empresa usa | **P3** |

### Payloads esperados (detalhes para implementacao)

**Formulario de inscricao:**
```json
PUT /jobs/{jobId}/application-form
{
  "fields": [
    { "name": "phone", "required": true },
    { "name": "linkedin", "required": false },
    { "name": "salary_expectation", "required": true }
  ],
  "questions": [
    {
      "text": "Voce tem disponibilidade para inicio imediato?",
      "type": "yes_no",
      "eliminatory": true,
      "expected_answer": "yes"
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

**Divulgacao:**
```json
GET /jobs/{jobId}/publish/channels
-> [{ "id": "linkedin", "name": "LinkedIn", "connected": true }, ...]

POST /jobs/{jobId}/publish
{ "channels": ["linkedin", "indeed", "careers_page"] }
-> { "published": ["linkedin", "indeed"], "failed": [] }
```

---

## 2. Sourcing e banco de talentos

### O que o Eli FAZ
- Busca LinkedIn (strings booleanas geradas por Claude)
- Busca no banco de talentos (Typesense full-text, 86k+ talentos)
- Analise de perfil colado (Claude avalia fit com a vaga)
- Adicionar talento a vaga (cria ou linka existente)
- Buscar talento por email (`GET /talents/email/{email}`)
- Buscar talento por LinkedIn (`GET /talents/linkedin/{username}`)
- Deduplicacao automatica (verifica email/LinkedIn antes de criar)
- Fluxo "analisei perfil -> adicionar a vaga" com botao de aprovacao

### O que FALTA — precisa de endpoint novo

| Funcionalidade | Endpoint necessario | Prioridade |
|---|---|---|
| **Talent pools** | `GET/POST /talent-pools/{poolId}/talents` | **P2** |
| **Programa de indicacoes** | `GET/POST /referrals` | **P3** |

---

## 3. Triagem de candidatos

### O que o Eli FAZ
- Lista candidatos com scores de triagem (alto/medio/baixo fit)
- Filtra por etapa ("quem ta na entrevista?")
- Gera shortlist comparativo (Claude ranqueia)
- Move candidatos em lote (`POST /job-talents/talents/stages/batch`)
- Reprova em lote com motivo inteligente (Haiku classifica: overqualified/underqualified/location/other)
- Devolutiva personalizada por candidato (nome, etapa alcancada, pontos fortes)
- Consulta sugestao de reprovacao do InHire antes de gerar propria
- Oferece WhatsApp para enviar devolutiva

### O que FALTA — precisa de endpoint novo

| Funcionalidade | Endpoint necessario | Impacto | Prioridade |
|---|---|---|---|
| **Scores detalhados** | `GET /jobs/{id}/screening-results` com score por criterio + evidencia | Recrutador nao sabe POR QUE o score e X | **P2** |
| **Triagem sob demanda** | `POST /job-talents/{jt}/screening/run` | Candidatos de hunting nao tem score automatico | **P2** |
| **Persistir notas/ranking** | Campo `notes` ou `ranking` no `PATCH /job-talents/{jt}` | Analise do Claude nao e salva no InHire | **P3** |
| **Tags em candidatos** | `POST /job-talents/{jt}/tags` | Nao da pra taggar ("forte tecnico", "validar ingles") | **P3** |

### Payload esperado

**Triagem sob demanda:**
```json
POST /job-talents/{jobTalentId}/screening/run
-> { "status": "queued", "estimatedTime": "30s" }

GET /job-talents/{jobTalentId}/screening/status
-> { "status": "completed", "score": 4.2, "details": [...] }
```

---

## 4. Entrevistas

### O que o Eli FAZ
- Agendar entrevista (provider: manual, sem calendario)
- Cancelar entrevista
- Remarcar entrevista (PATCH sem cancelar)
- Listar entrevistas do candidato e do recrutador
- Verificar disponibilidade
- Lembrete automatico 2h antes (APScheduler)
- WhatsApp pos-agendamento

### O que FALTA

| Funcionalidade | Endpoint/Acao necessaria | Impacto | Prioridade |
|---|---|---|---|
| **Integracao calendario** | Liberar `provider: "google"` ou `"microsoft"` no service account | Sem link de Meet/Zoom automatico | **P2** |
| **Feedback do entrevistador** | `POST /scorecards` + **liberar `GET /scorecards` (hoje 403)** | Recrutador nao tem dados estruturados pos-entrevista | **P1** |
| **Enviar teste** | `GET /jobs/{id}/available-tests` + `POST /jobs/{id}/tests/{testId}/send` | Nao dispara DISC/tecnico pro candidato | **P2** |
| **Entrevistas em cascata** | `POST /appointments/create-batch` (ou orquestrar no agente) | Nao agenda RH + tecnica + gestor em sequencia | **P3** |
| **Webhook entrevista concluida** | Webhook `appointment.completed` com status (completed/no_show) | Agente nao sabe quando entrevista acabou | **P2** |
| **Kit de entrevista** | `GET /jobs/{id}/interview-kit` (ou montar no agente) | Entrevistador nao recebe roteiro | **P3** |

### Payload esperado

**Feedback do entrevistador (scorecard):**
```json
POST /scorecards
{
  "jobTalentId": "...",
  "stageId": "...",
  "evaluatorEmail": "entrevistador@empresa.com",
  "scores": [
    { "criteriaId": "uuid", "score": 4, "comment": "Muito bom tecnicamente" }
  ],
  "recommendation": "advance",
  "overallComment": "Candidato forte"
}
```

**ACAO NECESSARIA:** Liberar permissao de `GET /scorecards` para o service account (hoje retorna 403).

---

## 5. Carta oferta

### O que o Eli FAZ
- Criar carta oferta com template
- Selecao inteligente de template (match por nome/numero)
- Coleta data de inicio, salario, aprovador
- Enviar notificacao ao candidato para assinar
- Cancelar oferta
- Mostrar link do documento PDF gerado

### O que FALTA

| Funcionalidade | Endpoint necessario | Prioridade |
|---|---|---|
| **Variaveis do template** | `GET /offer-letters/templates/{templateId}` com `requiredVariables[]` | **P2** |
| **Webhooks de oferta** | `offer-letter.signed`, `offer-letter.viewed`, `offer-letter.approved`, `offer-letter.rejected` | **P2** |
| **Registro de recusa** | `POST /offer-letters/{id}/decline` com motivo e detalhes | **P2** |
| **Contraproposta** | `PATCH /offer-letters/{id}` ou `POST /revise` | **P3** |

### Payload esperado

**Webhooks de oferta:**
```
Webhook: offer-letter.signed
{ "offerId": "...", "jobTalentId": "...", "signedAt": "..." }

Webhook: offer-letter.approved
{ "offerId": "...", "approverEmail": "...", "approvedAt": "..." }
```

---

## 6. Comunicacao com candidatos

### O que o Eli FAZ
- Enviar email via Amazon SES (`POST /comms/emails/submissions`)
- Listar templates de email
- Enviar WhatsApp (`POST /subscription-assistant/.../send`)
- Comemoracao automatica de contratacao (webhook)
- Notificacao ao recrutador sobre candidatos remanescentes pos-fechamento
- Notificacao automatica de mudanca de etapa ao candidato (email, opt-in)

### O que FALTA

| Funcionalidade | Endpoint necessario | Prioridade |
|---|---|---|
| **Historico de comunicacao** | `GET /comms/{jobTalentId}/history` | **P2** |
| **Talent pools (silver medalist)** | `GET/POST /talent-pools/{poolId}/talents` | **P2** |

---

## 7. Analytics

### O que o Eli FAZ
- SLA da vaga (dias aberta)
- Distribuicao por etapa
- Funil de conversao visual (barra por etapa com %)
- Previsao de fechamento (Haiku analisa funil e estima prazo)
- Comparacao entre vagas (ranking por velocidade)
- Relatorio semanal consolidado (seg 9:30 BRT)
- Alertas de pipeline parado (escalonamento 3d/7d/14d)
- Briefing diario (9h BRT)

### O que FALTA — **endpoint mais critico**

| Funcionalidade | Endpoint necessario | Impacto | Prioridade |
|---|---|---|---|
| **Historico de movimentacao** | `GET /job-talents/{jobTalentId}/history` | **Base para TODA analytics real** — sem ele nao da pra calcular tempo por etapa, funil real, nem time-to-hire preciso | **P1** |
| **Analytics agregados** | `GET /analytics/funnel?jobId=` e `GET /analytics/time-to-hire?jobId=` | Nice to have — se o historico existir, o agente calcula sozinho | **P3** |

### Payload esperado

**Historico de movimentacao (CRITICO):**
```json
GET /job-talents/{jobTalentId}/history
[
  { "event": "applied", "timestamp": "2026-04-01T10:00:00Z" },
  { "event": "stage_changed", "from": "Triagem", "to": "Entrevista RH", "timestamp": "2026-04-05T14:00:00Z" },
  { "event": "status_changed", "status": "hired", "timestamp": "2026-04-12T16:00:00Z" }
]
```

**Alternativa minima:** Retornar `stageChangedAt` no `GET /job-talents/{jobId}/talents` — a data da ultima movimentacao.

---

## 8. Testes e avaliacoes

### O que o Eli NAO faz (nada desta area)

| Funcionalidade | Bloqueio |
|---|---|
| Teste DISC | Modulo separado, sem API |
| Testes Mindsight | Modulo separado, sem API |
| Testes tecnicos | Modulo separado, sem API |
| Automacao de envio de testes | Sem endpoint |

---

## 9. Fora do escopo do agente (features visuais/UI)

- Pagina de vagas (careers page)
- Extensoes Chrome (hunting, interview kit do Google Meet)
- Dashboard visual de analytics
- Modulo de diversidade
- Smart CV (edicao visual)
- Programa de indicacao (gamificacao, dashboard)

---

## Resumo consolidado — Pedidos ao InHire

### Permissoes a liberar no service account (acao imediata)

| Endpoint | Status atual | Impacto |
|---|---|---|
| `GET /scorecards` | 403 | Feedback de entrevistadores |
| `GET /users` | 403 | Onboarding sem hack |
| `GET /team` | 403 | Dados do time |
| `GET /talents/{id}/files` | 403 | Acesso a CVs |
| `GET /files/{id}` | 403 (auth S3) | Download de arquivos |

### P1 — Criticos (desbloqueiam fluxos inteiros)

| # | Endpoint | O que desbloqueia |
|---|---|---|
| 1 | `GET/PUT /jobs/{id}/application-form` | Formulario de inscricao configuravel pelo agente |
| 2 | `POST /jobs/{id}/screening-config` | Triagem IA configurada automaticamente a partir do briefing |
| 3 | `POST /jobs/{id}/publish` + `GET channels` | Publicar vaga em portais sem sair do Slack |
| 4 | `GET /job-talents/{jt}/history` | Historico de movimentacao — base para analytics real |
| 5 | `POST /scorecards` + liberar GET | Feedback estruturado de entrevistadores |

### P2 — Importantes

| # | Endpoint | O que melhora |
|---|---|---|
| 6 | `POST /jobs/{id}/scorecard` | Scorecard configurado a partir do briefing |
| 7 | `POST /job-talents/{jt}/screening/run` | Triagem sob demanda para candidatos de hunting |
| 8 | `GET /jobs/{id}/screening-results` | Scores detalhados por criterio |
| 9 | `GET /offer-letters/templates/{templateId}` | Variaveis obrigatorias do template |
| 10 | Webhooks: `offer.signed`, `offer.approved`, `appointment.completed` | Automacoes de oferta e entrevista |
| 11 | `POST /talent-pools/{poolId}/talents` | Silver medalist / banco de talentos |
| 12 | `GET /comms/{jt}/history` | Historico de comunicacao |
| 13 | `POST /offer-letters/{id}/decline` | Registro de recusa com motivo |

### P3 — Desejaveis

| # | Endpoint | O que completa |
|---|---|---|
| 14 | `PUT /jobs/{id}/stages` | Pipeline customizado |
| 15 | `GET /job-templates` | Templates de vaga |
| 16 | `POST /job-talents/{jt}/tags` | Tags em candidatos |
| 17 | `POST /appointments/create-batch` | Cascata de entrevistas |
| 18 | `GET /jobs/{id}/available-tests` + `POST send` | Envio de testes |
| 19 | `GET /jobs/{id}/interview-kit` | Kit para entrevistador |

---

## Spec tecnica completa

Para payloads detalhados de todos os endpoints, ver:
`docs/superpowers/specs/2026-04-13-gap-api-agente-design.md`
