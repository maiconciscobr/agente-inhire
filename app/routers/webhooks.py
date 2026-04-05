import logging
import json

from fastapi import APIRouter, Request, Response

logger = logging.getLogger("agente-inhire.webhooks")

router = APIRouter(tags=["webhooks"])


def _detect_event_type(body: dict) -> str:
    """Detect event type from payload content (InHire doesn't send event type field)."""
    keys = set(body.keys())

    # JOB_TALENT_ADDED — has talentId + jobId + stageName
    if "talentId" in keys and "jobId" in keys:
        if "stageName" in keys:
            return "JOB_TALENT_ADDED"
        return "JOB_TALENT_ADDED"

    # REQUISITION events — has approvers or requisition fields
    if "approvers" in keys or "requisitionId" in keys:
        if body.get("status") in ("approved", "rejected", "pending"):
            return "REQUISITION_STATUS_UPDATED"
        return "REQUISITION_CREATED"

    # FORM_RESPONSE — has formId or response fields
    if "formId" in keys or "formResponseId" in keys:
        return "FORM_RESPONSE_ADDED"

    # JOB events — has job fields but no talent
    if "jobId" in keys and "talentId" not in keys:
        return "JOB_UPDATED"

    return "UNKNOWN"


@router.post("/inhire")
async def inhire_webhook(request: Request):
    """Receive and process webhooks from InHire API."""
    body = await request.json()

    logger.info("Webhook payload: %s", json.dumps(body, default=str)[:1000])

    event_type = _detect_event_type(body)
    logger.info("Webhook detectado como: %s", event_type)

    handler = WEBHOOK_HANDLERS.get(event_type)
    if handler:
        import asyncio
        asyncio.create_task(handler(request.app, body))
    else:
        logger.warning("Evento não mapeado: %s (keys: %s)", event_type, list(body.keys()))

    return Response(status_code=200)


async def _handle_talent_added(app, payload: dict):
    """Handle new candidate added — silent tracking only.
    Proactive alerts (shortlist ready, SLA, etc.) are handled by the hourly cron monitor.
    NOTE: Adding talents to jobs via API (POST /jobs/{id}/talents) is blocked by API Gateway (403).
    Pending resolution with InHire dev team."""
    try:
        job_name = payload.get("jobName", "Vaga")
        talent_id = payload.get("talentId", "")
        linkedin = payload.get("linkedinUsername", "")

        talent_name = linkedin or "Novo candidato"
        try:
            inhire = app.state.inhire
            talent_data = await inhire._request("GET", f"/talents/{talent_id}")
            talent_name = talent_data.get("name") or talent_name
        except Exception:
            pass

        logger.info("Novo candidato na vaga %s: %s (silencioso — cron monitora)", job_name, talent_name)

    except Exception as e:
        logger.exception("Erro ao processar talent added: %s", e)


async def _handle_stage_added(app, payload: dict):
    """Handle candidate moved to new stage. Includes hiring celebration."""
    try:
        talent_name = payload.get("userName") or payload.get("talentName", "Candidato")
        stage = payload.get("stageName", "Nova etapa")
        job_name = payload.get("jobName", "Vaga")
        job_id = payload.get("jobId", "")
        logger.info("Candidato %s movido para %s (vaga %s)", talent_name, stage, job_name)

        slack = app.state.slack
        conversations = app.state.conversations
        user_mapping = app.state.user_mapping

        # Detect hiring (stage name contains "contratado/hired/offer accepted")
        stage_lower = stage.lower()
        is_hired = any(kw in stage_lower for kw in ("contratado", "contratada", "hired", "offer accepted", "admitido", "admitida"))

        if is_hired:
            # Celebrate! Find the recruiter who owns this job
            await _celebrate_hire(app, talent_name, job_name, job_id)
            return

        # Regular stage change — notify recruiter with active conversation on this job
        for conv in conversations._conversations.values():
            if conv.get_context("current_job_id") == job_id:
                await slack.send_message(
                    conv.channel_id,
                    f"📌 *{talent_name}* avançou para *{stage}* na vaga *{job_name}*",
                )
                break

    except Exception as e:
        logger.exception("Erro ao processar stage change: %s", e)


