# Mapeamento de Gaps — API InHire × Agente Eli

> **DEPRECADO:** Este documento e um snapshot da sessao 40. O documento canonical e `MAPA_COBERTURA_ELI.md` na raiz do projeto.

> **Data:** 2026-04-13
> **Objetivo duplo:** (1) Backlog de desenvolvimento do agente Eli, (2) Pedido de endpoints ao time InHire
> **Organização:** Por fase do funil de recrutamento

---

## Legenda

| Símbolo | Significado |
|---|---|
| ✅ | Funcional no agente e na API |
| 🟡 | Parcial — funciona mas com limitações |
| ❌ Agente | Não implementado no agente (API existe) |
| ❌ API | Endpoint não existe na API InHire |
| ❌ 403 | Endpoint existe mas service account não tem permissão |

---

## Resumo executivo

O agente Eli cobre o **core do ciclo de recrutamento** — criar vaga, listar candidatos, triagem, mover/reprovar, agendar entrevista, carta oferta, e comunicação (email + WhatsApp). Porém, cada fase tem gaps que impedem a automação completa:

- **Abertura de vaga:** Cria a vaga mas não configura formulário, triagem IA, scorecard, nem divulgação
- **Sourcing:** Maduro — 4 endpoints disponíveis não utilizados (quick wins)
- **Triagem:** Core funciona, mas não configura screening IA nem persiste rankings
- **Entrevistas:** Agendar/cancelar funciona, mas sem calendário real, testes, ou feedback
- **Oferta:** Caso feliz funciona, mas sem negociação, acompanhamento de assinatura, ou recusa
- **Contratação:** Comunicação básica funciona, mas sem fluxos automáticos pós-fechamento
- **Analytics:** Fase mais carente — tudo é calculado manualmente sem histórico de movimentação

**Totais:**
- Funcionalidades mapeadas: **73**
- Funcionais: **28**
- Só precisam de dev no agente: **18**
- Precisam de endpoint novo na API: **22**
- Precisam de permissão no service account: **5**

---

## Fase 1 — Abertura de Vaga

### Gap Matrix

| Funcionalidade | Status Agente | Status API | Falta no Agente | Falta na API | Prioridade |
|---|---|---|---|---|---|
| Briefing conversacional | ✅ | — | — | — | — |
| Geração de JD (Claude) | ✅ | — | — | — | — |
| Criar vaga no InHire | ✅ | ✅ `POST /jobs` | — | — | — |
| **Formulário de inscrição** | ❌ | ❌ API | Implementar fluxo após criar vaga | Endpoint necessário | P1 |
| **Perguntas eliminatórias** | ❌ | ❌ API | Coletar perguntas no briefing | Incluir no endpoint de formulário | P1 |
| **Configurar triagem IA** | ❌ | ❌ API | Extrair critérios do briefing | Endpoint necessário | P1 |
| **Scorecard de entrevista** | ❌ | ❌ 403 | Gerar a partir do briefing | Liberar permissão + POST | P2 |
| **Divulgação em portais** | ❌ | ❌ API | Perguntar onde publicar | Endpoint necessário | P1 |
| **Pipeline customizado** | ❌ | ❌ API | Sugerir pipeline por tipo de vaga | Endpoint necessário | P3 |
| **Templates de vaga** | ❌ | ❓ Não verificado | Reutilizar config de vagas similares | Endpoint necessário | P3 |

### Detalhe técnico — Pedido ao InHire

#### 1.1 Formulário de inscrição + Perguntas eliminatórias

**Necessidade:** Quando o Eli cria uma vaga, poder configurar o formulário que candidatos preenchem ao se inscrever.

```
GET /jobs/{jobId}/application-form
→ Retorna: { fields: [...], questions: [...] }

PUT /jobs/{jobId}/application-form
← Payload: {
    "fields": [
      { "name": "phone", "required": true },
      { "name": "linkedin", "required": false },
      { "name": "salary_expectation", "required": true }
    ],
    "questions": [
      {
        "text": "Você tem disponibilidade para início imediato?",
        "type": "yes_no",
        "eliminatory": true,
        "expected_answer": "yes"
      },
      {
        "text": "Quantos anos de experiência com Python?",
        "type": "numeric",
        "eliminatory": true,
        "min_value": 3
      }
    ]
  }
```

