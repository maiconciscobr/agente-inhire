# Eli (Agente InHire) — Gaps pendentes para o André

> **Contexto:** O Eli é um agente de IA que automatiza recrutamento via Slack, conectando a API do InHire + Claude + Redis. O recrutador conversa pelo Slack e o Eli executa: cria vaga, analisa candidatos, monta shortlist, move pipeline, reprova em lote. Hoje funciona ponta a ponta da abertura da vaga até a seleção final. Faltam 4 gaps para cobrir até a contratação.
>
> **Pedido:** Cole este documento inteiro no Claude e peça para ele analisar cada gap, sugerir o que precisa ser feito do lado da API InHire, e devolver um .md estruturado com a solução de cada um.

---

## Gap 1 — Agendamento de entrevistas (BLOQUEADO)

### O que o Eli já faz
- Detecta quando o recrutador pede "agendar entrevista"
- Lista candidatos ativos da vaga
- Extrai candidato + data/hora da mensagem em linguagem natural
- Chama `POST /job-talents/appointments/{jobTalentId}/create`

### O que acontece hoje
Retorna **403 Forbidden**. A service account usada pelo Eli não tem calendário integrado (Google/Outlook).

### Endpoint que o Eli usa
```
POST /job-talents/appointments/{jobTalentId}/create
```

### Payload que o Eli envia
```json
{
  "datetime": "2026-04-10T14:00:00",
  "type": "interview",
  "provider": "google"
}
```

### O que preciso saber do André
1. Qual é o payload correto e completo desse endpoint? (campos obrigatórios: `name`, `startDateTime`, `endDateTime`, `guests`, `hasCallLink`, `userEmail` — quais são realmente required?)
2. A service account precisa ter um calendário Google/Outlook vinculado para esse endpoint funcionar? Se sim, como vincular?
3. É possível criar o appointment sem integração de calendário (só registrar no InHire, sem enviar convite externo)?
4. Existe alguma permissão ou role específica que a service account precisa para usar esse endpoint?
5. O `provider` aceita quais valores? (`google`, `outlook`, `teams`, `zoom`?)

---

## Gap 2 — Carta oferta (BLOQUEADO)

### O que o Eli já faz
- Detecta quando o recrutador pede "carta oferta"
- Lista candidatos elegíveis
- Extrai candidato + salário + aprovador da mensagem
- Monta payload com template + variáveis
- Chama `POST /offer-letters`

### O que acontece hoje
Retorna **403 Forbidden** no tenant `demo`.

### Endpoint que o Eli usa
```
POST /offer-letters
```

### Payload que o Eli envia
```json
{
  "name": "Oferta - João Silva - Dev Backend Senior",
  "jobTalentId": "{jobId}*{talentId}",
  "talent": {
    "id": "talent-uuid",
    "email": "joao@email.com"
  },
  "approvals": [
    {
      "email": "gestor@empresa.com",
      "name": "Nome do Aprovador"
    }
  ],
  "language": "pt-BR",
  "templateId": "template-uuid",
  "templateVariableValues": {
    "salario": "18000",
    "nomeCargo": "Dev Backend Senior",
    "nomeCandidato": "João Silva",
    "dataInicio": ""
  }
}
```

### Outros endpoints relacionados que o Eli usa
- `GET /offer-letters/templates` — listar templates disponíveis
- `GET /offer-letters/settings` — verificar configurações
- `GET /offer-letters/{id}` — consultar status
- `PATCH /offer-letters/{id}/cancel` — cancelar
- `POST /offer-letters/{id}/send-to-talent` — enviar ao candidato

### O que preciso saber do André
1. O tenant `demo` tem carta oferta habilitada? Se não, como habilitar?
2. O payload acima está correto? Quais campos são obrigatórios vs opcionais?
3. A service account precisa de alguma permissão adicional?
4. O formato do `jobTalentId` é mesmo `{jobId}*{talentId}` ou mudou?
5. Os templates precisam ser criados antes no InHire UI, ou podem ser criados via API?
6. O fluxo é: criar oferta → aprovador aprova → enviar ao candidato? Ou tem etapa adicional?

---

## Gap 3 — Busca full-text no Banco de Talentos (SEM API)

