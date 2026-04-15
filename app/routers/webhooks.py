import logging
import json
import asyncio

from fastapi import APIRouter, Request, Response

logger = logging.getLogger("agente-inhire.webhooks")

router = APIRouter(tags=["webhooks"])

# Semaphore to prevent thundering herd on auto-screening
_SCREENING_SEMAPHORE = asyncio.Semaphore(5)


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
    """Handle JOB_TALENT_ADDED webhook — auto-screen hunting candidates.
    For organic candidates (via form), InHire auto-screens; for hunting candidates
    (manual/API), we trigger screening on arrival to avoid blind spots."""
    job_id = payload.get("jobId", "")
    talent_id = payload.get("talentId", "")
    source = payload.get("source", "")
    job_talent_id = f"{job_id}*{talent_id}" if job_id and talent_id else ""

    logger.info("Talent added: %s (source=%s, job=%s)", talent_id, source, job_id)

    # Auto-screen hunting candidates (no form → no automatic screening in InHire)
    if source in ("manual", "api") and job_talent_id:
        # Check if post-creation chain is running (avoid duplicate screening)
        try:
            import redis as redis_lib
            from config import get_settings
            r = redis_lib.from_url(get_settings().redis_url, decode_responses=True)
            if r.get(f"inhire:chain_active:{job_id}"):
                r.rpush(f"inhire:screening_pending:{job_id}", job_talent_id)
                r.expire(f"inhire:screening_pending:{job_id}", 600)
                logger.info("Queued screening for %s (chain active)", job_talent_id)
                return
        except Exception:
            pass

        # Dispatch with semaphore to prevent thundering herd
        async def _screen():
            async with _SCREENING_SEMAPHORE:
                try:
                    inhire = app.state.inhire
                    result = await inhire.manual_screening(job_talent_id)
                    if not result:
                        await inhire.analyze_resume(job_talent_id)
                    if hasattr(app.state, "audit_log"):
                        app.state.audit_log.log_action(
                            "", "auto_screening", job_id,
                            candidate=talent_id, detail=f"source={source}",
                        )
                    logger.info("Auto-screening dispatched for %s", job_talent_id)
                except Exception as e:
                    logger.warning("Auto-screening failed for %s: %s", job_talent_id, e)

        asyncio.create_task(_screen())
    else:
        # Organic candidate or unknown source — just log
        try:
            job_name = payload.get("jobName", "Vaga")
            linkedin = payload.get("linkedinUsername", "")
            talent_name = linkedin or "Novo candidato"
            try:
                inhire = app.state.inhire
                talent_data = await inhire._request("GET", f"/talents/{talent_id}")
                talent_name = talent_data.get("name") or talent_name
            except Exception:
                pass
            logger.info("Novo candidato na vaga %s: %s (source=%s)", job_name, talent_name, source)
        except Exception as e:
            logger.warning("Erro ao logar talent added: %s", e)