**Impacto:** Sem isso, todo candidato que se inscreve entra sem filtro — recrutador precisa configurar manualmente no InHire UI.

#### 1.2 Configuração da triagem IA

**Necessidade:** Configurar os critérios que o agente de screening do InHire usa para pontuar candidatos.

```
POST /jobs/{jobId}/screening-config
← Payload: {
    "criteria": [
      { "name": "Python", "weight": "essential", "description": "3+ anos" },
      { "name": "FastAPI", "weight": "important" },
      { "name": "Docker", "weight": "nice_to_have" }
    ],
    "auto_reject_below": 2.0,
    "auto_approve_above": 4.0
  }

GET /jobs/{jobId}/screening-config
→ Retorna: configuração atual
```

**Impacto:** Sem isso, triagem IA não roda — candidatos orgânicos ficam todos com score "Pendente".

#### 1.3 Divulgação em portais

**Necessidade:** Publicar a vaga em portais de emprego diretamente do agente.

```
GET /jobs/{jobId}/publish/channels
→ Retorna: [
    { "id": "linkedin", "name": "LinkedIn", "connected": true },
    { "id": "indeed", "name": "Indeed", "connected": true },
    { "id": "careers_page", "name": "Página de Carreiras", "connected": true }
  ]

POST /jobs/{jobId}/publish
← Payload: {
    "channels": ["linkedin", "indeed", "careers_page"]
  }
→ Retorna: { "published": ["linkedin", "indeed"], "failed": [] }
```

**Impacto:** Sem isso, recrutador precisa entrar no InHire UI pra publicar — é o passo mais comum após criar a vaga.

#### 1.4 Scorecard de entrevista

**Necessidade:** Configurar critérios de avaliação que entrevistadores usam.

```
POST /jobs/{jobId}/scorecard
← Payload: {
    "stageId": "uuid-da-etapa-entrevista",
    "criteria": [
      { "name": "Comunicação", "description": "Clareza e objetividade", "scale": 5 },
      { "name": "Conhecimento técnico", "description": "Domínio da stack", "scale": 5 },
      { "name": "Fit cultural", "description": "Alinhamento com valores", "scale": 5 }
    ]
  }

GET /jobs/{jobId}/scorecard
→ Retorna: configuração atual (hoje retorna 403)
```

**Ação adicional:** Liberar permissão de `GET /scorecards` para o service account.

---

## Fase 2 — Sourcing

### Gap Matrix

| Funcionalidade | Status Agente | Status API | Falta no Agente | Falta na API | Prioridade |
|---|---|---|---|---|---|
| Busca LinkedIn (strings booleanas) | ✅ | — | — | — | — |
| Busca banco de talentos (Typesense) | ✅ | ✅ | — | — | — |
| Análise de perfil (Claude) | ✅ | — | — | — | — |
| Adicionar talento à vaga | ✅ | ✅ | — | — | — |
| **Buscar talento por email** | ❌ Agente | ✅ `GET /talents/email/{email}` | Implementar — deduplicar antes de adicionar | — | P2 |
| **Buscar talento por LinkedIn** | ❌ Agente | ✅ `GET /talents/linkedin/{username}` | Extrair username de URL e buscar | — | P2 |
| **Buscar múltiplos por ID** | ❌ Agente | ✅ `POST /talents/ids` | Enriquecer shortlists com dados completos | — | P3 |
| **Talentos paginado** | ❌ Agente | ✅ `POST /talents/paginated` | Fallback quando key Typesense expira | — | P3 |
| **Análise → criar candidato** | ❌ Agente | ✅ Endpoints existem | Fluxo: Claude analisa → recrutador aprova → cria talento + linka à vaga | — | P1 |
| **Programa de indicações** | ❌ | ❌ API | Pedir indicações via Slack | Endpoint necessário | P3 |
| **Integração LinkedIn Recruiter** | ❌ | ❌ API | Buscar direto no LinkedIn | API LinkedIn separada | P4 |

