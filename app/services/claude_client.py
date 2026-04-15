import json
import logging
import time

import anthropic

from config import Settings

logger = logging.getLogger("agente-inhire.claude")
usage_logger = logging.getLogger("agente-inhire.claude.usage")

PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10},
}

# Parte estática do system prompt — persona, regras, conhecimento InHire.
# Cacheada pela Anthropic API entre requests (cache_control: ephemeral, TTL 5 min).
SYSTEM_PROMPT_STATIC = """Você é o Eli, assistente de recrutamento do InHire. Você é um amigo do recrutador — não um chatbot corporativo. Trabalha junto, se importa com o resultado e faz o máximo pra liberar a cabeça do recrutador pro que realmente importa.

COMO FALAR:
- Fale como amigo, não como sistema. Use "você", nunca "senhor/senhora"
- Frases curtas e diretas. Vá ao ponto
- Emoji com moderação (1-2 por mensagem, quando fizer sentido)
- Use formatação Slack: *bold*, listas com •
- Comemore quando dá certo ("Pronto!", "Feito!", "Show!")
- Se errar, assuma: "Ops, deu ruim. Vou resolver."
- NUNCA fale em terceira pessoa ("O sistema identificou...")
- NUNCA use jargão técnico (endpoint, webhook, JWT)
- NUNCA pareça que está lendo um manual

O QUE VOCÊ SABE FAZER:
1. Abertura de vagas (briefing → job description → publicação → configuração automática)
2. Duplicar vagas existentes (copiar pipeline, settings, descrição)
3. Triagem de candidatos (fit scores, shortlists comparativos, screening sob demanda)
4. Gestão de pipeline (mover candidatos entre etapas, reprovar com devolutiva personalizada)
5. Análise de perfis (comparar candidato com vaga, adicionar à vaga)
6. Busca LinkedIn (gerar strings booleanas) + processar URLs do LinkedIn
7. Smart Match (busca IA no banco de 86k+ talentos cruzando com requisitos da vaga)
8. Busca no banco de talentos (full-text por nome, skills, experiência, localização)
9. Relatórios e status (SLA, funil visual, previsão de fechamento, comparação entre vagas)
10. Entrevistas (agendar, remarcar, lembrete 2h antes, preencher scorecard, kit de entrevista)
11. Carta oferta (template, ClickSign, aprovação, envio ao candidato)
12. Comunicação (WhatsApp, email, notificação de etapa, devolutiva em massa)
13. Testes (enviar DISC, formulários de avaliação, pesquisa NPS)
14. Rotinas automáticas (alertas recorrentes, briefing diário, status semanal)
15. Responder perguntas sobre recrutamento — especialista em R&S

CONHECIMENTO DO INHIRE:

Vagas: nome, departamento, descrição, senioridade (Júnior/Pleno/Sênior/Especialista), salário (ideal + máximo), regime (CLT/PJ/Cooperado/Estágio), modelo (Presencial/Híbrido/Remoto), localidade, múltiplas posições, status (Aberta/Congelada/Fechada/Cancelada).

Pipeline padrão: Listados → Em abordagem → Inscritos → Bate-papo com RH → Entrevista com Liderança → Entrevista Técnica → Offer → Contratados.

Triagem (Screening AI): 3 pilares (CV, formulário, salário). Alto fit (>= 4.0), Médio (2.0-4.0), Baixo (<= 2.0).

PONTOS DE PAUSA (NUNCA executar sem aprovação explícita):
- Publicar vaga
- Mover candidatos de etapa
- Reprovar candidatos
- Enviar carta oferta
- Comunicar candidatos externamente (WhatsApp — requer aprovação, funciona se candidato interagiu com InHire nas últimas 24h)

Nesses momentos, mude o tom de "fiz" pra "posso fazer?".

O QUE VOCÊ NÃO CONSEGUE FAZER (limitações reais — seja honesto):
- Gerar links diretos para perfis de talentos ou vagas no InHire — não existe essa URL na API
- Anexar arquivos ou currículos a talentos — a API não suporta upload de arquivos pelo agente
- Editar dados de um talento existente (telefone, email, etc.) — só leitura
- Ver histórico de comunicação com candidato — não exposto na API
- Integração de calendário real (Google/Outlook) — agendamos no modo manual

Se o recrutador pedir algo dessa lista, explique de forma simples que ainda não é possível. Nunca finja que fez algo que não fez.

REGRAS:
- Sempre português brasileiro
- NUNCA invente dados — nome, email, telefone, score, etapa, links, URLs
- NUNCA crie links fictícios (ex: app.inhire.app/talent/..., inhire.app/perfil/...)
- Se não sabe ou não consegue, diga claramente — nunca preencha com dados inventados
- Se faltar informação, pergunte
- Use nome da vaga (não ID) nas mensagens
- Se o recrutador tiver pressa (msgs curtas, urgência), seja mais direto e menos emoji"""


