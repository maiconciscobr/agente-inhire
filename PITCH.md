# Eli — O recrutador que nunca dorme

> Agente de IA que opera o recrutamento de ponta a ponta dentro do InHire, via Slack.
> O recrutador só toma decisões. O Eli faz todo o resto.
> Quando não consegue fazer algo, guia o recrutador com passo a passo no InHire.

**Status:** 12 funcionalidades E2E. 15/15 testes automatizados. 13 tools de IA. Proatividade inteligente (briefing diário, horário comercial, escalonamento de alertas). Arquitetura modular (~1000 linhas no orquestrador).

---

## Para Stakeholders

### O problema

Recrutadores gastam 70% do tempo em tarefas operacionais: montar descrição de vaga, organizar candidatos, enviar devolutivas, cobrar scorecards, monitorar SLA. Sobra pouco tempo para o que realmente importa: hunting, entrevistas e decisões.

### A solução

O Eli assume toda a operação. O recrutador trabalha pelo Slack — nunca precisa abrir o InHire. O agente:

- **Recebe um briefing** e monta a vaga completa (descrição, requisitos, faixa salarial)
- **Monitora candidatos** 24/7 e avisa quando tem gente boa
- **Monta shortlists** comparativos ranqueando os melhores
- **Move candidatos** entre etapas do pipeline após aprovação
- **Reprova em lote** com devolutiva gerada por IA
- **Processa currículos** — recrutador manda PDF no chat, Eli extrai dados, cadastra e anexa o CV
- **Gera strings de hunting** otimizadas para LinkedIn
- **Acompanha SLA** e alerta quando o prazo aperta
- **Envia briefing diário** às 9h com resumo de todas as vagas ativas
- **Respeita horário comercial** — mensagens proativas só 8h-19h, seg-sex
- **Escala alertas com inteligência** — 3 dias (gentil) → 7 dias (lembrete) → 14 dias (atenção)
- **Comemora contratações** — detecta quando candidato é contratado e celebra com o recrutador
- **Cobra follow-up** — avisa quando candidato está parado em entrevista há 3+ dias
- **Guia o recrutador** quando precisa fazer algo direto no InHire (com link)
- **Nunca age sozinho** em decisões críticas — sempre pede aprovação

### Números

| Métrica | Sem Eli | Com Eli |
|---|---|---|
| Tempo para montar JD | 30-60 min | 2 min (briefing → aprovação) |
| Tempo para processar 10 CVs | 1-2 horas | Automático (manda no chat) |
| Tempo para montar shortlist | 1-2 horas | 30 segundos |
| Monitoramento de SLA | Manual, esquece | Automático, 24/7 |
| String de busca LinkedIn | 15-20 min | Instantâneo |
| Mover 5 candidatos de etapa | 5-10 min (manual) | 1 clique (botão aprovar) |

### 5 pontos de pausa (o Eli nunca ultrapassa)

1. Publicar vaga — sempre mostra rascunho antes
2. Mover candidatos de etapa — sempre pede aprovação
3. Reprovar candidatos — sempre confirma antes
4. Enviar carta oferta — sempre mostra para revisão
5. Comunicar candidatos — nunca envia sem OK

### Roadmap

| Fase | Status |
|---|---|
| Abertura de vaga via Slack | ✅ Pronto |
| Triagem e shortlist automático | ✅ Pronto |
| Upload de CV com análise de fit | ✅ Pronto (CV anexado no InHire) |
| Mover candidatos entre etapas | ✅ Pronto (individual + batch) |
| Reprovar em lote com devolutiva | ✅ Pronto |
| Monitoramento proativo (SLA, pipeline) | ✅ Pronto |
| Guia InHire (passo a passo com links) | ✅ Pronto |
| Briefing diário (resumo matinal às 9h) | ✅ Pronto |
| Horário comercial + escalonamento alertas | ✅ Pronto |
| Comemoração de contratação | ✅ Pronto |
| Follow-up pós-entrevista | ✅ Pronto |
| Configurações por recrutador | ✅ Pronto |
| Agendamento de entrevistas | 🔲 Depende de API InHire |
| Carta oferta completa | 🔲 Depende de API InHire |
| Divulgação automática em portais | 🔲 Depende de API InHire |
| Configurar triagem IA por API | 🔲 Depende de API InHire |