### Detalhe técnico — Dev no Agente (sem depender do InHire)

#### 2.1 Busca por email e LinkedIn

Endpoints já existem. Implementar no `inhire_client.py`:
- `get_talent_by_email(email: str)` → `GET /talents/email/{email}`
- `get_talent_by_linkedin(username: str)` → `GET /talents/linkedin/{username}`

**Uso principal:** Quando recrutador cola um perfil do LinkedIn, extrair username e verificar se já está no banco antes de criar duplicata.

#### 2.2 Fluxo "analisei → adicionei"

Hoje `_analyze_profile()` retorna análise mas não oferece ação. Implementar:
1. Claude analisa perfil → retorna fit score
2. Se fit alto, oferecer botão "Adicionar à vaga X"
3. Ao clicar, extrair dados do perfil (nome, email, LinkedIn) → `add_talent_to_job()`

---

## Fase 3 — Triagem

### Gap Matrix

| Funcionalidade | Status Agente | Status API | Falta no Agente | Falta na API | Prioridade |
|---|---|---|---|---|---|
| Listar candidatos com scores | ✅ | ✅ | — | — | — |
| Classificar por fit | ✅ | — | — | — | — |
| Gerar shortlist | ✅ | — | — | — | — |
| Mover candidatos (batch) | ✅ | ✅ | — | — | — |
| Reprovar em lote | ✅ | ✅ | — | — | — |
| **Scores detalhados (critério a critério)** | ❌ | ❌ API | Mostrar por que o score é X | `GET /jobs/{id}/screening-results` | P2 |
| **Triagem sob demanda (hunting)** | ❌ | ❌ API | Disparar screening para candidatos de hunting | `POST /job-talents/{jt}/screening/run` | P2 |
| **Motivo de rejeição inteligente** | 🟡 Hardcoded "other" | ✅ API aceita enum | Usar Claude pra inferir motivo | — | P1 |
| **Devolutiva personalizada** | 🟡 Template genérico | ✅ API aceita comment | Gerar por candidato com Claude | — | P1 |
| **Sugestão de reprovação InHire** | ❌ Agente | ✅ `POST /reproval/suggestion/{jt}` | Usar antes de reprovar | — | P2 |
| **Persistir ranking/notas** | ❌ | ❌ API | Salvar análise do Claude na InHire | Campo `notes` ou `ranking` no job-talent | P3 |
| **Tags em candidatos** | ❌ | ❌ API | Taggar candidatos | `POST /job-talents/{jt}/tags` | P3 |
| **Filtro por etapa** | 🟡 Parcial | ✅ Dados vêm na API | Filtrar quando recrutador pede | — | P1 |

### Detalhe técnico — Pedido ao InHire

#### 3.1 Triagem sob demanda para hunting

**Necessidade:** Candidatos adicionados via hunting não passam pelo screening automático. Precisamos disparar manualmente.

```
POST /job-talents/{jobTalentId}/screening/run
→ Retorna: { "status": "queued", "estimatedTime": "30s" }

// Webhook ou polling:
GET /job-talents/{jobTalentId}/screening/status
→ Retorna: { "status": "completed", "score": 4.2, "details": [...] }
```

#### 3.2 Scores detalhados

```
GET /jobs/{jobId}/screening-results
→ Retorna: [
    {
      "jobTalentId": "...",
      "overallScore": 4.2,
      "criteria": [
        { "name": "Python", "score": 5, "evidence": "10 anos de experiência mencionados" },
        { "name": "FastAPI", "score": 3, "evidence": "Mencionou uso em 1 projeto" }
      ]
    }
  ]
```

### Detalhe técnico — Dev no Agente

#### 3.3 Motivo de rejeição inteligente

Alterar `_reject_candidates()` em [candidates.py](app/routers/handlers/candidates.py):
- Antes de reprovar, pedir ao Claude: "dado este perfil e esta vaga, o motivo é overqualified, underqualified, location, ou other?"
- Usar o motivo retornado no campo `reason` em vez de hardcoded "other"