# Tools para intent detection via Claude tool calling.
# Layer 1 = funcional, Layer 2 = retorna "em breve" (bloqueio externo).
ELI_TOOLS = [
    {
        "name": "listar_vagas",
        "description": (
            "Lista as vagas abertas do recrutador no InHire."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "criar_vaga",
        "description": (
            "Inicia abertura de uma nova vaga a partir do briefing do recrutador."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "briefing": {
                    "type": "string",
                    "description": "Texto completo do recrutador descrevendo a vaga",
                },
            },
            "required": ["briefing"],
        },
    },
    {
        "name": "ver_candidatos",
        "description": (
            "Mostra os candidatos de uma vaga com detalhes de triagem: quem são, scores de fit, "
            "classificação (alto/médio/baixo fit), nomes, LinkedIn. "
            "Foco nas PESSOAS. Use quando o recrutador perguntar sobre candidatos, triagem, "
            "screening, inscritos, ou quiser saber quem se candidatou."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "ID da vaga (UUID). Omita para usar a vaga ativa na conversa.",
                },
                "stage_filter": {
                    "type": "string",
                    "description": "Filtrar por nome da etapa (ex: 'Entrevista', 'Triagem'). Vazio = todos.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "gerar_shortlist",
        "description": (
            "Monta um shortlist comparativo ranqueando os melhores candidatos da vaga. "
            "Inclui análise de pontos fortes, atenção e recomendação de ranking. "
            "Use quando o recrutador pedir shortlist, comparativo, resumo dos melhores, ou ranking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "ID da vaga (UUID). Omita para usar a vaga ativa na conversa.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "status_vaga",
        "description": (
            "Relatório de saúde e progresso de uma vaga: SLA, dias aberta, prazo, "
            "distribuição de candidatos por etapa do pipeline, métricas gerais. "
            "Foco na VAGA e no PIPELINE. Use quando o recrutador perguntar como está a vaga, "
            "SLA, prazo, relatório, progresso, ou saúde do processo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "ID da vaga (UUID). Omita para usar a vaga ativa na conversa.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "busca_linkedin",
        "description": (
            "Gera strings de busca booleanas otimizadas para hunting no LinkedIn Recruiter. "
            "Use quando o recrutador pedir busca, string de hunting, sourcing, ou onde encontrar candidatos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "ID da vaga (UUID). Omita para usar a vaga ativa na conversa.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "analisar_perfil",
        "description": (
            "Analisa o fit de um perfil de candidato com a vaga ativa. "
            "Use quando o recrutador colar um texto de perfil, currículo, experiência profissional, "
            "ou pedir para avaliar/analisar um candidato específico."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "perfil_texto": {
                    "type": "string",
                    "description": "Texto do perfil do candidato para análise",
                },
                "job_id": {
                    "type": "string",
                    "description": "ID da vaga (UUID). Omita para usar a vaga ativa na conversa.",
                },
            },
            "required": ["perfil_texto"],
        },
    },
    {
        "name": "mover_candidatos",
        "description": (
            "Avança candidatos aprovados para a próxima etapa do pipeline."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga (UUID)."},
            },
            "required": [],
        },
    },
    {
        "name": "reprovar_candidatos",
        "description": (
            "Reprova candidatos em lote com envio de devolutiva profissional."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga (UUID)."},
            },
            "required": [],
        },
    },
    {
        "name": "agendar_entrevista",
        "description": (
            "Agenda uma entrevista com candidato."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga (UUID)."},
            },
            "required": [],
        },
    },
    {
        "name": "carta_oferta",
        "description": (
            "Cria e envia carta oferta para um candidato aprovado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga (UUID)."},
            },
            "required": [],
        },
    },
    {
        "name": "guia_inhire",
        "description": (
            "Mostra como fazer algo diretamente no InHire (passo a passo com link). "
            "Use quando o recrutador perguntar sobre divulgação de vaga, formulário de inscrição, "
            "configurar triagem IA, scorecard, kit de entrevista, automações, ou qualquer "
            "configuração que o agente ainda não faz automaticamente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "O tópico: divulgacao, formulario, triagem, scorecard, automacoes",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "ver_memorias",
        "description": (
            "Mostra o que o Eli sabe/lembra sobre o recrutador: padrões de decisão, "
            "vagas acompanhadas, configurações personalizadas."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "buscar_talentos",
        "description": (
            "Busca candidatos no banco de talentos do InHire usando busca full-text. "
            "Pesquisa por nome, skills, experiência, localização, cargo. "
            "Use quando o recrutador quiser buscar no banco de talentos, encontrar candidatos "
            "por perfil, pesquisar talentos, ou procurar alguém específico no sistema."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto de busca (ex: 'python backend São Paulo', 'designer UX senior')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Máximo de resultados (default 10)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "enviar_whatsapp",
        "description": (
            "Envia mensagem WhatsApp para um candidato. "
            "Use quando o recrutador pedir pra mandar WhatsApp, avisar candidato, "
            "comunicar por WhatsApp, notificar candidato, enviar mensagem, "
            "falar com candidato, avisar sobre entrevista/resultado, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "ID da vaga (se mencionada ou em contexto)",
                },
                "candidate_name": {
                    "type": "string",
                    "description": "Nome do candidato para enviar a mensagem",
                },
                "message_intent": {
                    "type": "string",
                    "description": "O que o recrutador quer comunicar ao candidato",
                },
            },
            "required": ["message_intent"],
        },
    },
    {
        "name": "gerenciar_rotina",
        "description": (
            "Cria, lista ou cancela rotinas automáticas do recrutador. "
            "Use quando o recrutador pedir algo recorrente "
            "(todo dia, toda semana, me avisa quando, de tempos em tempos, "
            "me manda X no horário Y, quero receber, rotina, agendar alerta, etc.) "
            "ou quiser ver/cancelar suas rotinas ativas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "O pedido completo do recrutador sobre rotinas",
                },
            },
            "required": ["request"],
        },
    },
    {
        "name": "divulgar_vaga",
        "description": "Publica a vaga em portais de emprego (LinkedIn, Indeed, Netvagas, etc.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "UUID da vaga"},
            },
        },
    },
    {
        "name": "configurar_vaga",
        "description": "Configura triagem IA, formulário e scorecard de uma vaga já criada",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "UUID da vaga"},
                "setup_screening": {"type": "boolean", "description": "Configurar triagem IA com critérios do briefing"},
                "setup_form": {"type": "boolean", "description": "Configurar formulário de inscrição"},
                "setup_scorecard": {"type": "boolean", "description": "Configurar scorecard de entrevista"},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "comparar_vagas",
        "description": "Compara performance de vagas abertas (SLA, candidatos, velocidade)",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "smart_match",
        "description": (
            "Busca inteligente no banco de talentos. Cruza requisitos da vaga "
            "com CVs usando IA. Encontra candidatos compatíveis automaticamente. "
            "Use quando o recrutador pedir para achar, encontrar, buscar candidatos "
            "compatíveis para a vaga, match de talentos, ou sourcing no banco interno."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Critérios de busca em linguagem natural (opcional, usa requisitos da vaga se vazio)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Máximo de candidatos para retornar (default 15)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "processar_linkedin",
        "description": (
            "Processa perfis do LinkedIn colados pelo recrutador. "
            "Extrai dados, cria talento no InHire, vincula à vaga e avalia fit. "
            "Use quando o recrutador colar URLs do LinkedIn (linkedin.com/in/...) "
            "ou mencionar perfis do LinkedIn para adicionar, processar ou avaliar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URLs ou usernames do LinkedIn extraídos da mensagem",
                },
            },
            "required": ["urls"],
        },
    },
    {
        "name": "duplicar_vaga",
        "description": (
            "Duplica uma vaga existente (copia pipeline, configurações, descrição). "
            "Use quando o recrutador pedir para copiar, duplicar, reabrir, criar igual, "
            "ou abrir uma vaga parecida com outra."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga a duplicar"},
            },
            "required": [],
        },
    },
    {
        "name": "avaliar_entrevista",
        "description": (
            "Preenche o scorecard de avaliação de entrevista de um candidato. "
            "Use quando o recrutador quiser registrar feedback, dar notas, avaliar, "
            "preencher scorecard, ou relatar como foi a entrevista."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga"},
                "candidate_name": {"type": "string", "description": "Nome do candidato avaliado"},
                "feedback_text": {
                    "type": "string",
                    "description": "Feedback do entrevistador em linguagem natural (notas, impressões, recomendação)",
                },
            },
            "required": ["feedback_text"],
        },
    },
    {
        "name": "enviar_teste",
        "description": (
            "Envia teste DISC, formulário de triagem, ou outro formulário para candidatos. "
            "Use quando o recrutador pedir para enviar DISC, teste, formulário, avaliação "
            "por email para um ou mais candidatos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga"},
                "test_type": {
                    "type": "string",
                    "description": "Tipo: 'disc', 'formulario', ou 'screening'",
                },
                "candidate_name": {"type": "string", "description": "Nome do candidato (ou 'todos')"},
            },
            "required": ["test_type"],
        },
    },
    {
        "name": "pesquisa_candidato",
        "description": (
            "Envia pesquisa de satisfação (NPS) para candidatos ou mostra métricas. "
            "Use quando o recrutador pedir pesquisa de experiência, NPS, satisfação, "
            "feedback dos candidatos sobre o processo seletivo, ou métricas de survey."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga"},
                "action": {
                    "type": "string",
                    "description": "'enviar' para agendar pesquisa ou 'metricas' para ver resultados",
                },
            },
            "required": [],
        },
    },
    {
        "name": "modo_autonomia",
        "description": (
            "Troca entre modo copiloto e piloto automático, ou ajusta threshold/silenciar. "
            "Use quando o recrutador pedir mais/menos autonomia, modo piloto, "
            "modo copiloto, silenciar notificações, ou ajustar score de auto-advance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": "'copilot' ou 'autopilot'",
                },
                "threshold": {
                    "type": "number",
                    "description": "Score mínimo para auto-advance (0-5). Só no autopilot.",
                },
                "mute_hours": {
                    "type": "number",
                    "description": "Silenciar notificações por N horas",
                },
            },
        },
    },
    {
        "name": "conversa_livre",
        "description": (
            "Fallback para perguntas gerais sobre recrutamento ou qualquer assunto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pergunta": {
                    "type": "string",
                    "description": "A pergunta ou mensagem do recrutador",
                },
            },
            "required": ["pergunta"],
        },
    },
]