async def _celebrate_hire(app, talent_name: str, job_name: str, job_id: str):
    """Send hiring celebration message to the recruiter who owns the job."""
    try:
        slack = app.state.slack
        user_mapping = app.state.user_mapping
        inhire = app.state.inhire
        conversations = app.state.conversations

        # Find who owns this job
        recruiter_name = ""
        try:
            jobs_data = await inhire._request("POST", "/jobs/paginated/lean", json={})
            all_jobs = jobs_data.get("results", []) if isinstance(jobs_data, dict) else jobs_data
            for job in all_jobs:
                if job.get("id") == job_id:
                    recruiter_name = job.get("userName", "")
                    break
        except Exception:
            pass

        # Find the recruiter's Slack user
        users = user_mapping.get_all_users()
        target_user = None
        for user in users:
            if user.get("inhire_name") == recruiter_name:
                target_user = user
                break

        if not target_user:
            # Fallback: notify any conversation tracking this job
            for conv in conversations._conversations.values():
                if conv.get_context("current_job_id") == job_id:
                    await slack.send_message(
                        conv.channel_id,
                        f"🎉 *Contratação!* *{talent_name}* fechou na vaga de *{job_name}*! "
                        f"Parabéns! Quer que eu feche a vaga ou ainda tem posições abertas?",
                    )
                    return
            logger.info("Contratação detectada mas recrutador não encontrado: %s em %s", talent_name, job_name)
            return

        # Open DM with the recruiter
        dm_resp = await slack.client.conversations_open(users=target_user["slack_user_id"])
        channel_id = dm_resp["channel"]["id"]

        text = (
            f"🎉 *Contratação!* *{talent_name}* fechou na vaga de *{job_name}*! "
            f"Parabéns! Quer que eu feche a vaga ou ainda tem posições abertas?"
        )
        await slack.send_message(channel_id, text)

        # Record in conversation history
        conv = conversations.get_or_create(target_user["slack_user_id"], channel_id)
        conv.add_message("assistant", text)
        conversations.save(conv)

        logger.info("Comemoração de contratação enviada: %s em %s para %s",
                     talent_name, job_name, recruiter_name)

    except Exception as e:
        logger.exception("Erro na comemoração de contratação: %s", e)


async def _handle_requisition_status(app, payload: dict):
    """Handle requisition status update."""
    try:
        slack = app.state.slack
        conversations = app.state.conversations
        status = payload.get("status", "unknown")
        req_id = payload.get("requisitionId") or payload.get("id", "")

        for conv in conversations._conversations.values():
            if conv.get_context("requisition_id") == req_id:
                if status in ("approved", "aprovada"):
                    await slack.send_message(conv.channel_id, "✅ Requisição aprovada!")
                else:
                    await slack.send_message(conv.channel_id, f"❌ Requisição {status}.")
                break
    except Exception as e:
        logger.exception("Erro ao processar requisition: %s", e)


async def _handle_form_response(app, payload: dict):
    """Handle form response submitted."""
    logger.info("Formulário respondido: %s", json.dumps(payload, default=str)[:300])


async def _log_event(app, payload: dict):
    logger.info("Evento recebido: %s", json.dumps(payload, default=str)[:500])


WEBHOOK_HANDLERS = {
    "JOB_TALENT_ADDED": _handle_talent_added,
    "JOB_TALENT_STAGE_ADDED": _handle_stage_added,
    "REQUISITION_STATUS_UPDATED": _handle_requisition_status,
    "REQUISITION_CREATED": _handle_requisition_status,
    "FORM_RESPONSE_ADDED": _handle_form_response,
    "JOB_ADDED": _log_event,
    "JOB_UPDATED": _log_event,
    "JOB_REMOVED": _log_event,
    "JOB_PAGE_CREATED": _log_event,
    "UNKNOWN": _log_event,
}