#### 3.4 Filtro por etapa

Alterar `_check_candidates()`: quando recrutador diz "quem tá na entrevista?", filtrar `applications` por `stageId` antes de exibir.

---

## Fase 4 — Entrevistas

### Gap Matrix

| Funcionalidade | Status Agente | Status API | Falta no Agente | Falta na API | Prioridade |
|---|---|---|---|---|---|
| Agendar entrevista (manual) | ✅ | ✅ | — | — | — |
| Cancelar entrevista | ✅ | ✅ | — | — | — |
| Listar entrevistas do candidato | ✅ | ✅ | — | — | — |
| Listar entrevistas do recrutador | ✅ | ✅ | — | — | — |
| Verificar disponibilidade | ✅ | ✅ | — | — | — |
| WhatsApp pós-agendamento | ✅ | ✅ | — | — | — |
| **Atualizar entrevista** | ❌ Agente | ✅ `PATCH /appointments/{id}` | Implementar — remarcar sem cancelar | — | P2 |
| **Integração calendário** | ❌ | ❌ API | Link de Meet/Zoom automático | Provider google/microsoft no service account | P2 |
| **Entrevistas em cascata** | ❌ | ❌ API | Sequência RH → técnica → gestor | Orquestrar no agente ou `POST batch` | P3 |
| **Enviar teste** | ❌ | ❌ API | Disparar teste pro candidato | `POST /tests/{testId}/send` | P2 |
| **Feedback do entrevistador** | ❌ | ❌ 403 | Coletar avaliação via Slack | `POST /scorecards` + liberar GET | P1 |
| **Lembrete de entrevista** | ❌ Agente | — | Slack/WhatsApp X horas antes | — (APScheduler) | P1 |
| **Status pós-entrevista** | ❌ | ❌ API | Perguntar "como foi?" | Webhook `appointment.completed` | P2 |
| **Kit de entrevista** | ❌ | ❌ API | CV + scorecard + perguntas ao entrevistador | `GET /jobs/{id}/interview-kit` ou montar no agente | P3 |
| **No-show tracking** | ❌ | ❌ API | Detectar candidato ausente | Campo `status: "no_show"` no PATCH | P3 |

### Detalhe técnico — Pedido ao InHire

#### 4.1 Feedback do entrevistador (Scorecard)

**Necessidade:** Após entrevista, entrevistador avalia o candidato. Hoje retorna 403.

```
POST /scorecards
← Payload: {
    "jobTalentId": "...",
    "stageId": "...",
    "evaluatorEmail": "entrevistador@empresa.com",
    "scores": [
      { "criteriaId": "uuid", "score": 4, "comment": "Muito bom tecnicamente" }
    ],
    "recommendation": "advance",  // advance | hold | reject
    "overallComment": "Candidato forte, recomendo avançar"
  }

GET /scorecards?jobTalentId={jt}
→ Retorna: avaliações registradas (LIBERAR PERMISSÃO service account)
```

**Impacto:** Sem feedback estruturado, recrutador não tem dados pra decidir quem avança. É o gap mais crítico desta fase.

#### 4.2 Envio de testes

```
GET /jobs/{jobId}/available-tests
→ Retorna: [
    { "id": "disc", "name": "DISC", "provider": "mindsight", "duration": "15min" },
    { "id": "tech-python", "name": "Teste Técnico Python", "provider": "inhire", "duration": "60min" }
  ]

POST /jobs/{jobId}/tests/{testId}/send
← Payload: { "jobTalentIds": ["id1", "id2"] }
→ Retorna: { "sent": 2, "failed": 0 }
```

#### 4.3 Webhook de status de entrevista

```
Webhook: appointment.completed
Payload: {
  "appointmentId": "...",
  "jobTalentId": "...",
  "status": "completed" | "no_show" | "cancelled_late",
  "completedAt": "2026-04-13T15:00:00Z"
}
```

### Detalhe técnico — Dev no Agente

#### 4.4 Lembrete de entrevista

