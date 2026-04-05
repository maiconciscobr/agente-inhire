# Eli — Roteiro de Testes (Cenário Real)

Simulação do dia a dia de uma recrutadora chamada **Camila**, que trabalha na empresa e usa o Eli pelo Slack pra gerenciar suas vagas no InHire.

Cada cenário simula uma demanda real. Siga na ordem — os cenários dependem uns dos outros.

---

## Dia 1 — Camila conhece o Eli

### Cenário 1: Primeiro contato

Camila acabou de receber acesso ao bot no Slack. Ela não sabe o que ele faz.

**O que mandar:**
> Oi, quem é você?

**O que esperar:**
- Eli pede o email do InHire (onboarding)
- Tom amigável, sem parecer tutorial

**Depois, responda com o email:**
> camila@empresa.com

**O que esperar:**
- Eli confirma o nome, explica o que sabe fazer
- Não manda parede de texto — é conciso

**Validar:**
- [ ] Pediu email de forma natural?
- [ ] Confirmou com o nome correto?
- [ ] A apresentação é curta e útil (não é manual)?

---

### Cenário 2: Demanda real — vaga urgente de Backend

Camila recebeu uma demanda do gestor técnico via email. Ela cola a demanda pro Eli como faria com um colega.

**O que mandar:**
> O Rafael me pediu pra abrir uma vaga de Desenvolvedor Backend Sênior, remoto, pra ontem. A stack é Python, FastAPI, PostgreSQL e AWS. Regime PJ, budget entre 15 e 22 mil. Precisa ter experiência com microsserviços e CI/CD. O time tem 4 devs e ele quer alguém que puxe o técnico. Ah, e se tiver experiência com Kafka é um baita diferencial.

**O que esperar:**
- Eli entende que é uma abertura de vaga
- Pede pra Camila continuar ou dizer "pronto"

**Depois, mande:**
> pronto

**O que esperar:**
- Eli analisa o briefing, identifica info faltante (se houver)
- Gera rascunho de JD com botões Aprovar/Ajustar/Rejeitar
- O título deve ser "Desenvolvedor Backend Sênior" (não inventar outro)

**Validar:**
- [ ] Entendeu o cargo corretamente?
- [ ] Kafka aparece como diferencial (não obrigatório)?
- [ ] Salário faixa 15-22k aparece?
- [ ] Modelo remoto e PJ estão corretos?
- [ ] JD é profissional e atrativa?

---

### Cenário 3: Camila ajusta o rascunho

A JD ficou boa mas Camila quer um ajuste.

**Clique em "Ajustar" e mande:**
> Tira a parte de "Sobre a empresa" e adiciona que o time usa metodologia ágil com sprints de 2 semanas. Também coloca que tem plano de saúde e gympass.

**Depois que ajustar, mande:**
> pronto

**O que esperar:**
- Eli gera novo rascunho incorporando os ajustes
- Mostra botões de aprovação novamente

**Clique em "Aprovar".**

**Validar:**
- [ ] O ajuste foi incorporado na nova versão?
- [ ] Vaga foi criada no InHire após aprovação?
- [ ] Eli mostrou o ID da vaga e o pipeline?
- [ ] Eli disse que vai monitorar candidatos?

---

### Cenário 4: Busca de talentos — Camila vai caçar no LinkedIn

Camila quer começar o hunting. Pede ajuda pro Eli.

**O que mandar:**
> Gera uma string de busca pro LinkedIn pra essa vaga

**O que esperar:**
- String booleana com termos relevantes (Python AND FastAPI AND "backend" etc.)
- Busca alternativa mais ampla
- Dicas de hunting (empresas referência, grupos, hashtags)

**Validar:**
- [ ] Strings são copiáveis e funcionais no LinkedIn?
- [ ] Termos estão alinhados com a vaga (não genéricos)?
- [ ] Dicas fazem sentido pro mercado brasileiro?

---

### Cenário 5: Camila encontrou um perfil e quer opinião

Camila achou alguém no LinkedIn e cola o perfil pro Eli analisar.

**O que mandar:**
> O que acha desse perfil?
>
> Lucas Mendes
> Backend Developer Sênior — 6 anos de experiência
> Atualmente na Nubank como Software Engineer III
> Stack: Python, Django, PostgreSQL, Redis, RabbitMQ, Docker, AWS
> Formação: Eng. Computação — Unicamp
> Localização: Campinas, SP
> Pretensão: 20k PJ
> LinkedIn: lucasmendes

**O que esperar:**
- Análise de fit (Alto/Médio/Baixo) com justificativa
- Pontos fortes (Python, AWS, senioridade, empresa de referência)
- Pontos de atenção (Django em vez de FastAPI, RabbitMQ em vez de Kafka)
- Recomendação clara (avançar ou não)

**Validar:**
- [ ] Eli comparou com a vaga ativa automaticamente?
- [ ] Análise é útil e não genérica?
- [ ] Tom é de colega dando opinião, não de robô classificando?

