# Agente InHire — APIs necessárias para operação completa

> Documento para o time de desenvolvimento do InHire.
> Objetivo: listar o que falta na API para o agente operar o recrutamento de ponta a ponta via Slack.

**Última atualização:** 4 de abril de 2026
**Autor:** Maicon (Byintera)

---

## Contexto

O agente Eli opera via Slack e executa ações no InHire via API REST. Hoje ele cobre **12 funcionalidades E2E** testadas. Mas várias etapas do processo de recrutamento não podem ser automatizadas porque a API não expõe os endpoints necessários.

Este documento lista exatamente o que falta, organizado por prioridade de impacto.

---

## O que já funciona (sem necessidade de mudança)

| Funcionalidade | Endpoint usado | Status |
|---|---|---|
| Criar vaga | `POST /jobs` | ✅ |
| Listar vagas | `POST /jobs/paginated/lean` | ✅ |
| Detalhe da vaga | `GET /jobs/{id}` | ✅ |
| Listar candidatos | `GET /job-talents/{jobId}/talents` | ✅ |
| Adicionar talento à vaga | `POST /job-talents/{jobId}/talents` | ✅ |
| Adicionar talento com CV | `POST /files` + campo `files[]` | ✅ |
| Mover candidato de etapa | `POST /job-talents/talents/{id}/stages` | ✅ |
| Mover em lote | `POST /job-talents/talents/stages/batch` | ✅ |
| Reprovar candidato | `POST /job-talents/talents/{id}/statuses` | ✅ |
| Reprovar em lote | `POST /job-talents/talents/statuses/batch` | ✅ |
| Criar carta oferta | `POST /offer-letters` | ✅ |
| Listar templates oferta | `GET /offer-letters/templates` | ✅ |
| Registrar webhooks | `POST /integrations/webhooks` | ✅ |
| Listar requisições | `GET /requisitions` | ✅ |

---

## PRIORIDADE CRÍTICA — Bloqueiam funcionalidades core

### 1. Upload real de CV ao S3

**Problema:** `POST /files` cria o registro de metadata do CV, mas o agente não consegue fazer upload do conteúdo binário do PDF. O endpoint de pre-signed URL retorna 403 para o service account.

**O que precisa:**
```
GET /files/upload-url?fileCategory=resumes&fileName={nome}.pdf
```
Retornar uma URL pre-signed do S3 válida para o service account (mesma auth JWT). O agente faz `PUT` no S3 com o binário.

**Impacto:** Hoje o CV é registrado mas o arquivo não fica acessível na UI do InHire. O recrutador não consegue ver o PDF do candidato que o agente cadastrou.

---

### 2. Agendar entrevista em nome de outro usuário

**Problema:** `POST /job-talents/appointments/{id}/create` busca a integração de calendário pelo user do JWT. O service account (Agente IA) não tem calendário integrado, então retorna "Calendar integration not found for user".

**O que precisa (uma das opções):**
- **Opção A:** Aceitar um campo `onBehalfOf` ou `userEmail` no payload que faça o endpoint usar o calendário de outro user
- **Opção B:** Permitir que o service account tenha uma integração de calendário própria
- **Opção C:** Endpoint alternativo que não exija calendário integrado (cria o evento sem link Meet/Teams)

**Impacto:** O agente sabe pedir candidato + data ao recrutador, mas não consegue criar o evento. O recrutador precisa agendar manualmente no InHire.

---

### 3. Configurar divulgação da vaga

**Problema:** Não existe endpoint para configurar visibilidade, portais (LinkedIn, Indeed, Netvagas), nem publicar a vaga após criação.

**O que precisa:**
```
PATCH /jobs/{id}/disclosure
{
  "visibility": "public" | "restricted" | "private",
  "jobBoards": ["linkedin", "indeed", "netvagas"],
  "jobPageId": "uuid-da-pagina-de-vagas",
  "displayName": "Nome de divulgação",
  "jobDescription": "HTML da descrição"
}

POST /jobs/{id}/publish
```

**Impacto:** Hoje o agente cria a vaga mas ela fica sem divulgação. O recrutador precisa abrir o InHire, ir na aba Divulgação e configurar manualmente.

---

### 4. Configurar formulário de inscrição

**Problema:** Não existe endpoint para criar/vincular formulário personalizado a uma vaga.

**O que precisa:**
```
GET /jobs/{id}/custom-form          → ler formulário atual
PUT /jobs/{id}/custom-form          → vincular/atualizar
POST /custom-forms                  → criar formulário
GET /custom-forms                   → listar modelos disponíveis
```

O endpoint `GET /formulario-personalizado` da docs.inhire.com.br parece existir para leitura, mas não testamos. Falta criação e vinculação.

**Impacto:** Candidatos se inscrevem sem formulário personalizado. O agente de triagem IA pode não funcionar corretamente sem as perguntas complementares.

---

## PRIORIDADE ALTA — Melhoram significativamente a experiência

### 5. Configurar agente de triagem IA

**Problema:** Não existe endpoint para definir critérios de triagem, pesos (essencial/importante/diferencial) ou faixa salarial para screening.