Usar APScheduler (já configurado no projeto):
1. Ao criar appointment, agendar job de lembrete para `startDateTime - 2h`
2. No trigger, enviar mensagem no Slack ao recrutador + WhatsApp ao candidato
3. Dados do appointment já existem — só precisa orquestrar

---

## Fase 5 — Oferta

### Gap Matrix

| Funcionalidade | Status Agente | Status API | Falta no Agente | Falta na API | Prioridade |
|---|---|---|---|---|---|
| Criar carta oferta | ✅ | ✅ | — | — | — |
| Listar templates | ✅ | ✅ | — | — | — |
| Enviar notificação ao candidato | ✅ | ✅ | — | — | — |
| Cancelar oferta | ✅ | ✅ | — | — | — |
| **URL do documento** | ❌ Agente | ✅ `GET /offer-letters/document/{id}` | Implementar — ver PDF antes de enviar | — | P1 |
| **Settings de oferta** | ❌ Agente | ✅ `GET /offer-letters/settings` | Implementar — saber aprovadores e provider | — | P2 |
| **Seleção de template** | 🟡 Usa primeiro | ✅ API retorna lista | Perguntar ao recrutador ou inferir | — | P1 |
| **Data de início** | 🟡 Vazio | ✅ API aceita | Coletar no fluxo conversacional | — | P1 |
| **Variáveis completas** | 🟡 Só 3 campos | ✅ API aceita dict | Ler campos do template, coletar todos | Template com `requiredVariables[]` | P2 |
| **Status da assinatura** | ❌ | ❌ API | Avisar quando candidato assinou | Webhook `offer.signed` / `offer.viewed` | P2 |
| **Contraproposta** | ❌ | ❌ API | Renegociar valores | `PATCH` ou `POST /revise` | P3 |
| **Ofertas comparativas** | ❌ Agente | ✅ `GET /offer-letters` | Comparar finalistas lado a lado | — | P3 |
| **Aprovação interna (notificação)** | 🟡 Via InHire | ✅ Campo `approvals` | Notificar no Slack | Webhook `offer.approved` / `offer.rejected` | P2 |
| **Registro de recusa** | ❌ | ❌ API | Registrar motivo quando candidato recusa | `POST /offer-letters/{id}/decline` | P2 |

### Detalhe técnico — Pedido ao InHire

#### 5.1 Webhooks de oferta

```
Webhook: offer-letter.signed
Payload: { "offerId": "...", "jobTalentId": "...", "signedAt": "..." }

Webhook: offer-letter.viewed
Payload: { "offerId": "...", "viewedAt": "..." }

Webhook: offer-letter.approved
Payload: { "offerId": "...", "approverEmail": "...", "approvedAt": "..." }

Webhook: offer-letter.rejected
Payload: { "offerId": "...", "approverEmail": "...", "reason": "..." }
```

#### 5.2 Variáveis do template

```
GET /offer-letters/templates/{templateId}
→ Retorna: {
    "id": "...",
    "name": "Template CLT",
    "requiredVariables": [
      { "key": "salario", "label": "Salário", "type": "currency" },
      { "key": "dataInicio", "label": "Data de início", "type": "date" },
      { "key": "beneficios", "label": "Benefícios", "type": "text" },
      { "key": "bonus", "label": "Bônus", "type": "currency" }
    ]
  }
```

#### 5.3 Registro de recusa

```
POST /offer-letters/{offerId}/decline
← Payload: {
    "reason": "salary" | "counter_offer" | "another_opportunity" | "personal" | "other",
    "details": "Aceitou proposta de outra empresa com salário 20% maior",
    "counterOfferValue": 15000.00  // opcional
  }
```

### Detalhe técnico — Dev no Agente

#### 5.4 Quick wins (sem depender do InHire)

1. **URL do documento:** Chamar `GET /offer-letters/document/{id}` e enviar link no Slack
2. **Seleção de template:** Listar templates, mostrar opções, deixar recrutador escolher
3. **Data de início:** Adicionar pergunta no fluxo de coleta: "Qual a data de início prevista?"

