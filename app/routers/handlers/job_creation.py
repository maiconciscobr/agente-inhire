import logging

from services.conversation import FlowState
from routers.handlers.helpers import _send, _send_approval

logger = logging.getLogger("agente-inhire.slack-router")


async def _handle_briefing(conv, app, channel_id: str, text: str):
    slack = app.state.slack
    claude = app.state.claude
    text_lower = text.lower()
    done_keywords = ["pronto", "isso é tudo", "é isso", "só isso", "finalizar", "gerar"]

    # "gerar" = skip missing info and generate anyway
    force_generate = "gerar" in text_lower

    if any(kw in text_lower for kw in done_keywords):
        # If user typed more than just "pronto", include it as briefing
        extra = text_lower
        for kw in done_keywords:
            extra = extra.replace(kw, "").strip()
        if extra and len(extra) > 10:
            parts = conv.get_context("briefing_parts", [])
            parts.append(text)
            conv.set_context("briefing_parts", parts)

        # If we already extracted job_data and user said "gerar", go straight to draft
        job_data = conv.get_context("job_data")
        if not job_data or not force_generate:
            parts = conv.get_context("briefing_parts", [])
            full_briefing = "\n".join(parts)

            await _send(conv, slack, channel_id, "Analisando o briefing... ⏳")

            job_data = await claude.extract_job_data(full_briefing)
            conv.set_context("job_data", job_data)

        if not force_generate:
            missing = job_data.get("missing_info", [])
            if missing and any(m for m in missing if m):
                missing_text = "\n".join(f"• {m}" for m in missing if m)
                await _send(
                    conv, slack, channel_id,
                    f"⚠️ Informações faltando:\n{missing_text}\n\n"
                    'Quer complementar ou digo "gerar" para prosseguir mesmo assim?',
                )
                return

        await _generate_and_post_draft(conv, app, channel_id, job_data)
    else:
        parts = conv.get_context("briefing_parts", [])
        parts.append(text)
        conv.set_context("briefing_parts", parts)
        await _send(conv, slack, channel_id, 'Anotado! Continua, ou diz "pronto" quando terminar.')


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
