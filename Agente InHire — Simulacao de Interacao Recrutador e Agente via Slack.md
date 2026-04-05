# O Agente no dia a dia

**Simulação completa de interação recrutador ↔ agente via Slack**
**InHire / Byintera — Março 2026**

> **Última atualização:** 4 de abril de 2026 — Sessão 22
> **Status:** Simulação atualizada para refletir o que o Eli realmente faz hoje vs. o que estava na visão original. Marcações de status adicionadas em cada interação.

---

## Como ler este documento

- 🤖 **Eli (agente)** — respostas automáticas via Slack, tom informal e direto
- 👤 **Recrutador** — mensagens e instruções via Slack DM
- ✅ = implementado e funcionando
- ⚠️ = código pronto, bloqueado por dependência externa
- 🔲 = não implementado

---

## Simulação — Vaga: Designer Sênior

### DIA 0 — Briefing recebido ✅

👤 **Recrutador:**
> Precisamos de um Designer Sênior para o time de produto. CLT, faixa 12–16k, início idealmente em maio. Foco em sistemas de design e colaboração com devs. Prioridade alta.

🤖 **Eli** (tool `criar_vaga` acionada automaticamente):
> Bora abrir essa vaga! 🎯
>
> Me conta tudo que você sabe:
> • Cargo e área
> • Modelo (remoto/híbrido/presencial) e local
> • Faixa salarial e regime (CLT/PJ)
> • Requisitos técnicos
> • Urgência
>
> Pode mandar tudo de uma vez. Quando terminar, diz "pronto".

👤 **Recrutador:**
> pronto

🤖 **Eli** (Claude extrai dados + gera JD):
> Analisando o briefing... ⏳
>
> ⚠️ Informações faltando:
> • Local de trabalho (remoto/híbrido/presencial)
> • Requisitos técnicos detalhados
>
> Quer complementar ou digo "gerar" para prosseguir mesmo assim?

👤 **Recrutador:**
> gerar

🤖 **Eli** (posta rascunho com botões):
> **Rascunho: Designer Sênior**
> ```
> # Designer Sênior
> ## Sobre a empresa
> [Placeholder]
> ## Responsabilidades
> - Liderar o desenvolvimento de sistemas de design...
> ...
> ```
> [✅ Aprovar] [✏️ Ajustar] [❌ Rejeitar]

👤 **Recrutador clica em ✅ Aprovar**

🤖 **Eli:**
> ✅ Pronto, vaga criada!
> *Nome:* Designer Sênior
> *ID:* `f9d75e0b-...`
> *Status:* open
> *Pipeline:*
>   1. Listados
>   2. Em abordagem
>   3. Inscritos
>   ...
>
> Vou ficar de olho nos candidatos e te aviso quando tiver gente boa!
>
> 💡 *Dica:* A vaga ainda não tem candidatos. Quer que eu gere uma *string de busca pro LinkedIn*? Diz "busca linkedin".

**Status:** ✅ Fluxo completo funciona E2E. Vaga é criada no InHire via `POST /jobs`.

---

### DIA 0 — Busca LinkedIn ✅

👤 **Recrutador:**
> busca linkedin

🤖 **Eli** (tool `busca_linkedin` acionada):
> Gerando string de busca... ⏳
>
> *Busca principal:*
> `("designer sênior" OR "senior designer") AND ("design system" OR "design tokens") AND ("figma" OR "sketch")`
>
> *Busca alternativa (mais ampla):*
> `("product designer" OR "ux designer") AND ("design system") AND ("CLT")`
>
> *Dicas de hunting:*
> • Empresas referência: Nubank, Stone, Creditas, iFood
> • Grupos: Design Systems Brasil, UX Collective
> • Hashtags: #designsystems #figma #productdesign

**Status:** ✅ Funciona. Claude gera strings booleanas otimizadas.

---

### DIA 2 — Upload de CV ✅

👤 **Recrutador envia PDF no chat:**
> [📎 ana_souza_cv.pdf]