---

## Fase 6 — Contratação e Comunicação

### Gap Matrix

| Funcionalidade | Status Agente | Status API | Falta no Agente | Falta na API | Prioridade |
|---|---|---|---|---|---|
| Comemoração contratação | ✅ | ✅ Webhook | — | — | — |
| Enviar email | ✅ | ✅ | — | — | — |
| Templates de email | ✅ | ✅ | — | — | — |
| Enviar WhatsApp | ✅ | ✅ | — | — | — |
| **Devolutiva em massa pós-fechamento** | ❌ Agente | ✅ Endpoints existem | Orquestrar reject batch + email quando vaga fecha | — | P1 |
| **Email personalizado** | 🟡 Mesmo body | ✅ API aceita body livre | Gerar com Claude por candidato | — | P1 |
| **Silver medalist (banco de talentos)** | ❌ | ❌ API | Marcar candidatos bons pra vagas futuras | `POST /talent-pools/{poolId}/talents` | P2 |
| **Comunicação multi-canal** | 🟡 Canais separados | ✅ Ambos existem | Detectar preferência automaticamente | — | P3 |
| **Templates dinâmicos** | ❌ Agente | ✅ `GET /comms/emails/templates` | Selecionar template por situação | — | P2 |
| **Histórico de comunicação** | ❌ | ❌ API | Ver o que já foi enviado | `GET /comms/{jt}/history` | P2 |
| **Onboarding contratado** | ❌ | ❌ API | Checklist pós-contratação | Provavelmente fora do escopo ATS | P4 |
| **NPS / feedback candidato** | ❌ | ❌ API | Pesquisa de satisfação | Integração externa (Typeform) | P4 |
| **Notificação automática de status** | ❌ Agente | ✅ Webhooks existem | Avisar candidato quando muda de etapa | — (orquestrar webhook + email/WhatsApp) | P2 |

### Detalhe técnico — Pedido ao InHire

#### 6.1 Talent Pools (silver medalist)

```
GET /talent-pools
→ Retorna: [{ "id": "...", "name": "Silver Medalists", "count": 42 }]

POST /talent-pools/{poolId}/talents
← Payload: {
    "talentIds": ["id1", "id2"],
    "tags": ["silver_medalist", "dev_senior"],
    "note": "Bom candidato, não selecionado por timing"
  }

GET /talent-pools/{poolId}/talents
→ Retorna: talentos do pool com tags e notas
```

#### 6.2 Histórico de comunicação

```
GET /comms/{jobTalentId}/history
→ Retorna: [
    { "type": "email", "subject": "...", "sentAt": "...", "status": "delivered" },
    { "type": "whatsapp", "message": "...", "sentAt": "...", "status": "read" }
  ]
```

### Detalhe técnico — Dev no Agente

#### 6.3 Devolutiva em massa pós-fechamento

Fluxo quando webhook detecta contratação:
1. Listar todos os candidatos da vaga ainda ativos
2. Para cada um, gerar devolutiva personalizada com Claude (nome, etapa alcançada, pontos fortes)
3. Reprovar em batch com motivo adequado
4. Enviar email/WhatsApp com devolutiva
5. Oferecer ao recrutador: "Quer salvar alguém como silver medalist?"

#### 6.4 Notificação automática de status

Webhook `job-talent.stage-changed` já existe. Implementar handler:
1. Detectar mudança de etapa
2. Enviar email/WhatsApp ao candidato: "Você avançou para a etapa X na vaga Y"
3. Respeitar preferência de canal do candidato

---

## Fase 7 — Analytics

### Gap Matrix

