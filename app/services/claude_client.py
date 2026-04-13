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
1. Abertura de vagas (briefing → job description → publicação)
2. Triagem de candidatos (fit scores, shortlists comparativos)
3. Gestão de pipeline (mover candidatos entre etapas, reprovar com devolutiva)
4. Análise de perfis (comparar candidato com vaga)
5. Busca LinkedIn (gerar strings booleanas pra hunting)
6. Busca no banco de talentos (busca full-text por nome, skills, experiência, localização)
7. Relatórios e status de vagas (SLA, distribuição de candidatos)
8. Responder perguntas sobre recrutamento, entrevistas, cultura, processos seletivos — você é especialista em R&S e compartilha seu conhecimento com prazer

CONHECIMENTO DO INHIRE:

Vagas: nome, departamento, descrição, senioridade (Júnior/Pleno/Sênior/Especialista), salário (ideal + máximo), regime (CLT/PJ/Cooperado/Estágio), modelo (Presencial/Híbrido/Remoto), localidade, múltiplas posições, status (Aberta/Congelada/Fechada/Cancelada).

Pipeline padrão: Listados → Em abordagem → Inscritos → Bate-papo com RH → Entrevista com Liderança → Entrevista Técnica → Offer → Contratados.

Triagem (Screening AI): 3 pilares (CV, formulário, salário). Alto fit (>= 4.0), Médio (2.0-4.0), Baixo (<= 2.0).

PONTOS DE PAUSA (NUNCA executar sem aprovação explícita):
- Publicar vaga
- Mover candidatos de etapa
- Reprovar candidatos
- Enviar carta oferta
- Comunicar candidatos externamente

Nesses momentos, mude o tom de "fiz" pra "posso fazer?".

O QUE VOCÊ NÃO CONSEGUE FAZER (limitações reais — seja honesto):
- Gerar links diretos para perfis de talentos ou vagas no InHire — não existe essa URL na API
- Anexar arquivos ou currículos a talentos — a API não suporta upload de arquivos pelo agente
- Acessar scorecards ou avaliações de entrevista — endpoint retorna 403
- Listar usuários do workspace ou times — endpoint retorna 403
- Enviar WhatsApp para candidatos — não existe API pública do InTerview ainda
- Editar dados de um talento existente (telefone, email, etc.) — só leitura
- Ver histórico de comunicação com candidato — não exposto na API
- Acessar métricas consolidadas (tempo médio de contratação, etc.) — não existe endpoint

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
            "Lista as vagas abertas do recrutador no InHire. "
            "Use quando o recrutador perguntar sobre suas vagas, quiser ver vagas ativas, ou pedir uma lista."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "criar_vaga",
        "description": (
            "Inicia abertura de uma nova vaga a partir do briefing do recrutador. "
            "Use quando o recrutador quiser abrir uma posição, contratar alguém, recrutar, ou criar uma nova vaga."
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
            "Avança candidatos aprovados para a próxima etapa do pipeline. "
            "Use quando o recrutador quiser mover, avançar, ou aprovar candidatos para próxima fase."
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
            "Reprova candidatos em lote com envio de devolutiva profissional. "
            "Use quando o recrutador quiser reprovar, rejeitar, dispensar candidatos, ou enviar devolutiva."
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
            "Agenda uma entrevista com candidato, com integração automática de calendário. "
            "Use quando o recrutador quiser agendar, marcar entrevista, ou scheduling."
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
            "Cria e envia carta oferta para um candidato aprovado. "
            "Use quando o recrutador quiser enviar oferta, proposta, ou offer letter."
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
            "vagas acompanhadas, configurações personalizadas. "
            "Use quando o recrutador perguntar 'o que você sabe sobre mim?', "
            "'o que você lembra?', 'suas memórias', 'meu perfil', ou quiser saber "
            "o que o agente aprendeu sobre ele."
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
        "name": "conversa_livre",
        "description": (
            "Responde perguntas gerais sobre recrutamento, processos do InHire, ou qualquer assunto "
            "que não se encaixe nas outras ferramentas. Use como fallback."
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
            model = resp.model or self.model
            prices = PRICING.get(model, PRICING["claude-sonnet-4-20250514"])

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
            logger.warning("Erro ao logar usage: %s", e)

    async def chat(self, messages: list[dict], system: str | None = None,
                   dynamic_context: str | None = None) -> str:
        t0 = time.monotonic()
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
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

        tool_block = None
        text_parts = []
        for block in resp.content:
            if block.type == "tool_use" and tool_block is None:
                tool_block = block
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

        import json as json_mod
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        try:
            return json_mod.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Haiku retornou JSON invalido em parse_routine_request: %s", raw[:200])
            return {"action": "list"}

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
        )
