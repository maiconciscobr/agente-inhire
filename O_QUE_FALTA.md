# O que falta para o agente cobrir o recrutamento de ponta a ponta

> **Papel deste arquivo:** fonte viva do estado atual dos gaps. Quando um gap fechar, atualize aqui. Histórico de como cada sessão progrediu fica em [DIARIO_DO_PROJETO.md](DIARIO_DO_PROJETO.md).

Este documento mostra o que ainda impede o agente de recrutamento automatizado de fazer sozinho o trabalho inteiro, da vaga aberta ao candidato contratado. Hoje ele cobre cerca de metade das tarefas. A outra metade ou depende de ajustes no sistema do InHire, ou ainda precisa ser construída por nós.

## Onde estamos hoje

O agente já cobre 51% do ciclo de recrutamento. Ele abre vaga por conversa, gera descrição, configura triagem por IA, divulga em portais (LinkedIn, Indeed, Netvagas), lê e pontua currículos, monta shortlist, busca em 86 mil talentos do banco, move candidatos em lote, reprova com devolutiva personalizada por pessoa, agenda entrevistas com lembrete, envia carta oferta com aprovação, comunica por email e WhatsApp, comemora contratação e gera relatórios semanais de todas as vagas. Da abertura à contratação, eis o que ainda precisa do recrutador abrir o InHire pra fazer.

## O que falta, por fase do funil

### Abertura de vaga

- **Campos personalizados na vaga** (ex.: "tipo de cliente que vai atender", "turno"). Hoje o recrutador preenche isso no InHire. O agente não preenche porque o sistema não tem rota pública para isso. Precisa ser construído no InHire.
- **Pipeline customizado por vaga** (etapas diferentes por cargo). O sistema do InHire já permite, mas o agente ainda não foi programado para usar. Trabalho nosso (agente).

### Atração e divulgação

- **Programa de indicação** (links gamificados para colaboradores indicarem). A rota existe no InHire, mas o agente ainda não foi programado para disparar. Trabalho nosso (agente).
- **Smart CV** (currículo padronizado, editável, que oculta dados para reduzir viés). Hoje o recrutador monta manualmente no InHire. Isso é uma tela visual do InHire, sem rota programática. Precisa ser construído no InHire.

### Triagem e seleção

- **Classificar talento (Gostei / Amei / Não gostei)**. O recrutador marca isso no InHire. A rota existe e é simples, mas o agente ainda não usa. Trabalho nosso (agente).
- **Persistir as notas que o Claude escreve sobre cada candidato**. Hoje a análise do agente some quando fecha o chat. Precisa de um campo de anotação do InHire. Precisa ser construído no InHire.
- **Anexar e baixar currículo em PDF**. Hoje retorna erro de permissão. Precisa de ajuste na conta do agente dentro do InHire. Pendente com o dev do InHire.

### Entrevista

- **Feedback do entrevistador (scorecard antigo)**. Hoje a rota antiga retorna erro de permissão. A rota nova funciona e o agente já usa. A antiga precisa ser liberada pelo time do InHire (combinado com o André, ainda não feito). Pendente com o dev do InHire.
- **Kit de Entrevista completo com parecer gerado por IA**. Funcionalidade que o InHire está desenvolvendo internamente; quando sair, precisa ter uma rota pública para o agente ler e preencher. Precisa ser construído no InHire.
- **Integração com Google Meet e Outlook para agendamento**. Hoje o agente agenda só modo manual (sem link automático de reunião). A conta do agente precisa de calendário próprio, ou o InHire precisa permitir o agente agendar em nome do recrutador. Pendente com o dev do InHire.
- **Enviar teste DISC, Big Five, fit cultural e testes técnicos**. Esses testes são do módulo Mindsight do InHire. Hoje não há rota pública para disparar. Precisa ser construído no InHire.
- **Webhook de entrevista concluída e marcação de "não compareceu"**. Hoje o agente não sabe automaticamente se a entrevista aconteceu. Precisa de um evento novo do InHire para avisar. Precisa ser construído no InHire.

### Oferta

- **Aviso automático quando o candidato abre, assina ou recusa a carta oferta**. Hoje o agente precisa perguntar o status. Precisa de eventos novos do InHire (webhook é um aviso que o sistema dispara sozinho quando algo acontece). Precisa ser construído no InHire.
- **Registrar por que o candidato recusou a oferta** (salário, outra empresa, mudou de ideia). Hoje não há campo estruturado. Sem isso, não conseguimos análise de perda de oferta. Precisa ser construído no InHire.

### Pós-contratação e banco de talentos

- **Histórico de comunicação por candidato** (o que já mandamos pra ele, quando, o que respondeu). Hoje o agente manda email mas não consegue consultar o histórico. Precisa ser construído no InHire.
- **Grupos nomeados no banco de talentos** ("finalistas Q1", "medalhistas de prata"). Hoje só existe busca por texto livre nos 86 mil talentos. Precisa ser construído no InHire.
- **Exportar relatórios e dados consolidados**. Hoje o agente calcula funil, SLA e previsão em tempo real, mas não exporta. Precisa ser construído no InHire.

## Resumo executivo

| Fase do funil | Itens que faltam | Quem precisa fazer |
|---|---|---|
| Abertura de vaga | Campos personalizados, pipeline customizado | InHire + time do agente |
| Atração e divulgação | Programa de indicação, Smart CV programático | Time do agente + InHire |
| Triagem e seleção | Classificação Gostei/Amei, notas do agente persistidas, download de currículo | Time do agente + InHire |
| Entrevista | Scorecard antigo (permissão), Kit com IA, integração de calendário, testes Mindsight, webhook de entrevista concluída | InHire (majoritariamente) |
| Oferta | Webhooks de status, motivo de recusa | InHire |
| Pós-contratação | Histórico de comunicação, grupos de talentos nomeados, exportação de dados | InHire |

Do total que falta: aproximadamente dois terços dependem de construção no InHire e um terço depende apenas de programação adicional no agente.

## Tracking no Linear (itens InHire)

Os 14 itens dependentes do InHire foram abertos como tasks no Linear (projeto **Agente Eli**, time Juliet, label **Agente**):
https://linear.app/inhire/project/agente-eli-e50140df69cb

IDs: JUL-357, JUL-358, JUL-359, JUL-362, JUL-363, JUL-364, JUL-365, JUL-366, JUL-367, JUL-368, JUL-369, JUL-370, JUL-371, JUL-372. Quando um item fechar por lá, atualizar este arquivo.