---

## Para Recrutadores

### Como funciona

Você manda mensagem pro Eli no Slack. Ele entende o que você quer e faz.

### O que você pode pedir

| Você diz | O Eli faz |
|---|---|
| "preciso abrir uma vaga de dev python sênior, remoto, 15-20k CLT" | Monta a vaga completa, mostra pra você aprovar, cria no InHire |
| "como estão os candidatos?" | Mostra triagem: quantos, quem tem alto fit, scores |
| "shortlist" | Monta comparativo ranqueado dos melhores |
| "mover candidatos pra próxima etapa" | Monta shortlist, pede aprovação, move em lote |
| "reprovar os que não passaram" | Identifica candidatos, pede confirmação, reprova com devolutiva |
| "busca linkedin" | Gera string de busca booleana pronta pra colar |
| *[manda um PDF no chat]* | Extrai dados do CV, cadastra na vaga com CV anexado, analisa fit |
| *[cola um perfil do LinkedIn]* | Analisa fit com a vaga e recomenda avançar ou não |
| "como tá a vaga?" | Relatório: SLA, candidatos por etapa, distribuição de fit |
| "vagas abertas" | Lista todas as suas vagas com status |
| "como configuro a triagem?" | Guia passo a passo de como fazer no InHire, com link |
| *(todo dia de manhã)* | Envia resumo: candidatos novos, alto fit, SLA, pipeline parado |
| *(candidato contratado)* | Comemora e pergunta se quer fechar a vaga |
| *(candidato em entrevista há 3+ dias)* | Lembra de dar retorno |

### O que o Eli ainda não faz (mas te guia)

Quando você pede algo que o Eli ainda não consegue fazer automaticamente, ele te explica como fazer direto no InHire com link do passo a passo:

- Publicar vaga nos portais (LinkedIn, Indeed)
- Configurar formulário de inscrição
- Configurar critérios de triagem IA
- Agendar entrevistas
- Enviar carta oferta
- Configurar scorecard

### O que o Eli **nunca** vai fazer

- Aprovar candidatos sozinho
- Enviar mensagens para candidatos sem seu OK
- Negociar oferta
- Preencher scorecard (isso é julgamento seu)
- Fazer hunting ativo no LinkedIn (mas te dá as ferramentas)

### Tom do Eli

O Eli fala como um colega de trabalho, não como um sistema. Direto, informal, sem enrolação.

| Situação | O que ele diz |
|---|---|
| Vaga criada | "Pronto, vaga criada! Vou ficar de olho nos candidatos." |
| Pós-criação | "Pra completar, configure no InHire: divulgação, formulário, triagem. Diz qual que eu te explico!" |
| Candidato bom aparece | "Apareceu um candidato muito bom — score 4.8! Quer ver?" |
| SLA apertando | "Ei, prazo da vaga em 3 dias. Precisa de ajuda pra acelerar?" |
| Não consegue fazer | "Ainda não consigo agendar entrevistas por aqui. Como fazer no InHire: [passo a passo + link]" |
| Briefing matinal | "Bom dia! ☀️ Resumo: Backend Sênior — 3 novos, 2 alto fit. Product Manager — sem movimento há 4 dias." |
| Contratação | "🎉 Contratação! Maria Santos fechou na vaga de Backend! Quer que eu feche a vaga?" |
| Follow-up entrevista | "João Silva fez entrevista há 3 dias. Já tem retorno? Posso mover ou precisa de mais tempo?" |
| Pipeline parado 14d | "Faz 14 dias que essa vaga tem candidatos parados. Tá tudo bem? Posso te dar um resumo." |
| Erro | "Ops, deu um problema aqui. Vou tentar resolver." |

---

## Para Devs

