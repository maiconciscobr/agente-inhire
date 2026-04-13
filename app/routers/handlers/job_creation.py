import logging

from services.conversation import FlowState
from routers.handlers.helpers import _send, _send_approval

logger = logging.getLogger("agente-inhire.slack-router")


async def _handle_briefing(conv, app, channel_id: str, text: str):
    slack = app.state.slack
    claude = app.state.claude

    has_missing = bool(conv.get_context("job_data", {}).get("missing_info"))
    intent = await claude.classify_briefing_reply(text, has_missing_info=has_missing)

    if intent == "cancel":
        conv.state = FlowState.IDLE
        conv.set_context("briefing_parts", None)
        conv.set_context("job_data", None)
        await _send(conv, slack, channel_id, "Beleza, cancelei a criação da vaga. No que mais posso ajudar?")
        return

    if intent == "more_info":
        parts = conv.get_context("briefing_parts", [])
        parts.append(text)
        conv.set_context("briefing_parts", parts)
        await _send(conv, slack, channel_id, "Anotado! Mais alguma coisa ou posso gerar a vaga?")
        return

    # intent == "proceed"
    job_data = conv.get_context("job_data")

    if not job_data:
        # First time finishing — extract job data from briefing parts
        parts = conv.get_context("briefing_parts", [])
        full_briefing = "\n".join(parts)
        await _send(conv, slack, channel_id, "Analisando o briefing... ⏳")
        job_data = await claude.extract_job_data(full_briefing)
        conv.set_context("job_data", job_data)

        # Check missing info — ask once, but don't block
        missing = job_data.get("missing_info", [])
        if missing and any(m for m in missing if m):
            missing_text = "\n".join(f"• {m}" for m in missing if m)
            await _send(
                conv, slack, channel_id,
                f"Só faltam alguns detalhes:\n{missing_text}\n\n"
                "Quer complementar ou posso criar assim mesmo?",
            )
            return

    await _generate_and_post_draft(conv, app, channel_id, job_data)


async def _generate_and_post_draft(conv, app, channel_id, job_data):
    slack = app.state.slack
    claude = app.state.claude

    job_description = await claude.generate_job_description(job_data)
    conv.set_context("job_description", job_description)
    conv.state = FlowState.WAITING_JOB_APPROVAL

    title = job_data.get("title", "Nova Vaga")
    await _send_approval(
        conv, slack, channel_id,
        title=f"Rascunho: {title}",
        details=f"```\n{job_description[:2900]}\n```",
        callback_id="job_draft_approval",
    )