🤖 **Eli:**
> Processando currículo `ana_souza_cv.pdf`... ⏳
>
> ✅ *Candidata cadastrada na vaga Designer Sênior!*
>
> *Nome:* Ana Souza
> *Email:* ana@email.com
> *Cargo:* Product Designer
> *Local:* São Paulo, SP
> *Skills:* Figma, Design Systems, UI/UX, Tokens
> *Resumo:* 5 anos de experiência em design de produto...
>
> *Fit:* 🟢 Alto
> *Justificativa:* Experiência sólida em design systems, Figma avançado, já trabalhou em squads com devs.

**Status:** ✅ Funciona. PDF extraído com PyMuPDF, Claude analisa, `POST /job-talents/{jobId}/talents` cadastra.

---

### DIA 5 — Verificar candidatos ✅

👤 **Recrutador:**
> como estão os candidatos?

🤖 **Eli** (tool `ver_candidatos` acionada):
> Deixa eu ver os candidatos... ⏳
>
> 📊 *Triagem — Designer Sênior*
> Total: 47 candidatos
>
> 🟢 Alto fit: 8
> 🟡 Médio fit: 21
> 🔴 Baixo fit: 12
> ⚪ Sem score: 6
>
> *Top candidatos (Alto fit):*
> • *Ana Souza* — Score: 4.5
> • *Marcos Lima* — Score: 4.2
> • *Carla Freitas* — Score: 4.1
>
> 💡 *Dica:* Já tem *8 candidatos com alto fit*! Que tal montar o shortlist comparativo? Diz "shortlist".

**Status:** ✅ Funciona. `GET /job-talents/{jobId}/talents` retorna screening scores.

---

### DIA 7 — Shortlist ✅

👤 **Recrutador:**
> shortlist

🤖 **Eli** (tool `gerar_shortlist` acionada):
> Montando o comparativo... ⏳
>
> • *Ana Souza* — Score: 4.5 (Alto)
>   Pontos fortes: Design Systems, Figma, 5 anos experiência
>   Pontos de atenção: Pretensão no teto da faixa
>
> • *Marcos Lima* — Score: 4.2 (Alto)
>   Pontos fortes: Liderou DS do zero, sólido tecnicamente
>   Pontos de atenção: Menos experiência em colaboração com devs
>
> • *Carla Freitas* — Score: 4.1 (Alto)
>   Pontos fortes: Portfólio forte, ex-Creditas
>   Pontos de atenção: Pretensão R$ 15.5k (acima da faixa)
>
> *Recomendação de ranking:*
> 1. Ana Souza — melhor fit geral
> 2. Marcos Lima — potencial de crescimento
> 3. Carla Freitas — experiência relevante
>
> **Shortlist — Designer Sênior**
> 3 candidatos selecionados. Ao aprovar, serão movidos para: *Bate-papo com RH*
> [✅ Aprovar] [✏️ Ajustar] [❌ Rejeitar]

**Status:** ✅ Shortlist funciona. ⚠️ Mover candidatos após aprovação bloqueado (endpoint errado no client).

---

### DIA 7 — Mover candidatos ✅

👤 **Recrutador clica ✅ Aprovar no shortlist**

🤖 **Eli** (tool `mover_candidatos` acionada):
> ✅ Movendo candidatos...
>
> Ana Souza, Marcos Lima e Carla Freitas movidos para *Bate-papo com RH* com sucesso!

**Status:** ✅ Eli monta o shortlist, apresenta ranking e botões de aprovação. Após aprovação, move os candidatos em batch via `POST /job-talents/talents/{id}/stages`.

---

### DIA 8 — Agendar entrevista ⚠️ Bloqueado

👤 **Recrutador:**
> agendar entrevista com a Ana

🤖 **Eli** (tool `agendar_entrevista` acionada):
> O agendamento de entrevistas por aqui ainda depende de uma integração de calendário que estamos configurando. Por enquanto, agende direto no InHire. Assim que estiver pronto, te aviso!

**Status:** ⚠️ Código pronto, service account sem calendário integrado.

---

### DIA 10 — Status da vaga ✅

👤 **Recrutador:**
> como tá a vaga?

🤖 **Eli** (tool `status_vaga` acionada):
> 📊 *Relatório — Designer Sênior*
>
> *Status:* 🟢 open
> *Dias aberta:* 10 dias
> *Total candidatos:* 47
>
> *Triagem:*
>   🟢 Alto fit: 8
>   🟡 Médio fit: 21
>   🔴 Baixo fit: 12
>   ⚪ Sem score: 6
>
> *Por etapa:*
>   • Listados: 39
>   • Inscritos: 8
>
> 💡 *Dica:* Tem *8 candidato(s) com alto fit*. Diz "candidatos" pra ver a triagem detalhada.

