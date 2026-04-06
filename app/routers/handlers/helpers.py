import logging

logger = logging.getLogger("agente-inhire.slack-router")


async def _send(conv, slack, channel_id: str, text: str, blocks: list | None = None):
    """Send a Slack message AND record it in conversation history."""
    conv.add_message("assistant", text)
    await slack.send_message(channel_id, text, blocks=blocks)


async def _send_approval(conv, slack, channel_id: str, title: str, details: str, callback_id: str):
    """Send an approval request AND record it in conversation history."""
    conv.add_message("assistant", f"{title}\n{details}")
    await slack.send_approval_request(channel_id, title, details, callback_id)


def _resolve_job_id(conv, tool_input: dict) -> str | None:
    """Resolve job_id from tool input or conversation context."""
    return tool_input.get("job_id") or conv.get_context("current_job_id")


def _build_dynamic_context(conv, is_returning: bool = False) -> str | None:
    """Build per-request dynamic context for Claude intent detection.
    When is_returning=True, includes summary and pending state so Claude
    can greet the recruiter with context from the previous session.
    Includes weekly insight if available (mini KAIROS).
    """
    parts = []

    # Welcome back context — inject when recruiter returns after inactivity
    if is_returning:
        if conv.summary:
            parts.append(f"CONTEXTO DA ÚLTIMA CONVERSA (resumo):\n{conv.summary}")
        state_label = conv.state.value if hasattr(conv.state, 'value') else str(conv.state)
        if state_label != "idle":
            parts.append(f"Estado pendente: {state_label}")
        parts.append(
            "INSTRUÇÃO: O recrutador está voltando após um período de inatividade. "
            "Cumprimente-o e resuma brevemente onde pararam e se há algo pendente. "
            "Se houver vaga ativa, mencione novidades ou próximos passos."
        )

    job_name = conv.get_context("current_job_name")
    job_id = conv.get_context("current_job_id")
    if job_name:
        parts.append(f"Vaga ativa: {job_name} (ID: {job_id})")
    shortlist = conv.get_context("shortlist_candidates")
    if shortlist:
        parts.append(f"Shortlist carregado com {len(shortlist)} candidatos")

    # Weekly insight (mini KAIROS) — inject recruiter style if available
    try:
        import redis as redis_lib
        from config import get_settings
        r = redis_lib.from_url(get_settings().redis_url, decode_responses=True)
        insight = r.get(f"inhire:insights:{conv.user_id}")
        if insight:
            parts.append(f"ESTILO DO RECRUTADOR (padrões aprendidos):\n{insight}")
    except Exception:
        pass

    return "\n".join(parts) if parts else None


_NOT_AVAILABLE_MESSAGES = {
    "agendar_entrevista": (
        "Ainda não consigo agendar entrevistas por aqui — estamos finalizando a integração de calendário.\n\n"
        "*Como fazer no InHire:*\n"
        "1. Abra a vaga e clique no candidato\n"
        "2. Clique em *Agendar entrevista*\n"
        "3. Escolha data/hora e participantes\n"
        "4. O convite é enviado automaticamente com link do Meet/Teams\n\n"
        "📖 https://help.inhire.app/pt-BR/articles/8725343"
    ),
    "carta_oferta": (
        "A carta oferta por aqui está em fase de validação.\n\n"
        "*Como fazer no InHire:*\n"
        "1. Mova o candidato para a etapa *Offer*\n"
        "2. Clique em *Enviar carta oferta*\n"
        "3. Escolha o template e preencha os dados (salário, data de início)\n"
        "4. Envie para aprovação interna → depois ao candidato\n\n"
        "📖 https://help.inhire.app/pt-BR/articles/6967313"
    ),
}