| Funcionalidade | Status Agente | Status API | Falta no Agente | Falta na API | Prioridade |
|---|---|---|---|---|---|
| SLA da vaga (dias aberta) | ✅ Calculado no agente | — | — | — | — |
| Distribuição por etapa | ✅ | ✅ Dados vêm na API | — | — | — |
| Alertas pipeline parado | ✅ | — | — | — | — |
| **Time-to-hire** | ❌ | ❌ API | Calcular com datas existentes | `GET /analytics/time-to-hire` ou campo `hiredAt` no job-talent | P1 |
| **Funil de conversão** | ❌ Agente | ✅ Dados parciais | Calcular % por etapa com stage_counts | — | P1 |
| **Taxa de aceitação de oferta** | ❌ Agente | 🟡 `GET /offer-letters` | Calcular com status das ofertas | Campo `status` confiável nas ofertas | P2 |
| **Tempo por etapa** | ❌ | ❌ API | Quanto tempo em cada stage | `GET /job-talents/{jt}/history` (essencial) | P1 |
| **Relatório semanal/mensal** | 🟡 Briefing diário | — | Consolidar todas as vagas | — (orquestrar dados existentes) | P1 |
| **Comparação entre vagas** | ❌ Agente | — | Benchmark de vagas | — (dados existem) | P2 |
| **Performance de sourcing** | ❌ | 🟡 Campo `source` existe | Canal que traz mais candidatos | Campo `source` consistente | P2 |
| **Previsão de fechamento** | ❌ | — | Claude com dados históricos | — | P3 |
| **Dashboard exportável** | ❌ | ❌ API | PDF com métricas | Gerar no agente (matplotlib/reportlab) | P4 |
| **Histórico de movimentação** | ❌ | ❌ API | Log de mudanças de etapa | `GET /job-talents/{jt}/history` | P1 |
| **Custo por contratação** | ❌ | ❌ | Input manual ou integração financeira | Fora do escopo ATS | P4 |

### Detalhe técnico — Pedido ao InHire

#### 7.1 Histórico de movimentação (CRÍTICO)

**Este é o endpoint mais importante para analytics.** Sem ele, não é possível calcular tempo por etapa, funil real, nem time-to-hire preciso.

```
GET /job-talents/{jobTalentId}/history
→ Retorna: [
    { "event": "applied", "timestamp": "2026-04-01T10:00:00Z" },
    { "event": "stage_changed", "from": "Triagem", "to": "Entrevista RH", "timestamp": "2026-04-05T14:00:00Z", "changedBy": "user@..." },
    { "event": "stage_changed", "from": "Entrevista RH", "to": "Entrevista Técnica", "timestamp": "2026-04-08T09:00:00Z" },
    { "event": "status_changed", "status": "hired", "timestamp": "2026-04-12T16:00:00Z" }
  ]
```

**Alternativa mínima:** Se o histórico completo é complexo, pelo menos retornar `stageChangedAt` no `GET /job-talents/{jobId}/talents` — a data da última movimentação.

#### 7.2 Analytics agregados (nice to have)

Se o InHire quiser oferecer endpoints prontos:

```
GET /analytics/funnel?jobId={id}
→ { "stages": [{ "name": "Triagem", "entered": 50, "advanced": 20, "rate": 0.4 }, ...] }

GET /analytics/time-to-hire?jobId={id}
→ { "averageDays": 23, "medianDays": 18, "byStage": [{ "name": "Triagem", "avgDays": 5 }, ...] }
```

**Nota:** Se o endpoint 7.1 existir, o agente pode calcular tudo isso sozinho. Os endpoints agregados são conveniência, não bloqueio.

### Detalhe técnico — Dev no Agente

#### 7.3 Quick wins calculáveis com dados atuais

1. **Funil de conversão:** Já temos `stage_counts` — calcular `candidatos_na_etapa / total_candidatos` por stage
2. **Relatório semanal:** Expandir briefing diário — consolidar todas as vagas ativas com métricas
3. **Comparação entre vagas:** Listar vagas, calcular SLA e funil de cada, ordenar por performance
4. **Previsão de fechamento:** Claude analisa velocidade do funil e histórico → estima prazo

---

## Consolidação — Pedidos ao Time InHire

### Endpoints novos necessários (por prioridade)

#### P1 — Críticos (desbloqueiam fluxos inteiros)