**Status:** ✅ Funciona. SLA calculado a partir de `createdAt`.

---

### DIA 14 — Carta oferta ⚠️ Bloqueado

👤 **Recrutador:**
> manda uma oferta pra Ana

🤖 **Eli** (tool `carta_oferta` acionada):
> A criação de carta oferta por aqui está sendo validada com o time. Por enquanto, crie a oferta direto no InHire. Te aviso quando liberar!

**Status:** ⚠️ Código pronto, `POST /offer-letters` testado E2E, mas fluxo pendente de validação completa.

---

### DIA 15 — Conversa livre ✅

👤 **Recrutador:**
> o que é screening no InHire?

🤖 **Eli** (tool `conversa_livre` acionada):
> Screening é a triagem automática do InHire. Quando um candidato se inscreve numa vaga, o sistema analisa 3 coisas:
>
> • *CV:* compara a experiência do candidato com os requisitos da vaga
> • *Formulário:* verifica as respostas do formulário de inscrição
> • *Salário:* compara a pretensão com a faixa da vaga
>
> Cada pilar gera um score, e a média vira o fit geral: Alto (≥4.0), Médio (2.0-4.0) ou Baixo (≤2.0).

**Status:** ✅ Claude responde com conhecimento do InHire integrado no system prompt.

---

### DIA 16 — Reprovar candidatos ✅

👤 **Recrutador:**
> reprova os candidatos que não avançaram

🤖 **Eli** (tool `reprovar_candidatos` acionada):
> Identificando candidatos não selecionados... ⏳
>
> Encontrei *38 candidatos* que não avançaram no processo. Vou reprovar todos com uma devolutiva personalizada.
>
> *Prévia da mensagem (gerada pelo Claude):*
> "Agradecemos muito seu interesse e tempo dedicado ao processo. Após análise cuidadosa, seguiremos com outros perfis neste momento. Guardamos seu currículo e podemos entrar em contato em futuras oportunidades."
>
> [✅ Confirmar reprovação em lote] [❌ Cancelar]

👤 **Recrutador clica ✅ Confirmar**

🤖 **Eli:**
> ✅ 38 candidatos reprovados com sucesso!
> Devolutiva registrada como comentário em cada perfil.

**Status:** ✅ Eli identifica os candidatos não selecionados, pede confirmação, então reprova em batch via `POST /job-talents/talents/{id}/statuses` com `reason=other` e devolutiva gerada pelo Claude como comentário.

---

## Resumo — O que funciona hoje no Slack

| Interação | Via Slack | Status |
|---|---|---|
| Fornecer briefing de vaga | Mensagem livre no DM | ✅ |
| Aprovar/ajustar rascunho | Botões Aprovar/Ajustar/Rejeitar | ✅ |
| Upload de CV | Arrastar PDF/DOCX no chat | ✅ |
| Múltiplos CVs de uma vez | Arrastar vários arquivos | ✅ |
| Busca LinkedIn | "busca linkedin" | ✅ |
| Analisar perfil colado | Colar texto no chat | ✅ |
| Ver candidatos/triagem | "candidatos" / "triagem" | ✅ |
| Gerar shortlist | "shortlist" | ✅ |
| Status/SLA da vaga | "como tá a vaga" / "status" | ✅ |
| Listar vagas | "vagas abertas" | ✅ |
| Conversa livre | Qualquer pergunta | ✅ |
| Cancelar conversa | "cancelar" / "reset" | ✅ |
| Toggle comunicação | "ativar/desativar comunicação" | ✅ |
| Mover candidatos | "mover" / "avançar" | ✅ |
| Reprovar candidatos | "reprovar" / "rejeitar" | ✅ |
| Guia InHire (passo a passo) | Qualquer dúvida operacional | ✅ |
| Agendar entrevista | "agendar entrevista" | ⚠️ Retorna "em breve" |
| Carta oferta | "carta oferta" | ⚠️ Retorna "em breve" |

**O recrutador nunca precisa abrir o InHire** para as funcionalidades que estão ✅. Tudo acontece via Slack DM com o Eli.