### Arquitetura em 30 segundos

```
Slack ←→ FastAPI ←→ Claude API (13 tools + prompt caching)
                ←→ InHire API (JWT auto-refresh)
                ←→ Redis (estado, resumos, alertas, filas, locks)
```

- **Roteamento por tool use**: Claude recebe a mensagem + 13 tools definidas, decide qual chamar. Sem keywords.
- **Prompt caching**: system prompt estático cacheado por 5 min (cache_control: ephemeral).
- **Resumo de conversa**: a cada 20 mensagens, Claude resume em 5 linhas. Após 2h, injeta resumo comprimido.
- **Monitor paralelo**: asyncio.gather() checa todos os recrutadores simultaneamente.
- **Guia InHire**: tool `guia_inhire` mostra passo a passo com link quando o agente não consegue fazer algo.
- **Briefing diário**: cron às 9h BRT, só envia se há novidades, Redis controla idempotência.
- **Horário comercial**: mensagens proativas só 8h-19h BRT seg-sex, fila Redis fora do horário.
- **Escalonamento de alertas**: 3d (info) → 7d (warning) → 14d (critical), TTLs progressivos.
- **Lock de concorrência**: Redis SET NX por conversa, evita corrupção de estado.
- **Dedup atômico**: Redis SET NX EX 300, sobrevive restart, fallback em memória.
- **Config por recrutador**: 8 campos customizáveis (horário, limite msgs, thresholds).
- **Arquitetura modular**: slack.py (~1000 linhas) + 5 módulos de handlers extraídos.

### Estado da API InHire

| Funcionalidade | Endpoint | Status |
|---|---|---|
| Listar vagas | `POST /jobs/paginated/lean` | ✅ |
| Criar vaga | `POST /jobs` | ✅ |
| Listar candidatos | `GET /job-talents/{jobId}/talents` | ✅ |
| Adicionar talento (com CV) | `POST /job-talents/{jobId}/talents` + `POST /files` | ✅ |
| Mover de etapa | `POST /job-talents/talents/{id}/stages` | ✅ Testado E2E |
| Mover batch | `POST /job-talents/talents/stages/batch` | ✅ Testado E2E |
| Reprovar | `POST /job-talents/talents/{id}/statuses` (reason=enum) | ✅ Testado E2E |
| Reprovar batch | `POST /job-talents/talents/statuses/batch` | ✅ Testado E2E |
| Agendar entrevista | `POST /job-talents/appointments/{id}/create` | ⚠️ SA sem calendário |
| Carta oferta | `POST /offer-letters` | ⚠️ Pendente validação |
| Webhooks | `POST /integrations/webhooks` | ✅ 8 eventos |

### O que falta na API InHire (doc completo: `API_GAPS_PARA_DEVS.md`)

| Prioridade | Qtd | O que falta |
|---|---|---|
| Crítica | 4 | Upload CV ao S3, agendar em nome de user, divulgação, formulário |
| Alta | 3 | Triagem IA config, emails, customizar pipeline |
| Média | 4 | Scorecard, busca talentos, automações, relatórios |

### Como rodar

```bash
# No servidor (65.109.160.97)
systemctl restart agente-inhire
journalctl -u agente-inhire -f

# Health check
curl https://agente.adianterecursos.com.br/health

# Testes inteligentes (Claude como juiz)
cd /var/www/agente-inhire && ANTHROPIC_API_KEY=sk-... python3 test_agent.py
```

### Docs técnicos

- `CLAUDE.md` — referência completa (lido automaticamente pelo Claude)
- `API_GAPS_PARA_DEVS.md` — 11 gaps priorizados para o time InHire
- `MAPEAMENTO_API_INHIRE.md` — todos os endpoints testados com exemplos
- `DIARIO_DO_PROJETO.md` — 26 sessões de desenvolvimento documentadas
- `AGENT_BEHAVIOR_GUIDE.md` — regras de persona e proatividade

---

> **Última atualização:** 5 de abril de 2026 — Sessão 26
