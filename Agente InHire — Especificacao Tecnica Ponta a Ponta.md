# Agente de Recrutamento IA — Especificação Técnica Ponta a Ponta

**InHire / Byintera — Março 2026**
**Para:** Glauber & Everton (devs)
**Scope:** APIs necessárias + fluxo completo agente vs. humano

> **Última atualização:** 4 de abril de 2026 (Sessão 7)
> **Status geral:** 12 funcionalidades E2E confirmadas, 15/15 testes PASS (agente inteligente com Claude como juiz). 13 tools de IA, guia InHire integrado.

---

## Status de Implementação por Etapa

| Etapa | Status | Detalhes |
|---|---|---|
| 1. Criação da Vaga | ✅ Funcional E2E | Briefing → extração Claude → JD → aprovação → cria via API |
| 2. Atração de Candidatos | ✅ Parcial | Upload CV (PDF/DOCX), cadastro na vaga, busca LinkedIn (strings booleanas). Hunting ativo manual. |
| 3. Triagem | ✅ Funcional | Screening scores (orgânicos), shortlist comparativo, distribuição de fit |
| 4. Pipeline | ✅ Funcional E2E | Mover (individual + batch) e reprovar (batch, reason=enum) testados com dados reais |
| 5. Entrevistas | ⚠️ Bloqueado | Código pronto, service account sem calendário. Aguardando Andre. |
| 6. Oferta | ⚠️ Bloqueado | Código pronto, pendente validação. Tool retorna "em breve". |
| 7. Fechamento | 🔲 Não implementado | Relatório de fechamento parcial (status/SLA existe). Reprovação em lote bloqueada. |

---

## 1. O Trigger — Como Tudo Começa

**Implementado:** Canal Slack DM. Recrutador manda briefing livre, Claude extrai dados estruturados (cargo, área, salário, requisitos, modelo, urgência).

**Não implementado:**
- Formulário web
- E-mail monitorado
- Contato automático com tech lead (Slack inter-user)

**Como funciona hoje:**

1. Recrutador manda DM para o bot Eli no Slack
2. `detect_intent()` (Claude tool use) identifica intent `criar_vaga`
3. Estado muda para `COLLECTING_BRIEFING`
4. Recrutador complementa info → diz "pronto" ou "gerar"
5. Claude extrai dados estruturados (`extract_job_data`)
6. Claude gera JD (`generate_job_description`)
7. Bot posta rascunho com botões Aprovar/Ajustar/Rejeitar
8. Ao aprovar: `POST /jobs` cria a vaga no InHire

---

## 2. Fluxo Ponta a Ponta — Estado Atual

### Etapa 1 — Criação da Vaga ✅

- **Agente faz:** Extrai briefing, gera JD, sugere info faltante, cria vaga via API
- **Humano faz:** Fornece briefing, aprova/ajusta rascunho
- **Ponto de pausa:** Aprovação antes de publicar ✅ implementado (botões Slack)
- **API:** `POST /jobs` com `name`, `description`, `locationRequired`, `talentSuggestions`, `salaryMin/Max`, `positions`

### Etapa 2 — Atração de Candidatos ✅ Parcial

- **Agente faz:** Upload de CV (PDF/DOCX) via Slack → extrai dados → cadastra na vaga → analisa fit. Gera strings de busca LinkedIn.
- **Não implementado:** Busca no Banco de Talentos (API não pública), monitoramento de volume de candidatos, e-mail de confirmação, Programa de Indicação
- **API:** `POST /job-talents/{jobId}/talents` (funciona!), `GET /talents/{id}`

### Etapa 3 — Triagem ✅

- **Agente faz:** Lista candidatos por fit (alto/médio/baixo/sem score), monta shortlist comparativo com Claude, sugere próximos passos
- **Humano faz:** Aprova shortlist (botões Slack)
- **Limitação:** Screening AI só roda para candidatos orgânicos. Hunting manual não gera score.
- **API:** `GET /job-talents/{jobId}/talents` (retorna screening.score e screening.status)

### Etapa 4 — Pipeline ⚠️ Bloqueado

- **Código pronto para:** Mover candidatos entre etapas, reprovar em lote com devolutiva gerada por Claude
- **Bloqueio:** `inhire_client.py` ainda usa `PATCH /applications/{id}` (endpoint errado). Endpoints corretos documentados: `POST /job-talents/talents/{id}/stages` e `POST /job-talents/talents/{id}/statuses`
- **Decisão:** Adiado. Tools `mover_candidatos` e `reprovar_candidatos` retornam mensagem "em breve".

### Etapa 5 — Entrevistas ⚠️ Bloqueado

- **Código pronto para:** Selecionar candidato, extrair data/hora com Claude, criar appointment
- **Bloqueio:** Endpoint `POST /job-talents/appointments/{jobTalentId}/create` exige que o user do JWT tenha calendário integrado. Service account não tem.
- **Pendente:** Andre resolver como agendar em nome de recrutador via service account
- **Tool:** `agendar_entrevista` retorna mensagem "em breve"

### Etapa 6 — Oferta ⚠️ Bloqueado

- **Código pronto para:** Selecionar candidato, definir salário/aprovador, criar offer letter
- **API testada E2E:** `POST /offer-letters` com `jobTalentId={jobId}*{talentId}`
- **Bloqueio:** Fluxo pendente de validação completa
- **Tool:** `carta_oferta` retorna mensagem "em breve"

### Etapa 7 — Fechamento 🔲

- **Parcialmente implementado:** Relatório de status/SLA (`status_vaga` tool)
- **Não implementado:** Fechar/congelar vaga, reprovação em massa de restantes, tags no banco de talentos, relatório de fechamento completo

