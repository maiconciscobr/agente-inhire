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
| **Agente de Triagem** (autonomo, le CV + formulario) | Sem endpoint de config | `POST /jobs/{id}/screening-config` (ver secao 1) | **P1** |
| Scores detalhados (por criterio + evidencia) | Sem endpoint | `GET /jobs/{id}/screening-results` | **P2** |
| Triagem sob demanda (hunting) | Sem endpoint | `POST /job-talents/{jt}/screening/run` | **P2** |
| Persistir notas/ranking do Claude | Sem campo | `PATCH /job-talents/{jt}` com campo `notes` | **P3** |
| Tags em candidatos | Sem endpoint | `POST /job-talents/{jt}/tags` | **P3** |
| Classificar talentos (Gostei/Amei/Nao gostei) | Sem endpoint | `PATCH /talents/{id}` com campo `classification` | **P3** |

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
| **Automacoes de vaga** (acao por mudanca de etapa) | Sem endpoint | `GET/POST /jobs/{id}/automations` | **P2** |
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

### Gaps

| Funcionalidade | Status | Endpoint/Acao | Prioridade |
|---|---|---|---|
| **Historico de movimentacao** | Sem endpoint | `GET /job-talents/{jt}/history` — **base pra toda analytics** | **P1** |
| Time-to-hire | Depende do historico | Calcular no agente com timestamps | **P1** |
| Tempo por etapa | Depende do historico | Idem | **P1** |
| **Modulo de Reporting** (3 visualizacoes) | Feature UI | Listagem, hunting, periodo | N/A |
| Dashboard personalizado por empresa | Feature UI | | N/A |
| Exportar dados/relatorios | Sem API | | **P3** |
| Dashboard de indicacoes | Feature UI | | N/A |

**Payload — Historico de movimentacao (CRITICO):**
```json
GET /job-talents/{jobTalentId}/history
[
  { "event": "applied", "timestamp": "2026-04-01T10:00:00Z" },
  { "event": "stage_changed", "from": "Triagem", "to": "Entrevista RH", "timestamp": "2026-04-05T14:00:00Z" },
  { "event": "status_changed", "status": "hired", "timestamp": "2026-04-12T16:00:00Z" }
]
```

**Alternativa minima:** Retornar `stageChangedAt` no `GET /job-talents/{jobId}/talents`.

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
- API REST (~40 endpoints implementados)
- Webhooks (stage change, contratacao)
- Slack bot completo (DM + botoes + interacoes)

### Fora do escopo
- Extensao Chrome Hunting (LinkedIn) — modulo externo
- Extensao Scorecard Google Meet — modulo externo
- Importacao de dados de ATS antigo — feature de onboarding

---

## Resumo numerico

| Status | Qtd | % |
|---|---|---|
| Funcional no agente | **33** | 35% |
| Parcial | **8** | 8% |
| Precisa de endpoint novo | **27** | 28% |
| Feature UI (fora do escopo) | **22** | 23% |
| Modulo externo (Mindsight/Chrome) | **5** | 5% |
| **Total mapeado** | **95** | 100% |

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

### P1 — Criticos (desbloqueiam fluxos inteiros)

| # | Endpoint | O que desbloqueia |
|---|---|---|
| 1 | `GET/PUT /jobs/{id}/application-form` | Formulario de inscricao configuravel |
| 2 | `POST /jobs/{id}/screening-config` | Triagem IA configurada a partir do briefing |
| 3 | `POST /jobs/{id}/publish` + `GET channels` | Publicar vaga em portais sem sair do Slack |
| 4 | `GET /job-talents/{jt}/history` | Historico de movimentacao — base pra analytics |
| 5 | `POST /scorecards` + liberar GET | Feedback estruturado de entrevistadores |

### P2 — Importantes

| # | Endpoint | O que melhora |
|---|---|---|
| 6 | `POST /jobs/{id}/scorecard` | Scorecard configurado a partir do briefing |
| 7 | `POST /job-talents/{jt}/screening/run` | Triagem sob demanda para candidatos de hunting |
| 8 | `GET /jobs/{id}/screening-results` | Scores detalhados por criterio |
| 9 | `GET /offer-letters/templates/{templateId}` | Variaveis obrigatorias do template |
| 10 | Webhooks: `offer.signed`, `offer.approved`, `appointment.completed` | Automacoes de oferta e entrevista |
| 11 | `POST /talent-pools/{poolId}/talents` | Talent pools / silver medalist |
| 12 | `GET /comms/{jt}/history` | Historico de comunicacao |
| 13 | `POST /offer-letters/{id}/decline` | Registro de recusa com motivo |
| 14 | `GET/POST /jobs/{id}/automations` | Automacoes de vaga (acao por mudanca de etapa) |
| 15 | `GET /jobs/{id}/interview-kit` | Kit de entrevista |

### P3 — Desejaveis

| # | Endpoint | O que completa |
|---|---|---|
| 16 | `PUT /jobs/{id}/stages` | Pipeline customizado |
| 17 | `GET /job-templates` | Templates de vaga |
| 18 | `POST /job-talents/{jt}/tags` | Tags em candidatos |
| 19 | `POST /appointments/create-batch` | Cascata de entrevistas |
| 20 | `GET/POST /jobs/{id}/tests` | Envio de testes |
| 21 | `GET /custom-fields` | Campos personalizados da empresa |
| 22 | `PATCH /talents/{id}` com `classification` | Classificar talentos (Gostei/Amei) |

---

## Historico

- **Sessao 40 (2026-04-14):** Criacao do mapeamento + 18 features implementadas + pesquisa Help Center
- **Spec original (snapshot):** `docs/superpowers/specs/2026-04-13-gap-api-agente-design.md` (historico, nao manter)
- **Plano de implementacao:** `docs/superpowers/plans/2026-04-13-gap-implementation.md`