---

## Dia 3 — Candidatos começaram a chegar

### Cenário 6: Camila quer ver como estão os candidatos

Passaram alguns dias. Camila quer saber o status.

**O que mandar:**
> Como tá a vaga de Backend?

**O que esperar:**
- Relatório com dias aberta, total de candidatos, distribuição de fit
- Contagem por etapa do pipeline

**Validar:**
- [ ] Mostra distribuição Alto/Médio/Baixo fit?
- [ ] Mostra contagem por etapa?
- [ ] Sugere próximos passos?

---

### Cenário 7: Camila pede a triagem detalhada

**O que mandar:**
> Me mostra os candidatos

**O que esperar:**
- Lista de candidatos com score e status de screening
- Top candidatos alto fit destacados
- Oferta de montar shortlist comparativo

**Validar:**
- [ ] Lista nomes reais com scores?
- [ ] Diferencia alto/médio/baixo fit?
- [ ] Oferece montar shortlist sem Camila ter que pedir?

---

### Cenário 8: Shortlist comparativo

**O que mandar:**
> shortlist

**O que esperar:**
- Resumo comparativo lado a lado dos melhores candidatos
- Ranking com justificativa
- Botões Aprovar/Ajustar/Rejeitar
- Indica pra qual etapa serão movidos se aprovados

**Validar:**
- [ ] Comparativo é útil pra tomar decisão (não é lista seca)?
- [ ] Ranking tem justificativa clara?
- [ ] Mostra pra qual etapa vai mover?

---

### Cenário 9: Camila aprova o shortlist

**Clique em "Aprovar".**

**O que esperar:**
- Eli move os candidatos aprovados pra próxima etapa
- Mostra quantos foram movidos com sucesso
- Pergunta se quer reprovar os que ficaram de fora

**Validar:**
- [ ] Confirmou movimentação com contagem?
- [ ] Ofereceu reprovar restantes naturalmente?

---

### Cenário 10: Reprovação com devolutiva

**Clique em "Aprovar" na pergunta de reprovação.**

**O que esperar:**
- Eli reprova em lote
- Gera devolutiva profissional e empática
- Mostra o texto da devolutiva

**Validar:**
- [ ] Reprovação executou sem erro?
- [ ] Devolutiva é humana, não genérica?
- [ ] Mostra quantos foram reprovados?

---

## Dia 5 — Entrevistas e decisão

### Cenário 11: Camila quer agendar entrevista

**O que mandar:**
> Quero agendar entrevista com os aprovados

**O que esperar:**
- Eli lista candidatos disponíveis pra agendar
- Pede número do candidato + data/hora
- (Hoje: deve dar erro 403 ou aviso de limitação — isso é esperado)

**Validar:**
- [ ] Listou candidatos corretamente?
- [ ] Quando falhar, a mensagem é amigável (não técnica)?
- [ ] Sugere alternativa (agendar manualmente no InHire)?

---

### Cenário 12: Camila quer enviar um CV pelo Slack

Camila recebeu um CV por email e quer que o Eli analise.

**Envie um PDF de currículo real pro bot.**

**O que esperar:**
- Eli extrai dados (nome, cargo, skills, resumo)
- Faz análise de fit com a vaga ativa
- Cadastra no InHire (ou avisa se não conseguir)

**Validar:**
- [ ] Extraiu dados corretamente do PDF?
- [ ] Fez análise de fit automaticamente?
- [ ] Mostra resumo útil (não um JSON cru)?

---

## Dia 10 — Nova demanda + contexto de conversa

### Cenário 13: Camila manda outra demanda sem contexto

Camila quer abrir outra vaga, sem mencionar que já tem uma ativa.

**O que mandar:**
> Preciso de um Product Manager, pode ser pleno ou sênior. Híbrido em São Paulo, CLT, faixa de 18 a 25 mil. Experiência com produtos B2B SaaS, métricas, discovery. Precisa falar inglês fluente.

**Depois:**
> pronto

**O que esperar:**
- Eli entende que é uma NOVA vaga (não confunde com a de Backend)
- Gera JD separada
- Aprovar e criar no InHire

**Validar:**
- [ ] Não confundiu com a vaga anterior?
- [ ] Título correto ("Product Manager")?
- [ ] Inglês fluente aparece nos requisitos?

---

### Cenário 14: Camila pergunta sobre as duas vagas

**O que mandar:**
> Como tão minhas vagas?

**O que esperar:**
- Eli lista as vagas abertas com status resumido
- Se ambíguo, pergunta de qual vaga quer detalhes

**Validar:**
- [ ] Mostra as duas vagas?
- [ ] Eli sabe diferenciar entre elas?

---

### Cenário 15: Carta oferta

Camila quer fazer uma oferta pra um candidato da vaga de Backend.

**O que mandar:**
> Quero mandar uma carta oferta pro candidato da vaga de Backend

