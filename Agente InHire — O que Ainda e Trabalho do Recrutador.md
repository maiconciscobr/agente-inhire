# O que ainda é trabalho do recrutador

**Tudo o que o agente de IA não pode — e não deve — fazer sozinho**
**InHire / Byintera — Março 2026**

> **Última atualização:** 4 de abril de 2026 (Sessão 7)
> **Status:** 15/15 testes PASS. Quando o Eli não consegue fazer algo, guia o recrutador com passo a passo no InHire.

---

## Premissa

O agente assume tudo que é operacional, repetitivo ou que pode ser decidido por regras. O recrutador foca apenas no que exige julgamento, responsabilidade ou relação humana.

---

## As 18 tarefas que pertencem ao recrutador

### Abertura da Vaga

| # | O que o recrutador faz | Por que o agente não pode | Status do agente |
|---|---|---|---|
| 1 | Fornecer o briefing da vaga | Precisa de um ponto de partida humano | ✅ Agente extrai dados do briefing automaticamente |
| 2 | Definir o salário máximo | Decisão financeira e estratégica | ✅ Agente usa o valor informado, nunca inventa |
| 3 | Validar e aprovar a vaga antes de publicar | Afeta employer branding e qualidade do funil | ✅ Ponto de pausa implementado (botões Aprovar/Ajustar/Rejeitar) |
| 4 | Aprovar ou reprovar uma requisição | Responsabilidade dos aprovadores designados | 🔲 Agente não interage com requisições |
| 5 | Designar gestor técnico e avaliadores | Escolha política e organizacional | 🔲 Agente não gerencia participantes |

### Atração de Candidatos

| # | O que o recrutador faz | Por que o agente não pode | Status do agente |
|---|---|---|---|
| 6 | Decidir quais perfis abordar ativamente | Hunting é personalizado e sensível | ✅ Agente gera strings de busca LinkedIn, recrutador executa |
| 7 | Revisar mensagens de abordagem antes de enviar | Representa employer branding | 🔲 Agente não envia e-mails de hunting (sem API de comunicação) |

### Triagem

| # | O que o recrutador faz | Por que o agente não pode | Status do agente |
|---|---|---|---|
| 8 | Validar critérios de triagem antes de ativar | Critérios errados contaminam o funil | 🔲 Configuração de triagem não disponível via API |
| 9 | Aprovar o shortlist — decidir quem avança | Decisão sempre humana | ✅ Ponto de pausa implementado (botões no shortlist) |
| 10 | Autorizar reanálise quando critérios mudam | Consome créditos limitados | 🔲 Reanálise não disponível via API |

### Entrevistas

| # | O que o recrutador faz | Por que o agente não pode | Status do agente |
|---|---|---|---|
| 11 | Preencher o scorecard de entrevista | Avaliação qualitativa 100% humana | 🔲 Scorecard não acessível via API (403) |
| 12 | Emitir parecer final do candidato | Responsabilidade do entrevistador | 🔲 Idem |
| 13 | Decidir quem avança após entrevistas | Requer julgamento pós-avaliação | ✅ Agente move após aprovação (batch) |

### Oferta

| # | O que o recrutador faz | Por que o agente não pode | Status do agente |
|---|---|---|---|
| 14 | Aprovar internamente a carta oferta | Decisão de negócio | ⚠️ Código pronto, fluxo pendente de validação |
| 15 | Negociar os termos com o candidato | Exige leitura emocional e autoridade | ❌ Irredutivelmente humano |
| 16 | Validar novos termos após recusa | Precisa de aprovação interna | ⚠️ Idem #14 |

### Fechamento

| # | O que o recrutador faz | Por que o agente não pode | Status do agente |
|---|---|---|---|
| 17 | Confirmar reprovação em massa | Irreversível — requer confirmação explícita | ✅ Ponto de pausa implementado (botões) |
| 18 | Revisar devolutivas para finalistas | Afeta employer branding a longo prazo | ✅ Agente gera rascunho com Claude, recrutador aprova |

---

## Resumo por critério

| Critério | Descrição | Tarefas | Implementação do agente |
|---|---|---|---|
| Julgamento qualitativo | Leitura de contexto e nuance | #11, 12, 13 | Scorecard sem API. Mover candidatos com endpoint errado. |
| Decisão financeira/política | Compromissos formais da empresa | #2, 4, 14, 15, 16 | Salário extraído do briefing. Oferta pendente validação. |
| Relação e reputação | Percepção do candidato sobre a empresa | #6, 7, 18 | Busca LinkedIn ✅. E-mail hunting sem API. Devolutiva com Claude ✅. |
| Validação antes de ação irreversível | Execuções em massa, publicação | #3, 8, 9, 10, 17 | 3 dos 5 pontos de pausa implementados com botões Slack. |
| Ponto de origem | Alguém precisa dizer que a vaga existe | #1, 5 | Briefing via Slack ✅. Designação de avaliadores 🔲. |

---

## Princípio central

> O agente nunca age no escuro. Toda decisão humana é um ponto de pausa explícito — o agente para, reporta o que preparou e aguarda confirmação antes de seguir.

**Pontos de pausa implementados (5):**
1. ✅ Publicar vaga (botão Aprovar no rascunho)
2. ✅ Mover candidatos de etapa (botão Aprovar no shortlist) — ⚠️ execução bloqueada
3. ✅ Reprovar candidatos (botão Aprovar na reprovação) — ⚠️ execução bloqueada
4. ⚠️ Enviar carta oferta — código pronto, validação pendente
5. 🔲 Comunicar candidatos externamente — sem API de comunicação
