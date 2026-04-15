import logging
import re

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

    # Hierarchical memory injection (profile → facts → last session → insights)
    try:
        import json as _json
        import redis as redis_lib
        from config import get_settings
        r = redis_lib.from_url(get_settings().redis_url, decode_responses=True)

        # Level 4: Recruiter profile (permanent)
        profile = r.get(f"inhire:profile:{conv.user_id}")
        if profile:
            parts.append(f"PERFIL DO RECRUTADOR:\n{profile}")

        # Level 3: Accumulated facts (90-day TTL)
        facts_raw = r.get(f"inhire:facts:{conv.user_id}")
        if facts_raw:
            try:
                facts = _json.loads(facts_raw)
                if isinstance(facts, list) and facts:
                    facts_text = "\n".join(f"- {f}" for f in facts[:10])
                    parts.append(f"FATOS APRENDIDOS:\n{facts_text}")
            except Exception:
                pass

        # Level 2: Last session summary (only when returning, 30-day TTL)
        # Stored as a Redis list (newest first) by ConversationManager.save_session_summary
        if is_returning:
            session_items = r.lrange(f"inhire:session_summary:{conv.user_id}", 0, 0)
            if session_items:
                parts.append(f"SESSÃO ANTERIOR:\n{session_items[0]}")

        # Level 1: Weekly insight (mini KAIROS) — recruiter style patterns
        insight = r.get(f"inhire:insights:{conv.user_id}")
        if insight:
            parts.append(f"ESTILO DO RECRUTADOR (padrões aprendidos):\n{insight}")

        # Autonomy mode context
        try:
            user_data = r.get(f"inhire:user:{conv.user_id}")
            if user_data:
                import json as _json2
                u = _json2.loads(user_data)
                mode = u.get("autonomy_mode", "copilot")
                threshold = u.get("auto_advance_threshold", 4.0)
                mode_label = "Piloto Automático" if mode == "autopilot" else "Copiloto"
                parts.append(f"MODO DE AUTONOMIA: {mode_label} (threshold auto-advance: {threshold})")
        except Exception:
            pass
    except Exception:
        pass

    return "\n".join(parts) if parts else None


_NOT_AVAILABLE_MESSAGES = {
    # agendar_entrevista and carta_oferta moved to Layer 1 (session 33)
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
            f"Quer que eu gere uma *string de busca pro LinkedIn* pra você começar o hunting?"
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
            f"Que tal montar o shortlist comparativo?"
        )

    # Tem candidatos alto fit (menos que 5) → sugere dar uma olhada
    if high_fit >= 1 and not has_shortlist:
        return (
            f"\n\n💡 *Dica:* Tem {high_fit} candidato(s) com alto fit. "
            f"Quer ver a triagem detalhada?"
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
            f"Quer enviar uma carta oferta?"
        )

    return ""


def _normalize_phone(raw: str) -> str | None:
    """Normalize phone to international digits-only format for WhatsApp API.

    Examples:
        '+55 (11) 99999-8888' -> '5511999998888'
        '(11) 99999-8888'     -> '5511999998888'
        '11999998888'         -> '5511999998888'
    Returns None if result is not 10-15 digits.
    """
    digits = re.sub(r"\D", "", raw)
    # Brazilian numbers without country code
    if len(digits) in (10, 11) and not digits.startswith("55"):
        digits = "55" + digits
    if len(digits) < 10 or len(digits) > 15:
        return None
    return digits


def _talent_phone(a: dict) -> str | None:
    """Extract and normalize phone from a job-talent record."""
    raw = (
        a.get("talentPhone")
        or (a.get("talent") or {}).get("phone")
        or a.get("phone")
        or ""
    )
    if not raw:
        return None
    return _normalize_phone(raw)


# Actions that NEVER auto-approve (require human in both modes)
_ALWAYS_REQUIRE_APPROVAL = {
    "reject_candidates",
    "send_offer",
}

# Actions that auto-approve ONLY in autopilot mode
_AUTOPILOT_ONLY = {
    "move_candidates",
    "publish_job",
    "auto_advance",
    "send_whatsapp",
    "send_email",
    "send_external_comms",
}

# Actions that auto-approve in BOTH modes (internal, no external impact)
_ALWAYS_AUTO = {
    "auto_screening",
    "smart_match",
    "configure_job",
    "generate_shortlist",
    "generate_linkedin_search",
    "send_interview_kit",
    "follow_up",
}


def _should_auto_approve(user: dict, action: str) -> bool:
    """Check if an action should be auto-approved based on recruiter's autonomy mode.

    Returns True if the action can proceed without explicit recruiter approval.
    """
    if action in _ALWAYS_REQUIRE_APPROVAL:
        return False
    if action in _ALWAYS_AUTO:
        return True
    mode = user.get("autonomy_mode", "copilot")
    if mode == "autopilot" and action in _AUTOPILOT_ONLY:
        return True
    return False
