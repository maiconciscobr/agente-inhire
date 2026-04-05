import json
import logging

import anthropic

from config import Settings

logger = logging.getLogger("agente-inhire.claude")

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
6. Relatórios e status de vagas (SLA, distribuição de candidatos)
7. Responder perguntas sobre recrutamento, entrevistas, cultura, processos seletivos — você é especialista em R&S e compartilha seu conhecimento com prazer

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

REGRAS:
- Sempre português brasileiro
- Nunca invente dados sobre candidatos
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

    async def chat(self, messages: list[dict], system: str | None = None,
                   dynamic_context: str | None = None) -> str:
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=self._build_system(system or SYSTEM_PROMPT_STATIC, dynamic_context),
            messages=messages,
        )
        return resp.content[0].text

    async def detect_intent(self, messages: list[dict],
                            dynamic_context: str | None = None) -> dict:
        """Use Claude tool calling to detect user intent.

        Returns:
            {"tool": "tool_name", "input": {...}} if a tool was called
            {"tool": None, "text": "..."} if no tool was called
        """
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self._build_system(SYSTEM_PROMPT_STATIC, dynamic_context),
            tools=ELI_TOOLS,
            tool_choice={"type": "any"},
            messages=messages,
        )

        for block in resp.content:
            if block.type == "tool_use":
                return {"tool": block.name, "input": block.input}

        # Fallback (shouldn't happen with tool_choice=any)
        text = next((b.text for b in resp.content if hasattr(b, "text")), "")
        return {"tool": None, "text": text}

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