---

## 3. Resumo — Agente vs. Humano (Atualizado)

| Momento | Agente executa | Humano decide | Status |
|---|---|---|---|
| Briefing da vaga | Extrai e estrutura dados | Fornece briefing | ✅ |
| Rascunho da vaga | Gera JD com Claude | Revisa e aprova | ✅ |
| Publicação | Cria via API após aprovação | — | ✅ |
| Upload de CV | Extrai, cadastra, analisa fit | — | ✅ |
| Busca LinkedIn | Gera strings booleanas | Executa busca manual | ✅ |
| Busca no Banco de Talentos | — | — | 🔲 API não pública |
| Triagem / Shortlist | Ranqueia e apresenta | Decide quem avança | ✅ |
| Mover candidatos | Move após aprovação | Aprova shortlist | ✅ Testado E2E |
| Reprovação em lote | Reprova com devolutiva | Autoriza execução | ✅ Testado E2E |
| Agendamento | Cria appointment | Confirma horário | ⚠️ Sem calendário |
| Scorecard | — | Preenche e emite parecer | 🔲 Sem API |
| Carta oferta | Cria e envia | Aprova internamente | ⚠️ Validação pendente |
| Negociação | — | Negocia termos | ❌ Irredutivelmente humano |
| Fechamento | Relatório SLA | Confirma reprovação em massa | 🔲 Parcial |

---

## 4. APIs — Status de Implementação

### 4.1 Vagas ✅

| Endpoint | Status |
|---|---|
| `POST /jobs` (criar) | ✅ Funciona |
| `GET /jobs/:id` (detalhe) | ✅ Funciona |
| `PATCH /jobs/:id` (atualizar) | ✅ Funciona |
| `DELETE /jobs/:id` | ✅ Funciona |
| `POST /jobs/paginated/lean` (listar) | ✅ Funciona (substitui GET /jobs que dá 502) |
| `POST /jobs/:id/publicar` | ❌ Não existe na API |
| `POST /jobs/:id/fechar` | ❌ Não existe na API |
| `POST /jobs/:id/duplicar` | ❌ Não existe na API |

### 4.2 Talentos / Job Talents ✅

| Endpoint | Status |
|---|---|
| `GET /job-talents/{jobId}/talents` (listar candidatos) | ✅ Funciona (hunting + orgânicos) |
| `POST /job-talents/{jobId}/talents` (adicionar) | ✅ Funciona |
| `POST /job-talents/{jobId}/talents/batch` (lote) | Disponível, não testado |
| `POST /job-talents/talents/{id}/stages` (mover etapa) | ✅ Documentado, client desatualizado |
| `POST /job-talents/talents/{id}/statuses` (reprovar) | ✅ Documentado, client desatualizado |
| `GET /talents/{id}` (perfil) | ✅ Funciona |
| `POST /talents` (criar no banco) | ✅ Funciona |

### 4.3 Entrevistas / Appointments ⚠️

| Endpoint | Status |
|---|---|
| `POST /job-talents/appointments/{id}/create` | ⚠️ Funciona mas exige calendário no JWT user |
| `GET /job-talents/appointments/my-appointments` | ✅ Funciona |
| Verificar disponibilidade | Disponível, não testado |

### 4.4 Carta Oferta ⚠️

| Endpoint | Status |
|---|---|
| `POST /offer-letters` | ✅ Testado E2E |
| `GET /offer-letters/templates` | ✅ Funciona |
| `POST /offer-letters/{id}/talents/notifications` | Disponível, não testado |

### 4.5 Webhooks ✅

| Endpoint | Status |
|---|---|
| `POST /integrations/webhooks` | ✅ Funciona (obrigatório: `"rules": {}`) |
| 8 eventos registrados | ✅ Funcionando |

### 4.6 APIs que NÃO existem (confirmado)

- InTerview (WhatsApp) — sem API
- Busca full-text no Banco de Talentos — não pública
- Scorecard — 403 no service account
- Agente de Triagem (configurar critérios) — não disponível via API
- Automações (criar/editar) — não disponível via API
- E-mail / comunicação direta — não testado
- Programa de Indicação — não disponível via API
- Templates de descrição — não disponível via API
- Relatórios/métricas — não disponível via API

---

## 5. Arquitetura Atual

```
Slack (DMs + botões) ←→ FastAPI (agente.adianterecursos.com.br)
                              ↕
                    Claude API (Sonnet 4) ← prompt caching + tool use
                              ↕
                    InHire API (api.inhire.app) ← JWT auth auto-refresh
                              ↕
                         Redis ← conversas, users, alerts, learning
```

### Componentes principais

- `claude_client.py` — prompt caching (`cache_control: ephemeral`), 12 tools (`ELI_TOOLS`), `detect_intent()` para roteamento
- `slack.py` — handler principal, tool-based routing (não mais keywords)
- `conversation.py` — máquina de estados (11 FlowStates), resumo automático a cada 20 msgs, compress após 2h
- `proactive_monitor.py` — cron horário, verifica SLA/pipeline/shortlist em paralelo (`asyncio.gather`)

---

## 6. Princípios Inegociáveis do Agente ✅ Todos implementados

- ✅ Nunca aprovar/reprovar candidato sem validação humana (5 pontos de pausa)
- ✅ Nunca inventar dados sobre candidatos
- ✅ Nunca usar jargão técnico com o recrutador
- ✅ Registrar ações no histórico (conversation history + learning service)
- ✅ Em caso de ambiguidade, perguntar antes de agir