async def _handle_stage_added(app, payload: dict):
    """Handle candidate moved to new stage. Includes hiring celebration."""
    try:
        # Flag for cron to skip follow-up on recently moved candidates
        try:
            import redis as redis_lib
            from config import get_settings
            r = redis_lib.from_url(get_settings().redis_url, decode_responses=True)
            jt_id = f"{payload.get('jobId', '')}*{payload.get('talentId', '')}"
            if jt_id and "*" in jt_id and not jt_id.startswith("*"):
                r.set(f"inhire:stage_changed:{jt_id}", "1", ex=7200)
        except Exception:
            pass

        talent_name = payload.get("userName") or payload.get("talentName", "Candidato")
        stage = payload.get("stageName", "Nova etapa")
        job_name = payload.get("jobName", "Vaga")
        job_id = payload.get("jobId", "")
        job_talent_id = payload.get("jobTalentId") or payload.get("id", "")
        logger.info("Candidato %s movido para %s (vaga %s)", talent_name, stage, job_name)

        slack = app.state.slack
        conversations = app.state.conversations
        user_mapping = app.state.user_mapping

        # Detect hiring (stage name contains "contratado/hired/offer accepted")
        stage_lower = stage.lower()
        is_hired = any(kw in stage_lower for kw in ("contratado", "contratada", "hired", "offer accepted", "admitido", "admitida"))

        if is_hired:
            # Celebrate! Find the recruiter who owns this job
            await _celebrate_hire(app, talent_name, job_name, job_id, job_talent_id)
            return

        # Regular stage change — notify recruiter with active conversation on this job
        for conv in conversations._conversations.values():
            if conv.get_context("current_job_id") == job_id:
                await slack.send_message(
                    conv.channel_id,
                    f"📌 *{talent_name}* avançou para *{stage}* na vaga *{job_name}*",
                )
                break

        # Task 17 — optionally notify candidate of stage advancement (opt-in per recruiter)
        stage_lower_check = stage.lower()
        is_rejection_or_hire = any(kw in stage_lower_check for kw in (
            "contratado", "contratada", "hired", "offer accepted", "admitido", "admitida",
            "rejeitado", "rejeitada", "reprovado", "reprovada", "rejected",
        ))
        if not is_rejection_or_hire:
            try:
                # Resolve recruiter_id via job ownership
                recruiter_id = None
                try:
                    inhire = app.state.inhire
                    jobs_data = await inhire._request("POST", "/jobs/paginated/lean", json={})
                    all_jobs = jobs_data.get("results", []) if isinstance(jobs_data, dict) else jobs_data
                    for job in all_jobs:
                        if job.get("id") == job_id:
                            recruiter_name = job.get("userName", "")
                            users = user_mapping.get_all_users()
                            for u in users:
                                if u.get("inhire_name") == recruiter_name:
                                    recruiter_id = u.get("slack_user_id")
                                    break
                            break
                except Exception:
                    pass

                user_config = {}
                if recruiter_id:
                    user_config = user_mapping.get_user(recruiter_id) or {}

                if user_config.get("auto_stage_notification", False):
                    talent_data = payload.get("talent") or {}
                    talent_email = talent_data.get("email", "")
                    talent_name_notif = talent_data.get("name") or talent_name
                    if talent_email:
                        subject = f"Atualização sobre sua candidatura — {job_name}"
                        body = (
                            f"Olá {talent_name_notif},\n\n"
                            f"Gostaríamos de informar que sua candidatura para a vaga de "
                            f"{job_name} avançou para a etapa de {stage}.\n\n"
                            f"Em breve entraremos em contato com mais detalhes.\n\n"
                            f"Atenciosamente,\nEquipe de Recrutamento"
                        )
                        inhire = app.state.inhire
                        await inhire.send_email([job_talent_id], subject, body)
                        logger.info(
                            "Notificação de avanço de etapa enviada para %s (%s → %s)",
                            talent_email, job_name, stage,
                        )
            except Exception as e:
                logger.warning("Erro ao notificar candidato sobre mudança de etapa: %s", e)

    except Exception as e:
        logger.exception("Erro ao processar stage change: %s", e)


async def _celebrate_hire(app, talent_name: str, job_name: str, job_id: str, job_talent_id: str = ""):
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

        recruiter_channel = None

        if not target_user:
            # Fallback: notify any conversation tracking this job
            for conv in conversations._conversations.values():
                if conv.get_context("current_job_id") == job_id:
                    recruiter_channel = conv.channel_id
                    await slack.send_message(
                        recruiter_channel,
                        f"🎉 *Contratação!* *{talent_name}* fechou na vaga de *{job_name}*! "
                        f"Parabéns! Quer que eu feche a vaga ou ainda tem posições abertas?",
                    )
                    break
            if not recruiter_channel:
                logger.info("Contratação detectada mas recrutador não encontrado: %s em %s", talent_name, job_name)
                return
        else:
            # Open DM with the recruiter
            dm_resp = await slack.client.conversations_open(users=target_user["slack_user_id"])
            recruiter_channel = dm_resp["channel"]["id"]

            text = (
                f"🎉 *Contratação!* *{talent_name}* fechou na vaga de *{job_name}*! "
                f"Parabéns! Quer que eu feche a vaga ou ainda tem posições abertas?"
            )
            await slack.send_message(recruiter_channel, text)

            # Record in conversation history
            conv = conversations.get_or_create(target_user["slack_user_id"], recruiter_channel)
            conv.add_message("assistant", text)
            conversations.save(conv)

            logger.info("Comemoração de contratação enviada: %s em %s para %s",
                         talent_name, job_name, recruiter_name)

        # Task 11 — check remaining active candidates and prompt devolutiva
        try:
            all_candidates = await inhire.list_job_talents(job_id)
            active_remaining = [
                c for c in all_candidates
                if c.get("status") not in ("rejected", "dropped", "hired")
                and c.get("id") != job_talent_id
            ]

            if active_remaining and recruiter_channel:
                count = len(active_remaining)
                await slack.send_message(
                    recruiter_channel,
                    f"📋 A vaga *{job_name}* ainda tem *{count} candidato(s)* no processo.\n"
                    f"Quer que eu envie devolutiva profissional para todos? "
                    f"Basta dizer: *reprova os candidatos da vaga*",
                )
        except Exception as e:
            logger.warning("Erro ao verificar candidatos remanescentes: %s", e)

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