class ClaudeService:
    """Claude API client for AI-powered recruitment tasks."""

    def __init__(self, settings: Settings):
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model
        self.fast_model = settings.claude_model_fast

    def _build_system(self, static: str, dynamic: str | None = None) -> list[dict]:
        """Build system prompt blocks with prompt caching on the static part.

        The static block gets cache_control: ephemeral (5 min TTL).
        The dynamic block (optional) carries per-request context and is never cached.
        """
        blocks = [
            {
                "type": "text",
                "text": static,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        if dynamic:
            blocks.append({"type": "text", "text": dynamic})
        return blocks

    def _log_usage(self, method: str, resp, latency_ms: int):
        try:
            usage = resp.usage
            if usage is None:
                logger.warning("_log_usage(%s): resp.usage is None", method)
                return
            model = resp.model or self.model
            prices = PRICING.get(model)
            if prices is None:
                logger.warning("_log_usage(%s): modelo '%s' sem pricing, usando Sonnet", method, model)
                prices = PRICING["claude-sonnet-4-20250514"]

            input_tokens = getattr(usage, "input_tokens", 0)
            output_tokens = getattr(usage, "output_tokens", 0)
            cache_creation = getattr(usage, "cache_creation_input_tokens", 0)
            cache_read = getattr(usage, "cache_read_input_tokens", 0)

            cost = (
                (input_tokens - cache_creation - cache_read) * prices["input"] / 1_000_000
                + output_tokens * prices["output"] / 1_000_000
                + cache_creation * prices["cache_write"] / 1_000_000
                + cache_read * prices["cache_read"] / 1_000_000
            )

            usage_logger.info(json.dumps({
                "method": method,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
                "stop_reason": resp.stop_reason,
                "latency_ms": latency_ms,
                "estimated_cost_usd": round(cost, 6),
            }))
        except Exception as e:
            logger.warning("Erro ao logar usage para %s: %s", method, e, exc_info=True)

    async def chat(self, messages: list[dict], system: str | None = None,
                   dynamic_context: str | None = None, max_tokens: int = 4096) -> str:
        t0 = time.monotonic()
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=self._build_system(system or SYSTEM_PROMPT_STATIC, dynamic_context),
            messages=messages,
        )
        self._log_usage("chat", resp, int((time.monotonic() - t0) * 1000))
        return resp.content[0].text

    async def detect_intent(self, messages: list[dict],
                            dynamic_context: str | None = None) -> dict:
        """Use Claude tool calling to detect user intent.

        Returns:
            {"tool": "tool_name", "input": {...}, "text": "..."} if a tool was called
            {"tool": None, "text": "..."} if no tool was called (direct response)
        """
        t0 = time.monotonic()
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=self._build_system(SYSTEM_PROMPT_STATIC, dynamic_context),
            tools=ELI_TOOLS,
            tool_choice={"type": "auto"},
            messages=messages,
        )
        self._log_usage("detect_intent", resp, int((time.monotonic() - t0) * 1000))

        if not resp.content:
            logger.warning("detect_intent: resp.content vazio (stop_reason=%s)", resp.stop_reason)
            return {"tool": None, "text": ""}

        if resp.stop_reason == "max_tokens":
            logger.warning("detect_intent: resposta truncada (max_tokens)")

        tool_block = None
        text_parts = []
        for block in resp.content:
            if block.type == "tool_use" and tool_block is None:
                tool_block = block
            elif block.type == "tool_use":
                logger.debug("detect_intent: tool_use extra ignorado: %s", block.name)
            elif hasattr(block, "text") and block.text:
                text_parts.append(block.text)

        combined_text = "\n".join(text_parts) if text_parts else ""

        if tool_block:
            return {"tool": tool_block.name, "input": tool_block.input, "text": combined_text}

        return {"tool": None, "text": combined_text or ""}

    async def summarize_conversation(self, messages: list[dict]) -> str:
        """Compress conversation history into a 5-line summary for context efficiency."""
        formatted = "\n".join(
            f"{'Recrutador' if m['role'] == 'user' else 'Eli'}: {m['content'][:200]}"
            for m in messages[-30:]
        )
        system = (
            "Resuma o estado atual desta conversa entre recrutador e assistente de recrutamento "
            "em exatamente 5 linhas curtas:\n"
            "1. Quem é o recrutador e contexto geral\n"
            "2. Qual vaga ou processo está sendo discutido (se houver)\n"
            "3. O que já foi feito ou decidido\n"
            "4. O que está pendente ou em andamento\n"
            "5. Último assunto ou pedido\n\n"
            "Retorne APENAS as 5 linhas, sem numeração, sem markdown. Seja conciso e factual."
        )
        return await self.chat(
            messages=[{"role": "user", "content": f"Resuma esta conversa:\n\n{formatted}"}],
            system=system,
        )

    async def extract_facts(self, messages: list[dict]) -> list[str]:
        """Extract durable facts from a conversation session (preferences, criteria, decisions).
        Uses Haiku for cost efficiency (~$0.001 per extraction)."""
        if not messages or len(messages) < 4:
            return []

        # Take last 30 messages max
        recent = messages[-30:]
        msgs_text = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in recent)

        try:
            resp = await self.client.messages.create(
                model=self.fast_model,
                max_tokens=300,
                system=[{"type": "text", "text": (
                    "Extraia fatos duradouros desta conversa de recrutamento. "
                    "Fatos = preferências, critérios recorrentes, decisões importantes, padrões do recrutador. "
                    "NÃO inclua: dados temporários, saudações, erros. "
                    "Retorne uma lista com no máximo 5 fatos, um por linha, sem bullets. "
                    "Se não houver fatos relevantes, retorne VAZIO."
                )}],
                messages=[{"role": "user", "content": msgs_text}],
            )
            text = resp.content[0].text.strip()
            if not text or text.upper() == "VAZIO":
                return []
            return [f.strip() for f in text.split("\n") if f.strip()][:5]
        except Exception as e:
            logger.warning("Erro ao extrair fatos: %s", e)
            return []

    async def generate_recruiter_profile(self, facts: list[str], patterns: str, decisions_summary: str) -> str:
        """Generate a concise recruiter profile from accumulated facts and patterns.
        Uses Haiku. Called monthly by KAIROS consolidation."""
        context = f"Fatos acumulados:\n" + "\n".join(f"- {f}" for f in facts)
        if patterns:
            context += f"\n\nPadrões semanais:\n{patterns}"
        if decisions_summary:
            context += f"\n\nResumo de decisões:\n{decisions_summary}"

        try:
            resp = await self.client.messages.create(
                model=self.fast_model,
                max_tokens=200,
                system=[{"type": "text", "text": (
                    "Gere um perfil conciso do recrutador em 3-4 linhas. "
                    "Inclua: experiência, foco (tipo de vaga), critérios mais valorizados, "
                    "padrões de comportamento, preferências de comunicação. "
                    "Seja objetivo e direto."
                )}],
                messages=[{"role": "user", "content": context}],
            )
            return resp.content[0].text.strip()
        except Exception as e:
            logger.warning("Erro ao gerar perfil: %s", e)
            return ""

    async def classify_briefing_reply(self, user_text: str, has_missing_info: bool) -> str:
        """Classify user reply during briefing collection.

        Returns one of: "proceed", "more_info", "cancel"
        - proceed: user wants to move forward (create the job, skip missing info)
        - more_info: user is providing additional briefing details
        - cancel: user wants to stop/cancel the flow
        """
        system = (
            "Você classifica a resposta de um recrutador durante a criação de uma vaga.\n"
            "O recrutador já passou o briefing inicial e foi perguntado se quer complementar.\n\n"
            "Classifique a mensagem em EXATAMENTE uma palavra:\n"
            "- proceed — quer prosseguir, criar a vaga, não tem mais info, manda gerar, "
            "qualquer variação de 'vai', 'cria', 'pode ser', 'prossiga', 'não tenho', 'tá bom', etc.\n"
            "- more_info — está fornecendo dados adicionais (responsabilidades, benefícios, stack, etc.)\n"
            "- cancel — quer cancelar, desistir, parar, mudar de assunto\n\n"
            "Responda APENAS: proceed, more_info ou cancel"
        )
        context = f"Tem info faltando: {'sim' if has_missing_info else 'não'}"
        t0 = time.monotonic()
        resp = await self.client.messages.create(
            model=self.fast_model,
            max_tokens=20,
            system=[{"type": "text", "text": system}],
            messages=[{"role": "user", "content": f"[{context}]\nRecrutador disse: {user_text}"}],
        )
        self._log_usage("classify_briefing_reply", resp, int((time.monotonic() - t0) * 1000))
        result = resp.content[0].text.strip().lower()
        if result not in ("proceed", "more_info", "cancel"):
            return "proceed" if any(w in result for w in ["proceed", "prosseg"]) else "more_info"
        return result

    async def parse_routine_request(self, text: str, available_jobs: list[dict]) -> dict:
        """Parse a routine request from natural language.

        Returns dict with: action, routine_type, job_id, job_name,
        hour_brt, minute, frequency, cancel_id, description.
        """
        jobs_context = "\n".join(
            f"- {j.get('name', '?')} (ID: {j.get('id', '?')})"
            for j in available_jobs[:20]
        )

        system = (
            "Você interpreta pedidos de rotinas automáticas de um recrutador.\n\n"
            "Vagas ativas disponíveis:\n" + (jobs_context or "(nenhuma)") + "\n\n"
            "Classifique o pedido e retorne JSON puro (sem markdown, sem ```):\n"
            "{\n"
            '  "action": "create" | "list" | "cancel",\n'
            '  "routine_type": "novos_candidatos" | "status_vagas" | "shortlist_update" | "resumo_semanal",\n'
            '  "job_id": "uuid" ou null,\n'
            '  "job_name": "nome da vaga" ou null,\n'
            '  "hour_brt": 8,\n'
            '  "minute": 0,\n'
            '  "frequency": "weekdays" | "daily" | "weekly_mon" | "weekly_fri" etc,\n'
            '  "cancel_id": "1" (numero ou id, so para cancel),\n'
            '  "description": "resumo curto do que a rotina faz"\n'
            "}\n\n"
            "Regras:\n"
            "- Se o recrutador quer listar, action=list (ignore outros campos)\n"
            "- Se quer cancelar, action=cancel + cancel_id\n"
            "- Se quer criar: preencha todos os campos\n"
            "- Horário padrão: 9h BRT se não especificado\n"
            "- Frequência padrão: weekdays (seg-sex) se não especificado\n"
            "- novos_candidatos e shortlist_update precisam de vaga. Se não mencionou, job_id=null\n"
            "- status_vagas e resumo_semanal não precisam de vaga\n"
            "- Resolva o nome da vaga para o job_id correto da lista acima\n"
            "- Retorne APENAS o JSON, nada mais"
        )

        t0 = time.monotonic()
        resp = await self.client.messages.create(
            model=self.fast_model,
            max_tokens=300,
            system=[{"type": "text", "text": system}],
            messages=[{"role": "user", "content": text}],
        )
        self._log_usage("parse_routine_request", resp, int((time.monotonic() - t0) * 1000))

        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Haiku retornou JSON invalido em parse_routine_request: %s", raw[:200])
            raise ValueError("Falha ao interpretar pedido de rotina")

    async def extract_job_data(self, briefing: str) -> dict:
        """Extract structured job data from a free-form briefing. Returns parsed dict."""
        system = """Você é um extrator de dados de vagas do InHire. A partir de um briefing informal,
extraia os seguintes campos em JSON puro (sem markdown, sem ```):
{
  "title": "Nome exato do cargo mencionado (ex: Desenvolvedor Python Sênior)",
  "department": "área/departamento",
  "seniority": "Júnior/Pleno/Sênior/Especialista",
  "location": "local (Remoto/Híbrido/Presencial + cidade se mencionada)",
  "work_model": "remote/hybrid/onsite",
  "salary_range": {"min": number, "max": number},
  "contract_type": "CLT/PJ/Cooperado/Estágio/Menor Aprendiz/Autônomo",
  "urgency": "alta/média/baixa",
  "sla_days": number ou null,
  "positions_count": number,
  "requirements": ["requisito obrigatório 1", "requisito 2"],
  "nice_to_have": ["diferencial 1"],
  "responsibilities": ["responsabilidade 1"],
  "benefits": ["benefício 1"],
  "technical_manager": "nome do gestor técnico se mencionado" ou null,
  "missing_info": ["informações que faltam para uma vaga completa"]
}

IMPORTANTE:
- O campo "title" deve conter o cargo EXATO mencionado pelo recrutador
- Se o recrutador não mencionou senioridade, tente inferir dos requisitos
- Se não mencionou quantidade de posições, assuma 1
- Se não mencionou SLA, use null
- Em missing_info, liste o que falta para uma vaga profissional completa
- Retorne APENAS o JSON, nada mais"""
        raw = await self.chat(
            messages=[{"role": "user", "content": briefing}],
            system=system,
        )
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Falha ao parsear JSON: %s", text[:200])
            return {"title": "Nova Vaga", "raw_briefing": briefing, "missing_info": []}

    async def generate_job_description(self, job_data: dict) -> str:
        """Generate a professional job description from structured data."""
        system = """Você é um redator especializado em job descriptions para o mercado brasileiro.
Gere uma descrição de vaga profissional, atrativa e inclusiva em português brasileiro.

Formato obrigatório:
# [Título da Vaga]

## Sobre a empresa
[Placeholder — a empresa preencherá]

## Responsabilidades
[Lista de responsabilidades]

## Requisitos obrigatórios
[Lista de requisitos]

## Diferenciais
[Lista de diferenciais, se houver]

## Benefícios
[Lista de benefícios, se houver]

## Informações da vaga
- Modelo: [Remoto/Híbrido/Presencial]
- Regime: [CLT/PJ/etc]
- Senioridade: [nível]
- Faixa salarial: [se informada]

Retorne apenas o texto da vaga, sem JSON. Use linguagem inclusiva."""
        return await self.chat(
            messages=[
                {
                    "role": "user",
                    "content": f"Gere a job description:\n{json.dumps(job_data, ensure_ascii=False, indent=2)}",
                }
            ],
            system=system,
        )

    async def summarize_candidates(self, candidates: list[dict], job_name: str = "") -> str:
        """Create a comparative summary of shortlisted candidates."""
        system = """Você é um analista de recrutamento do InHire. Resuma os candidatos de forma comparativa.

Para cada candidato:
• *Nome* — Score: X.X (Status)
  Pontos fortes: ...
  Pontos de atenção: ...

No final:
*Recomendação de ranking:*
1. [Nome] — motivo
2. [Nome] — motivo

Use formatação Slack (*bold*, listas com •). Seja conciso."""
        context = f" para a vaga de *{job_name}*" if job_name else ""
        return await self.chat(
            messages=[
                {
                    "role": "user",
                    "content": f"Analise estes candidatos{context}:\n{json.dumps(candidates, ensure_ascii=False, indent=2)}",
                }
            ],
            system=system,
        )

    async def generate_rejection_message(self, job_name: str) -> str:
        """Generate a professional rejection message."""
        system = """Gere uma mensagem de devolutiva profissional e empática para candidatos
não aprovados em um processo seletivo. A mensagem deve:
- Agradecer pela participação
- Ser respeitosa e encorajadora
- Mencionar que o perfil ficará no banco de talentos
- Ser curta (máximo 5 linhas)
Retorne apenas o texto da mensagem, sem aspas."""
        return await self.chat(
            messages=[{"role": "user", "content": f"Devolutiva para candidatos não aprovados na vaga: {job_name}"}],
            system=system,
            max_tokens=512,
        )

    async def classify_rejection_reason(
        self, candidate_name: str, candidate_summary: str, job_name: str, job_requirements: str,
    ) -> str:
        """Classify rejection reason into InHire enum: overqualified, underqualified, location, other."""
        system = (
            "Você classifica motivos de rejeição de candidatos. "
            "Responda apenas: overqualified, underqualified, location, ou other."
        )
        user_content = (
            f"Candidato: {candidate_name}\nResumo: {candidate_summary}\n"
            f"Vaga: {job_name}\nRequisitos: {job_requirements}\n\n"
            "Classifique o motivo de rejeição em UMA palavra: overqualified, underqualified, location, ou other.\n"
            "Responda APENAS a palavra."
        )
        t0 = time.monotonic()
        resp = await self.client.messages.create(
            model=self.fast_model,
            max_tokens=20,
            system=[{"type": "text", "text": system}],
            messages=[{"role": "user", "content": user_content}],
        )
        self._log_usage("classify_rejection_reason", resp, int((time.monotonic() - t0) * 1000))
        reason = resp.content[0].text.strip().lower()
        valid = {"overqualified", "underqualified", "location", "other"}
        return reason if reason in valid else "other"

    async def generate_personalized_rejection(
        self, candidate_name: str, stage_reached: str, strengths: str, job_name: str,
    ) -> str:
        """Generate a personalized rejection message for a specific candidate."""
        system = "Você gera devolutivas de processos seletivos. Seja empático e específico."
        user_content = (
            f"Candidato: {candidate_name}\n"
            f"Vaga: {job_name}\n"
            f"Etapa alcançada: {stage_reached}\n"
            f"Pontos fortes observados: {strengths}\n\n"
            "Gere uma devolutiva profissional e empática em 3-4 linhas.\n"
            "Seja específico — mencione a etapa que alcançou e pelo menos um ponto positivo.\n"
            "Tom: respeitoso, encorajador, sem clichês."
        )
        t0 = time.monotonic()
        resp = await self.client.messages.create(
            model=self.fast_model,
            max_tokens=300,
            system=[{"type": "text", "text": system}],
            messages=[{"role": "user", "content": user_content}],
        )
        self._log_usage("generate_personalized_rejection", resp, int((time.monotonic() - t0) * 1000))
        return resp.content[0].text.strip()

    async def generate_whatsapp_message(self, intent: str, candidate_name: str,
                                         job_name: str = "", context: str = "") -> str:
        """Generate a professional WhatsApp message for a candidate."""
        system = (
            "Gere uma mensagem profissional e cordial para enviar via WhatsApp a um candidato "
            "em um processo seletivo. A mensagem deve:\n"
            "- Ser breve (máximo 500 caracteres — é WhatsApp, não email)\n"
            "- Usar tom profissional mas acolhedor\n"
            "- Não usar markdown (WhatsApp não renderiza)\n"
            "- Incluir o nome do candidato\n"
            "- Mencionar a empresa se possível\n"
            "Retorne apenas o texto da mensagem, sem aspas."
        )
        user_msg = f"Candidato: {candidate_name}\nVaga: {job_name}\nContexto: {context}\nIntenção: {intent}"
        return await self.chat(
            messages=[{"role": "user", "content": user_msg}],
            system=system,
        )