| # | Endpoint | Fase | Impacto |
|---|---|---|---|
| 1 | `GET/PUT /jobs/{id}/application-form` | Abertura | Formulário de inscrição configurável |
| 2 | `POST /jobs/{id}/screening-config` | Abertura | Configurar triagem IA |
| 3 | `POST /jobs/{id}/publish` | Abertura | Divulgação em portais |
| 4 | `GET /job-talents/{jt}/history` | Analytics | Histórico de movimentação — base pra toda analytics |
| 5 | `POST /scorecards` + liberar GET | Entrevista | Feedback estruturado de entrevistadores |

#### P2 — Importantes (melhoram significativamente a experiência)

| # | Endpoint | Fase | Impacto |
|---|---|---|---|
| 6 | `POST /jobs/{id}/scorecard` | Abertura | Scorecard configurável |
| 7 | `POST /job-talents/{jt}/screening/run` | Triagem | Screening sob demanda (hunting) |
| 8 | `GET /jobs/{id}/screening-results` | Triagem | Scores detalhados por critério |
| 9 | `GET /offer-letters/templates/{id}` | Oferta | Variáveis obrigatórias do template |
| 10 | Webhooks: `offer.signed`, `offer.approved`, `appointment.completed` | Oferta/Entrevista | Eventos pra automação |
| 11 | `POST /talent-pools/{id}/talents` | Comunicação | Silver medalist |
| 12 | `GET /comms/{jt}/history` | Comunicação | Histórico de comunicação |
| 13 | `POST /offer-letters/{id}/decline` | Oferta | Registro de recusa |

#### P3 — Desejáveis (completam a experiência)

| # | Endpoint | Fase | Impacto |
|---|---|---|---|
| 14 | `PUT /jobs/{id}/stages` | Abertura | Pipeline customizado |
| 15 | `GET /job-templates` | Abertura | Templates de vaga |
| 16 | `POST /job-talents/{jt}/tags` | Triagem | Tags em candidatos |
| 17 | `POST /appointments/create-batch` | Entrevista | Cascata de entrevistas |
| 18 | `GET /jobs/{id}/available-tests` + `POST send` | Entrevista | Envio de testes |
| 19 | `GET /jobs/{id}/interview-kit` | Entrevista | Kit para entrevistador |

#### Permissões a liberar no service account

| Endpoint | Status atual |
|---|---|
| `GET /scorecards` | 403 |
| `GET /users` | 403 |
| `GET /team` | 403 |
| `GET /talents/{id}/files` | 403 |
| `GET /files/{id}` | 403 (auth S3) |

---

## Consolidação — Dev no Agente (sem depender do InHire)

### Quick wins (implementáveis agora)

| # | O que | Fase | Complexidade |
|---|---|---|---|
| 1 | Motivo de rejeição inteligente (Claude infere) | Triagem | Baixa |
| 2 | Devolutiva personalizada por candidato | Triagem | Baixa |
| 3 | Filtro por etapa quando recrutador pede | Triagem | Baixa |
| 4 | Buscar talento por email/LinkedIn | Sourcing | Baixa |
| 5 | URL do documento de oferta | Oferta | Baixa |
| 6 | Seleção de template de oferta | Oferta | Baixa |
| 7 | Coletar data de início na oferta | Oferta | Baixa |
| 8 | Lembrete de entrevista (APScheduler) | Entrevista | Média |
| 9 | Funil de conversão (com dados existentes) | Analytics | Média |
| 10 | Relatório semanal consolidado | Analytics | Média |

### Fluxos novos (mais complexos)

| # | O que | Fase | Complexidade |
|---|---|---|---|
| 11 | Analisar perfil → aprovar → criar candidato | Sourcing | Média |
| 12 | Devolutiva em massa pós-fechamento | Comunicação | Média |
| 13 | Notificação automática de mudança de etapa | Comunicação | Média |
| 14 | Comparação entre vagas | Analytics | Média |
| 15 | Atualizar entrevista (remarcar) | Entrevista | Baixa |
| 16 | Sugestão de reprovação do InHire | Triagem | Baixa |
| 17 | Kit de entrevista (montar no agente) | Entrevista | Média |
| 18 | Previsão de fechamento (Claude) | Analytics | Alta |