**O que esperar:**
- Eli identifica a vaga e lista candidatos elegíveis
- Pede informações (qual candidato, salário, aprovador)

**Responda com algo como:**
> O primeiro da lista, salário 19 mil, aprovador rafael@empresa.com

**O que esperar:**
- Eli mostra resumo da oferta com botões de aprovação
- Dados corretos (candidato, salário, aprovador)

**Clique em "Aprovar".**

**Validar:**
- [ ] Identificou a vaga correta?
- [ ] Resumo da oferta está correto?
- [ ] Criou no InHire (ou erro amigável se não habilitado)?

---

### Cenário 16: Camila cancela uma ação no meio

**Inicie qualquer fluxo e mande:**
> cancelar

**O que esperar:**
- Eli reseta a conversa sem drama
- Mensagem curta e direta

**Validar:**
- [ ] Resetou sem erro?
- [ ] Não ficou preso em estado anterior?

---

### Cenário 17: Conversa livre — Camila pergunta algo genérico

**O que mandar:**
> Qual a melhor forma de avaliar fit cultural numa entrevista?

**O que esperar:**
- Eli responde como assistente de recrutamento, com dicas úteis
- Tom de colega, não de Wikipedia

**Validar:**
- [ ] Resposta é útil e contextualizada?
- [ ] Não saiu do personagem?

---

### Cenário 18: Toggle de comunicação

**O que mandar:**
> desativar comunicação com candidatos

**Depois:**
> ativar comunicação com candidatos

**Validar:**
- [ ] Confirmou desativação e reativação?

---

## Testes de Memória e Contexto

### Cenário 19: Eli lembra o que aconteceu antes?

Depois de todos os cenários anteriores, teste se o Eli mantém contexto.

**O que mandar:**
> Qual foi o último candidato que eu aprovei?

**O que esperar:**
- Eli consegue responder com base no histórico da conversa
- Se não souber exatamente, diz que não tem certeza em vez de inventar

**Validar:**
- [ ] Tentou responder com base no contexto?
- [ ] Não inventou informação?

---

### Cenário 20: Eli mantém contexto após mensagem proativa?

Este teste depende do cron de monitoramento rodar (1h).

**Pré-requisito:** Ter vagas abertas há pelo menos 3 dias.

**O que esperar quando o cron rodar:**
- Eli manda alerta proativo (pipeline parado, SLA, shortlist pronto)
- Se Camila responder ao alerta, Eli sabe do que ela está falando

**Validar:**
- [ ] Mensagem proativa chegou?
- [ ] Se Camila responder, Eli entende o contexto?

---

## Checklist de Tom e Persona (validar ao longo de todos os cenários)

| Critério | OK? |
|---|---|
| Eli fala como amigo, não como robô | |
| Usa formatação Slack (*bold*, listas •) | |
| Emojis com moderação (1-2 por msg, não em toda msg) | |
| Nunca usa jargão técnico (endpoint, webhook, JWT) | |
| Mensagens de erro são amigáveis | |
| Nunca inventa dados sobre candidatos | |
| Sempre usa nome da vaga (não ID solto) | |
| Tom se adapta (urgência = resposta curta) | |

---

## Resumo dos cenários

| # | Cenário | Resultado | Notas |
|---|---|---|---|
| 1 | Primeiro contato + onboarding | | |
| 2 | Abrir vaga urgente de Backend | | |
| 3 | Ajustar rascunho de JD | | |
| 4 | Busca LinkedIn | | |
| 5 | Análise de perfil colado | | |
| 6 | Status da vaga | | |
| 7 | Triagem detalhada | | |
| 8 | Shortlist comparativo | | |
| 9 | Aprovar shortlist (mover) | | |
| 10 | Reprovar em lote | | |
| 11 | Agendar entrevista | | |
| 12 | Envio de CV (PDF) | | |
| 13 | Abrir segunda vaga (PM) | | |
| 14 | Status de múltiplas vagas | | |
| 15 | Carta oferta | | |
| 16 | Cancelar no meio do fluxo | | |
| 17 | Conversa livre | | |
| 18 | Toggle comunicação | | |
| 19 | Teste de memória/contexto | | |
| 20 | Contexto pós-mensagem proativa | | |

---

## Limitações conhecidas (não são bugs)

| Funcionalidade | Status | Motivo |
|---|---|---|
| Agendar entrevista | Bloqueado | Service account sem calendário integrado. Endpoint retorna 403. |
| Webhooks InHire | Bloqueado | Registro via API retorna 500 no tenant demo. Registrar pelo painel. |
| Screening scores reais | Depende | Só funciona com candidatos orgânicos (inscrição via formulário). Hunting manual não gera score. |
| Enviar email de reprovação real | Não testado | Endpoint de automação existe mas não foi validado E2E. |
| Carta oferta | Depende do tenant | Pode retornar 403 se não estiver habilitado. |