# Guide messages for features the agent handles partially (post-creation steps)
_INHIRE_GUIDES = {
    "divulgacao": (
        "📢 *Divulgação da vaga*\n"
        "Ainda não consigo publicar a vaga nos portais por aqui.\n\n"
        "*Como fazer no InHire:*\n"
        "1. Abra a vaga → aba *Divulgação*\n"
        "2. Configure visibilidade (pública/restrita)\n"
        "3. Ative os portais: LinkedIn, Indeed, Netvagas\n"
        "4. Revise o nome de divulgação e a descrição\n\n"
        "📖 https://help.inhire.app/pt-BR/collections/3728052"
    ),
    "formulario": (
        "📋 *Formulário de inscrição*\n"
        "Ainda não consigo configurar o formulário por aqui.\n\n"
        "*Como fazer no InHire:*\n"
        "1. Abra a vaga → aba *Formulário*\n"
        "2. Adicione perguntas personalizadas\n"
        "3. Marque pretensão salarial e CV como obrigatórios\n"
        "4. Defina perguntas eliminatórias se necessário\n\n"
        "📖 https://help.inhire.app/pt-BR/collections/4073016"
    ),
    "triagem": (
        "🤖 *Agente de Triagem IA*\n"
        "Ainda não consigo configurar os critérios de triagem por aqui.\n\n"
        "*Como fazer no InHire:*\n"
        "1. Abra a vaga → seção *Agente de Triagem*\n"
        "2. Defina os critérios (Essencial/Importante/Diferencial)\n"
        "3. Configure a faixa salarial para screening\n"
        "4. Ative o agente — ele analisa automaticamente cada candidato\n\n"
        "📖 https://help.inhire.app/pt-BR/articles/12674798"
    ),
    "scorecard": (
        "📝 *Scorecard e Kit de Entrevista*\n"
        "Ainda não consigo configurar o scorecard por aqui.\n\n"
        "*Como fazer no InHire:*\n"
        "1. Abra a vaga → aba *Kit de Entrevista*\n"
        "2. Defina os critérios de avaliação por entrevista\n"
        "3. Adicione o roteiro de perguntas\n"
        "4. Configure os permissionamentos dos avaliadores\n\n"
        "📖 https://help.inhire.app/pt-BR/articles/8718108"
    ),
    "automacoes": (
        "⚡ *Automações*\n"
        "Ainda não consigo configurar automações por aqui.\n\n"
        "*Como fazer no InHire:*\n"
        "1. Abra a vaga → aba *Automações*\n"
        "2. Configure gatilhos (ex: enviar teste quando candidato avança)\n"
        "3. Defina delays e templates de email\n\n"
        "📖 https://help.inhire.app/pt-BR/articles/12710593"
    ),
}


async def _tool_not_available(conv, app, channel_id: str, tool_name: str):
    """Send friendly message for Layer 2 tools (not yet available)."""
    msg = _NOT_AVAILABLE_MESSAGES.get(
        tool_name, "Essa funcionalidade ainda não está disponível. Em breve!"
    )
    await _send(conv, app.state.slack, channel_id, msg)


def _suggest_next_action(conv, total_candidates: int = 0, high_fit: int = 0,
                         has_shortlist: bool = False, stage_counts: dict | None = None) -> str:
    """Analyze job state and return a proactive suggestion for the recruiter."""
    job_name = conv.get_context("current_job_name", "")
    if not job_name:
        return ""

    stage_counts = stage_counts or {}

    # Vaga recém-criada, sem candidatos → sugere hunting
    if total_candidates == 0:
        return (
            f"\n\n💡 *Dica:* A vaga ainda não tem candidatos. "
            f'Quer que eu gere uma *string de busca pro LinkedIn* pra você começar o hunting? Diz "busca linkedin".'
        )

    # Tem candidatos mas poucos com alto fit → sugere revisar critérios ou esperar
    if total_candidates > 0 and total_candidates < 5 and high_fit == 0:
        return (
            f"\n\n💡 *Dica:* Tem {total_candidates} candidato(s) mas nenhum com alto fit ainda. "
            f"Vale reforçar o hunting ou esperar mais inscrições."
        )

    # Tem 5+ candidatos alto fit e ainda não fez shortlist → sugere shortlist
    if high_fit >= 5 and not has_shortlist:
        return (
            f"\n\n💡 *Dica:* Já tem *{high_fit} candidatos com alto fit*! "
            f'Que tal montar o shortlist comparativo? Diz "shortlist".'
        )

    # Tem candidatos alto fit (menos que 5) → sugere dar uma olhada
    if high_fit >= 1 and not has_shortlist:
        return (
            f"\n\n💡 *Dica:* Tem {high_fit} candidato(s) com alto fit. "
            f'Diz "candidatos" pra ver a triagem detalhada.'
        )

    # Candidatos em etapa de entrevista → sugere acompanhar
    interview_stages = ["Bate-papo com RH", "Entrevista com Liderança", "Entrevista Técnica",
                        "Entrevista com a Liderança"]
    in_interview = sum(stage_counts.get(s, 0) for s in interview_stages)
    if in_interview > 0:
        return (
            f"\n\n💡 *Dica:* Tem *{in_interview} candidato(s) em etapa de entrevista*. "
            f"Quando tiver um retorno, me avisa que eu movo pra próxima etapa."
        )

    # Candidatos em Offer → sugere carta oferta
    in_offer = stage_counts.get("Offer", 0)
    if in_offer > 0:
        return (
            f"\n\n💡 *Dica:* Tem *{in_offer} candidato(s) na etapa de Offer*! "
            f'Quer enviar uma carta oferta? Diz "carta oferta".'
        )

    return ""