**O que precisa:**
```
GET /jobs/{id}/screening/config
PUT /jobs/{id}/screening/config
{
  "criteria": [
    {"description": "Python avançado", "weight": "essential"},
    {"description": "Experiência com AWS", "weight": "important"}
  ],
  "salaryRange": {"min": 15000, "max": 22000}
}
POST /jobs/{id}/screening/reanalyze   → solicitar reanálise
GET /jobs/{id}/screening/distribution → distribuição de fit
```

**Impacto:** Sem configuração via API, o recrutador precisa ir no InHire configurar os critérios manualmente. A triagem IA é uma das features mais importantes do InHire e o agente não consegue ativá-la.

---

### 6. Enviar emails para candidatos

**Problema:** Não encontramos endpoint para envio de email individual ou em lote para candidatos.

**O que precisa:**
```
POST /job-talents/{jobTalentId}/emails
{
  "templateId": "uuid" | null,
  "subject": "Assunto",
  "body": "HTML do email",
  "sendMode": "personal" | "system"
}

POST /job-talents/emails/batch
{
  "jobTalentIds": ["id1", "id2"],
  "templateId": "uuid",
  "sendMode": "system"
}

GET /email-templates              → listar templates
```

**Impacto:** O agente não consegue enviar devolutivas personalizadas por email. Hoje a reprovação em lote usa o campo `comment` mas não envia email ao candidato.

---

### 7. Customizar pipeline (etapas)

**Problema:** `POST /jobs` cria a vaga com pipeline padrão. Não há como adicionar, remover ou reordenar etapas via API.

**O que precisa:**
```
POST /jobs/{id}/stages              → adicionar etapa
PATCH /jobs/{id}/stages/{stageId}   → editar etapa
DELETE /jobs/{id}/stages/{stageId}  → remover etapa
PUT /jobs/{id}/stages/order         → reordenar
```

**Impacto:** Vagas que precisam de pipeline diferente do padrão precisam ser editadas manualmente no InHire.

---

## PRIORIDADE MÉDIA — Complementam a experiência

### 8. Scorecard e Kit de Entrevista

**Problema:** `GET /scorecards` retorna 403 para o service account. Não há endpoints para criar/configurar scorecard ou kit de entrevista.

**O que precisa:**
```
GET /jobs/{id}/scorecard                 → ler configuração
PUT /jobs/{id}/scorecard                 → criar/atualizar
GET /job-talents/{jtId}/scorecards       → ler avaliações preenchidas
GET /job-talents/{jtId}/interview-kit    → ler kit
```

**Impacto:** O agente não consegue consolidar avaliações de entrevista nem gerar resumo comparativo de scorecards.

---

### 9. Busca no Banco de Talentos

**Problema:** Não existe endpoint de busca full-text ou por filtros no banco de talentos.

**O que precisa:**
```
POST /talents/search
{
  "query": "python backend senior",
  "filters": {
    "skills": ["Python", "AWS"],
    "location": "remoto",
    "salaryRange": {"min": 15000, "max": 22000},
    "excludeJobId": "uuid"
  },
  "limit": 20
}
```

**Impacto:** O agente não consegue buscar candidatos de processos anteriores para sugerir para novas vagas.

---

### 10. Criar automações

**Problema:** docs.inhire.com.br menciona `POST /automations` mas não testamos. Não sabemos se funciona para o service account.

**O que precisa confirmar:**
- Endpoint existe e aceita JWT do service account?
- Quais automações podem ser criadas via API? (envio de teste, email por gatilho, ação por mudança de etapa)

**Impacto:** O agente não consegue configurar envio automático de testes ou emails por gatilho.

---

### 11. Relatórios e métricas

**Problema:** Não existe endpoint para relatórios de fechamento, time-to-fill, funil por etapa ou performance por fonte.

**O que precisa:**
```
GET /jobs/{id}/report
→ { timeTofill, funnelByStage, conversionByStage, performanceBySource }

GET /jobs/{id}/metrics
→ { totalByStage, avgTimeByStage, slaStatus, emailResponseRate }
```

**Impacto:** O agente calcula SLA manualmente (dias aberta = now - createdAt). Com endpoint dedicado, poderia dar métricas muito mais ricas.

---

## Bugs conhecidos da API atual

| Bug | Impacto | Workaround |
|---|---|---|
| `GET /jobs` causa 502 (full scan + N+1) | Listagem falha | Usamos `POST /jobs/paginated/lean` |
| `POST /integrations/webhooks` exige `"rules": {}` | 500 sem o campo | Sempre enviamos `"rules": {}` |
| Payload de webhook não tem tipo de evento | Não dá pra rotear | Detectamos pelo conteúdo dos campos |
| `GET /integrations/webhooks` retorna `[]` | Não lista webhooks registrados | Ignoramos, webhooks funcionam |
| `userName` no webhook é quem cadastrou, não o candidato | Nome errado | Buscamos via `GET /talents/{id}` |
| Rejection `reason` é enum não documentado | 406 com texto livre | Descobrimos: overqualified, underqualified, location, other |

---

## Resumo executivo

| Prioridade | Qtd | O que falta |
|---|---|---|
| **Crítica** | 4 | Upload CV ao S3, agendar entrevista, divulgação, formulário |
| **Alta** | 3 | Triagem IA config, emails, customizar pipeline |
| **Média** | 4 | Scorecard, busca talentos, automações, relatórios |

**Com os 4 itens críticos resolvidos, o agente cobre 80% do fluxo de recrutamento sem o recrutador precisar abrir o InHire.**
