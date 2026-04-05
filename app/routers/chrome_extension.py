import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger("agente-inhire.chrome-ext")

router = APIRouter(tags=["chrome-extension"])


class ProfileSubmission(BaseModel):
    profile_text: str
    linkedin_url: str | None = None
    slack_user_id: str | None = None


@router.post("/analyze")
async def analyze_profile(submission: ProfileSubmission, request: Request):
    """Receive a LinkedIn profile from the Chrome extension and analyze it."""
    app = request.app
    claude = app.state.claude
    slack = app.state.slack
    conversations = app.state.conversations

    logger.info("Perfil recebido via extensão Chrome: %s", submission.linkedin_url or "sem URL")

    # Find active conversation for this user
    channel_id = None
    conv = None
    if submission.slack_user_id:
        for key, c in conversations._conversations.items():
            if c.user_id == submission.slack_user_id:
                conv = c
                channel_id = c.channel_id
                break

    # Analyze profile
    job_name = conv.get_context("current_job_name", "") if conv else ""
    job_data = conv.get_context("job_data", {}) if conv else {}

    context = ""
    if job_name:
        import json
        context = f"\nVaga: {job_name}\nRequisitos: {json.dumps(job_data.get('requirements', []), ensure_ascii=False)}"

    system = """Você é o Eli, assistente de recrutamento. Analise o perfil do LinkedIn como um amigo dando opinião.

*Candidato:* [nome]
*Fit com a vaga:* 🟢 Alto / 🟡 Médio / 🔴 Baixo

*Pontos fortes:*
• ...

*Pontos de atenção:*
• ...

*Minha recomendação:* [avançar/não avançar/pedir mais info]

Use formatação Slack. Seja direto e útil."""

    analysis = await claude.chat(
        messages=[{"role": "user", "content": f"Analise este perfil:{context}\n\n{submission.profile_text}"}],
        system=system,
    )

    # Send to Slack if we have a channel
    if channel_id:
        url_info = f"\n_Perfil: {submission.linkedin_url}_" if submission.linkedin_url else ""
        await slack.send_message(
            channel_id,
            f"📋 *Perfil recebido via extensão:*{url_info}\n\n{analysis}",
        )

    return {"status": "ok", "analysis": analysis}