### O que o Eli gostaria de fazer
- Recrutador diz "procura no banco de talentos alguém com experiência em Python"
- Eli busca no banco de talentos do InHire por skills, cargo, localização
- Retorna candidatos que já passaram por processos anteriores

### O que existe hoje
- `GET /talents` existe mas não tem parâmetro de busca full-text
- `GET /talents?search=python` — não funciona ou retorna vazio
- Não há endpoint de busca avançada (por skill, cargo, experiência)

### O que preciso saber do André
1. Existe algum endpoint de busca no banco de talentos que não está documentado?
2. `GET /talents` aceita quais query params? (`search`, `skills`, `location`, `name`?)
3. Se não existe busca via API, está no roadmap? Qual a previsão?
4. Existe algum workaround? (ex: listar talentos paginados e filtrar client-side?)

---

## Gap 4 — Comunicação com candidato via WhatsApp / InTerview (SEM API)

### O que o Eli gostaria de fazer
- Enviar mensagens ao candidato diretamente (devolutiva, convite para entrevista, follow-up)
- Usar o InTerview (módulo WhatsApp do InHire) para comunicação automatizada

### O que existe hoje
- Nenhuma API pública para o InTerview
- Comunicação com candidato só é possível via interface do InHire

### O que preciso saber do André
1. O InTerview tem API interna? Está nos planos abrir?
2. Existe alguma alternativa via API? (ex: enviar email ao candidato via endpoint do InHire?)
3. O webhook de evento pode ser usado para triggerar comunicação? (ex: quando candidato é movido, InHire envia mensagem automaticamente?)

---

## Contexto técnico (para referência do Claude do André)

### Stack do Eli
- **Backend:** FastAPI + Python 3.12 + Redis
- **IA:** Anthropic Claude API (claude-sonnet-4) com tool calling
- **Comunicação:** Slack Events API (recebe) + Slack Web API (envia)
- **ATS:** InHire REST API (`https://api.inhire.app`, tenant `demo`)
- **Auth:** JWT via `POST https://auth.inhire.app/login` (service account)

### Endpoints que já funcionam (confirmados)
| Ação | Endpoint | Status |
|---|---|---|
| Listar vagas | `POST /jobs/paginated/lean` | OK |
| Criar vaga | `POST /jobs` | OK |
| Listar candidatos | `GET /job-talents/{jobId}/talents` | OK |
| Adicionar talento | `POST /job-talents/{jobId}/talents` | OK |
| Mover de etapa | `POST /job-talents/talents/{id}/stages` | OK |
| Mover em lote | `POST /job-talents/talents/stages/batch` | OK |
| Reprovar | `POST /job-talents/talents/{id}/statuses` | OK |
| Reprovar em lote | `POST /job-talents/talents/statuses/batch` | OK |
| Registrar webhook | `POST /integrations/webhooks` | OK |
| Criar registro CV | `POST /files` | OK |

### Endpoints que retornam 403/erro
| Ação | Endpoint | Erro |
|---|---|---|
| Agendar entrevista | `POST /job-talents/appointments/{id}/create` | 403 |
| Criar carta oferta | `POST /offer-letters` | 403 |
| Listar templates oferta | `GET /offer-letters/templates` | 403 |
| Listar usuários | `GET /users` | 403 |
| Listar time | `GET /team` | 403 |
| Listar scorecards | `GET /scorecards` | 403 |

### Bugs conhecidos da API (para contexto)
- `GET /jobs` faz full table scan → 502 timeout (usar `POST /jobs/paginated/lean`)
- `GET /applications` retorna vazio para candidatos de hunting (usar `GET /job-talents/{jobId}/talents`)
- Webhook payload não tem campo de tipo de evento (detectamos pela presença de campos)
- `userName` no webhook é quem cadastrou, não o candidato
- `GET /integrations/webhooks` retorna `[]` mesmo com webhooks registrados
- Screening/triagem IA só funciona para candidatos orgânicos (inscrição via formulário)

---

**Objetivo final:** com esses 4 gaps resolvidos, o Eli cobre o ciclo completo de recrutamento — da abertura da vaga até a contratação — sem o recrutador sair do Slack.
