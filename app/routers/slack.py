import asyncio
import hashlib
import hmac
import json
import logging
import time

import redis as redis_lib
from fastapi import APIRouter, Request, Response

from config import get_settings
from services.conversation import FlowState

# Extracted handler modules (refactored session 26)
from routers.handlers.helpers import (
    _send, _send_approval, _resolve_job_id, _build_dynamic_context,
    _suggest_next_action, _tool_not_available,
    _NOT_AVAILABLE_MESSAGES, _INHIRE_GUIDES,
)
from routers.handlers.job_creation import _handle_briefing, _generate_and_post_draft
from routers.handlers.candidates import (
    _start_screening_flow, _check_candidates, _build_shortlist,
    _move_approved_candidates, _reject_candidates,
)
from routers.handlers.interviews import (
    _start_offer_flow, _handle_offer_input, _create_and_send_offer,
    _start_scheduling, _handle_scheduling_input,
)
from routers.handlers.hunting import _analyze_profile, _generate_linkedin_search, _job_status_report

logger = logging.getLogger("agente-inhire.slack-router")

router = APIRouter(tags=["slack"])

# Deduplication via Redis (survives restarts)
DEDUP_PREFIX = "inhire:dedup:"
DEDUP_TTL = 300  # 5 minutes — Slack retries within 3 min

# Conversation lock (prevents concurrent event corruption)
LOCK_PREFIX = "inhire:lock:"
LOCK_TTL = 30  # Auto-expire lock after 30s (safety net)
LOCK_RETRY_INTERVAL = 0.3  # seconds between lock attempts
LOCK_MAX_WAIT = 10  # max seconds to wait for lock

_dedup_redis: redis_lib.Redis | None = None


def _get_dedup_redis() -> redis_lib.Redis | None:
    """Lazy-init Redis connection for deduplication."""
    global _dedup_redis
    if _dedup_redis is None:
        try:
            settings = get_settings()
            _dedup_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)
            _dedup_redis.ping()
        except Exception as e:
            logger.warning("Redis indisponível para dedup, usando fallback em memória: %s", e)
            _dedup_redis = None
    return _dedup_redis

# In-memory fallback if Redis is down
_processed_events: dict[str, float] = {}
_MAX_EVENTS = 1000


def _verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify Slack request signature."""
    settings = get_settings()
    secret = settings.slack_signing_secret
    if not secret or secret == "CHANGE-ME":
        return True
    if not timestamp or not signature:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except ValueError:
        return False
    sig_base = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed = "v0=" + hmac.new(secret.encode(), sig_base.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


def _is_duplicate(event_id: str) -> bool:
    """Check if we already processed this event (Slack retries).
    Uses Redis with in-memory fallback.
    """
    if not event_id:
        return False

    r = _get_dedup_redis()
    if r:
        try:
            key = f"{DEDUP_PREFIX}{event_id}"
            # SET NX returns True if key was set (not duplicate), False if already exists
            was_new = r.set(key, "1", ex=DEDUP_TTL, nx=True)
            return not was_new
        except Exception:
            pass  # Fall through to in-memory

    # In-memory fallback
    if event_id in _processed_events:
        return True
    _processed_events[event_id] = time.time()
    if len(_processed_events) > _MAX_EVENTS:
        cutoff = time.time() - DEDUP_TTL
        to_remove = [k for k, v in _processed_events.items() if v < cutoff]
        for k in to_remove:
            del _processed_events[k]
    return False


async def _acquire_conversation_lock(user_id: str) -> bool:
    """Acquire a per-user conversation lock via Redis SET NX.
    Waits up to LOCK_MAX_WAIT seconds, retrying every LOCK_RETRY_INTERVAL.
    Returns True if lock acquired, False if timed out.
    """
    r = _get_dedup_redis()
    if not r:
        return True  # No Redis = no lock, proceed anyway

    key = f"{LOCK_PREFIX}{user_id}"
    deadline = time.time() + LOCK_MAX_WAIT
    while time.time() < deadline:
        try:
            if r.set(key, "1", ex=LOCK_TTL, nx=True):
                return True
        except Exception:
            return True  # Redis error = proceed without lock
        await asyncio.sleep(LOCK_RETRY_INTERVAL)

    logger.warning("Lock timeout for user %s after %ds", user_id, LOCK_MAX_WAIT)
    return False


def _release_conversation_lock(user_id: str):
    """Release per-user conversation lock."""
    r = _get_dedup_redis()
    if r:
        try:
            r.delete(f"{LOCK_PREFIX}{user_id}")
        except Exception:
            pass


@router.post("/events")
async def slack_events(request: Request):
    """Handle Slack Events API callbacks (DM messages)."""
    body_bytes = await request.body()

    # Verify signature
    if not _verify_slack_signature(
        body_bytes,
        request.headers.get("X-Slack-Request-Timestamp", ""),
        request.headers.get("X-Slack-Signature", ""),
    ):
        logger.warning("Slack signature verification failed")
        return Response(status_code=401)

    body = json.loads(body_bytes)

    if body.get("type") == "url_verification":
        return {"challenge": body["challenge"]}

    # Deduplicate retries
    event_id = body.get("event_id", "")
    if _is_duplicate(event_id):
        logger.debug("Evento duplicado ignorado: %s", event_id)
        return Response(status_code=200)

    event = body.get("event", {})
    logger.info("Evento recebido: type=%s channel_type=%s subtype=%s bot_id=%s user=%s text=%s",
                event.get("type"), event.get("channel_type"), event.get("subtype"),
                event.get("bot_id"), event.get("user"), (event.get("text", "")[:50] if event.get("text") else ""))

    subtype = event.get("subtype")
    if event.get("bot_id") or (subtype and subtype != "file_share"):
        return Response(status_code=200)

    if event.get("type") == "message" and event.get("channel_type") == "im":
        user_id = event["user"]
        channel_id = event["channel"]
        text = event.get("text", "").strip()
        files = event.get("files", [])

        # Handle file uploads (CVs) — blocked until POST /jobs/{id}/talents is available
        if files:
            import asyncio
            asyncio.create_task(_handle_file_upload(request.app, user_id, channel_id, text, files))
            return Response(status_code=200)

        if not text:
            return Response(status_code=200)

        import asyncio
        asyncio.create_task(_handle_dm(request.app, user_id, channel_id, text))

    return Response(status_code=200)


@router.post("/interactions")
async def slack_interactions(request: Request):
    """Handle Slack interactive components (button clicks)."""
    form_data = await request.form()
    payload = json.loads(form_data["payload"])

    if payload["type"] == "block_actions":
        action = payload["actions"][0]
        action_id = action["action_id"]
        callback_id = action["value"]
        user_id = payload["user"]["id"]
        channel_id = payload["channel"]["id"]

        import asyncio
        asyncio.create_task(
            _handle_approval(request.app, user_id, channel_id, action_id, callback_id)
        )

    return Response(status_code=200)


# ==============================================================================
# DM HANDLER — Routes messages based on conversation state
# ==============================================================================

async def _handle_dm(app, user_id: str, channel_id: str, text: str):
    locked = await _acquire_conversation_lock(user_id)
    try:
        slack = app.state.slack
        claude = app.state.claude
        inhire = app.state.inhire
        conversations = app.state.conversations
        user_mapping = app.state.user_mapping

        # Record interaction for inactivity tracking
        if hasattr(app.state, "monitor"):
            app.state.monitor.record_interaction(user_id)

        # Check if recruiter responded to a recent proactive alert
        if hasattr(app.state, "learning"):
            app.state.learning.check_alert_response(user_id)

        # --- Onboarding: check if user is registered ---
        if not user_mapping.is_registered(user_id):
            await _handle_onboarding(app, user_id, channel_id, text)
            return

        conv = conversations.get_or_create(user_id, channel_id)

        # Detect returning recruiter (stale = 2h+ inactivity)
        is_returning = conv.is_stale() and (conv.summary or conv.get_context("current_job_name"))
        if is_returning:
            logger.info("Recruiter %s returning after inactivity", user_id)

        # Resume stale conversation with compressed summary
        if conv.is_stale() and conv.summary:
            logger.info("Resuming stale conversation for %s with summary", user_id)
            conv.compress_with_summary()

        # Store returning flag in context for _handle_idle to pick up
        if is_returning:
            conv.set_context("_is_returning", True)

        conv.add_message("user", text)

        text_lower = text.lower().strip()

        # Global commands
        if text_lower in ("cancelar", "reset", "recomeçar"):
            conversations.reset(user_id, channel_id)
            await slack.send_message(channel_id, "Pronto, conversa zerada! Como posso te ajudar?")
            return

        # Toggle candidate communication
        if "desativar comunicação" in text_lower or "desativar comunicacao" in text_lower:
            user_mapping.set_comms_enabled(user_id, False)
            await _send(conv, slack, channel_id, "Pronto, comunicação automática com candidatos *desativada*.")
            return
        if "ativar comunicação" in text_lower or "ativar comunicacao" in text_lower:
            user_mapping.set_comms_enabled(user_id, True)
            await _send(conv, slack, channel_id, "Comunicação automática com candidatos *ativada*! ✅")
            return

        # Route by state
        handlers = {
            FlowState.IDLE: _handle_idle,
            FlowState.COLLECTING_BRIEFING: _handle_briefing,
            FlowState.WAITING_JOB_APPROVAL: _handle_waiting_approval,
            FlowState.WAITING_SHORTLIST_APPROVAL: _handle_waiting_approval,
            FlowState.WAITING_STAGE_APPROVAL: _handle_waiting_approval,
            FlowState.WAITING_REJECTION_APPROVAL: _handle_waiting_approval,
            FlowState.MONITORING_CANDIDATES: _handle_monitoring,
            FlowState.SCHEDULING_INTERVIEW: _handle_scheduling_input,
            FlowState.CREATING_OFFER: _handle_offer_input,
            FlowState.WAITING_OFFER_APPROVAL: _handle_waiting_approval,
        }
        handler = handlers.get(conv.state, _handle_general)
        await handler(conv, app, channel_id, text)

        # Generate summary if message threshold reached
        if conv.needs_summary():
            try:
                summary = await claude.summarize_conversation(conv.messages)
                conv.summary = summary
                conv.msgs_since_summary = 0
                logger.info("Conversation summary generated for %s", user_id)
            except Exception as e:
                logger.warning("Failed to generate conversation summary: %s", e)

        conversations.save(conv)

    except Exception as e:
        logger.exception("Erro ao processar DM: %s", e)
        await app.state.slack.send_message(
            channel_id, "Ops, deu um problema aqui. Vou tentar resolver."
        )
    finally:
        _release_conversation_lock(user_id)


# ==============================================================================
# CV / FILE UPLOAD HANDLER
# ==============================================================================

async def _handle_file_upload(app, user_id: str, channel_id: str, text: str, files: list):
    """Handle file uploads — extract CV data. Adding to job pending API Gateway fix."""
    slack = app.state.slack
    claude = app.state.claude
    inhire = app.state.inhire
    conversations = app.state.conversations
    conv = conversations.get_or_create(user_id, channel_id)

    if len(files) > 1:
        await _send(conv, slack, channel_id, f"Recebi {len(files)} currículos! Vou processar todos... ⏳")

    for file_info in files:
        try:
            filename = file_info.get("name", "")
            mimetype = file_info.get("mimetype", "")
            url = file_info.get("url_private_download") or file_info.get("url_private", "")

            if not url:
                await _send(conv, slack, channel_id, f"Não consegui acessar `{filename}`. Tenta mandar de novo?")
                continue

            supported = mimetype in ("application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document") or \
                        filename.lower().endswith((".pdf", ".docx"))
            if not supported:
                await _send(conv, slack, channel_id, f"Esse formato (`{filename}`) eu não consigo ler. Manda em *PDF* ou *DOCX*!")
                continue

            await _send(conv, slack, channel_id, f"Processando currículo `{filename}`... ⏳")

            # Download file from Slack
            import httpx
            from config import get_settings
            settings = get_settings()
            auth_header = {"Authorization": f"Bearer {settings.slack_bot_token}"}
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=auth_header, follow_redirects=False)
                while resp.status_code in (301, 302, 303, 307, 308):
                    redirect_url = resp.headers.get("location", "")
                    if not redirect_url:
                        break
                    resp = await client.get(redirect_url, headers=auth_header, follow_redirects=False)
                file_bytes = resp.content

            # Extract text
            cv_text = ""
            if filename.lower().endswith(".pdf") or "pdf" in mimetype:
                import fitz
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                for page in doc:
                    cv_text += page.get_text()
                doc.close()
            elif filename.lower().endswith(".docx"):
                import io
                from docx import Document
                doc = Document(io.BytesIO(file_bytes))
                cv_text = "\n".join(p.text for p in doc.paragraphs)

            if not cv_text or len(cv_text) < 50:
                await _send(conv, slack, channel_id,
                    f"Não consegui ler o texto de `{filename}` — pode ser imagem escaneada. "
                    "Tenta mandar um PDF com texto selecionável, ou cola o conteúdo aqui.")
                continue

            # Extract candidate data with Claude
            extract_system = """Extraia do currículo os dados do candidato em JSON puro (sem markdown):
{"name": "Nome completo", "email": "email" ou null, "phone": "telefone" ou null,
"linkedin": "username LinkedIn" ou null, "location": "cidade/estado" ou null,
"headline": "cargo atual ou último", "skills": ["skill1", "skill2"],
"experience_years": number ou null, "current_company": "empresa atual" ou null,
"summary": "resumo profissional em 2-3 linhas"}
Retorne APENAS o JSON."""

            raw = await claude.chat(
                messages=[{"role": "user", "content": f"Extraia os dados deste currículo:\n\n{cv_text[:4000]}"}],
                system=extract_system,
            )

            import json as json_module
            parsed_text = raw.strip()
            if parsed_text.startswith("```"):
                parsed_text = parsed_text.split("\n", 1)[1].rsplit("```", 1)[0]
            try:
                candidate_data = json_module.loads(parsed_text)
            except Exception:
                candidate_data = {"name": "Não identificado", "summary": cv_text[:200]}

            candidate_name = candidate_data.get("name", "Não identificado")

            # Build talent payload
            talent_payload = {"name": candidate_name}
            for field, key in [("email", "email"), ("phone", "phone"), ("linkedin", "linkedinUsername"),
                               ("location", "location"), ("headline", "headline")]:
                if candidate_data.get(field):
                    talent_payload[key] = candidate_data[field]

            # Find job — check context first, then try to match by name from user text
            job_id = conv.get_context("current_job_id")
            job_name = conv.get_context("current_job_name", "")
            job_data = conv.get_context("job_data", {})

            if not job_id and text:
                # User might have mentioned a job name — try to find it
                try:
                    jobs_data = await inhire._request("POST", "/jobs/paginated/lean", json={})
                    all_jobs = jobs_data.get("results", []) if isinstance(jobs_data, dict) else jobs_data
                    text_lower_search = text.lower()
                    for j in all_jobs:
                        if j.get("status") == "open" and j.get("name", "").lower() in text_lower_search:
                            job_id = j["id"]
                            job_name = j["name"]
                            conv.set_context("current_job_id", job_id)
                            conv.set_context("current_job_name", job_name)
                            break
                except Exception:
                    pass
            talent_id = ""
            added_to_job = False

            # Create file record in InHire to attach CV
            file_refs = []
            try:
                file_record = await inhire.create_file_record(filename, category="resumes")
                file_refs = [{
                    "id": file_record["id"],
                    "fileCategory": "resumes",
                    "name": filename,
                }]
                logger.info("Registro de CV criado no InHire: %s", file_record["id"])
            except Exception as file_err:
                logger.warning("Não conseguiu criar registro de CV: %s (continuando sem anexo)", file_err)

            if job_id:
                try:
                    result = await inhire.add_talent_to_job(
                        job_id, talent_payload, source="api", files=file_refs or None
                    )
                    talent_id = result.get("talentId", "")
                    added_to_job = True
                except Exception as add_err:
                    if "409" in str(add_err):
                        # Talent exists — try to find and link
                        try:
                            talents = await inhire._request("GET", "/talents", params={"search": candidate_name})
                            if isinstance(talents, list) and talents:
                                existing_id = talents[0].get("id", "")
                                if existing_id:
                                    result = await inhire.add_existing_talent_to_job(job_id, existing_id)
                                    talent_id = existing_id
                                    added_to_job = True
                        except Exception:
                            pass
                        if not added_to_job:
                            talent_id = "já existente"
                    else:
                        raise add_err
            else:
                try:
                    result = await inhire._request("POST", "/talents", json=talent_payload)
                    talent_id = result.get("id", "")
                except Exception as create_err:
                    if "409" in str(create_err):
                        talent_id = "já existente"
                    else:
                        raise create_err

            # Analyze fit if there's an active job
            fit_analysis = ""
            if job_name:
                fit_analysis = await claude.chat(
                    messages=[{
                        "role": "user",
                        "content": f"Vaga: {job_name}\nRequisitos: {json_module.dumps(job_data.get('requirements', []), ensure_ascii=False)}\n\nCandidato:\n{json_module.dumps(candidate_data, ensure_ascii=False)}",
                    }],
                    system="Analise o fit deste candidato com a vaga. Retorne:\n*Fit:* 🟢 Alto / 🟡 Médio / 🔴 Baixo\n*Justificativa:* 1-2 linhas\nUse formatação Slack.",
                )

            # Build response
            skills_text = ", ".join(candidate_data.get("skills", [])[:8])
            cv_tag = " (CV anexado)" if file_refs else ""
            msg = f"✅ *Candidato cadastrado na vaga {job_name}!*{cv_tag}\n\n" if added_to_job else f"✅ *Candidato cadastrado no banco de talentos!*{cv_tag}\n\n"
            msg += f"*Nome:* {candidate_name}\n"
            if candidate_data.get("email"):
                msg += f"*Email:* {candidate_data['email']}\n"
            if candidate_data.get("headline"):
                msg += f"*Cargo:* {candidate_data['headline']}\n"
            if candidate_data.get("location"):
                msg += f"*Local:* {candidate_data['location']}\n"
            if skills_text:
                msg += f"*Skills:* {skills_text}\n"
            if candidate_data.get("summary"):
                msg += f"*Resumo:* {candidate_data['summary']}\n"
            msg += f"\n*ID:* `{talent_id}`\n"
            if fit_analysis:
                msg += f"\n{fit_analysis}\n"
            if not added_to_job:
                msg += "\n_Não tem vaga ativa na conversa. Diz o nome da vaga ou manda o ID que eu vinculo!_"

            await _send(conv, slack, channel_id, msg)
            conversations.save(conv)

        except Exception as e:
            logger.exception("Erro ao processar %s: %s", file_info.get("name", "arquivo"), e)
            await _send(conv, slack, channel_id, f"Ops, deu um problema com `{file_info.get('name', 'arquivo')}`. Tenta mandar de novo?")

    # Save conversation state after processing all files
    conversations.save(conv)


# ==============================================================================
# ONBOARDING
# ==============================================================================

async def _handle_onboarding(app, user_id: str, channel_id: str, text: str):
    """Handle user onboarding — map Slack user to InHire user."""
    slack = app.state.slack
    user_mapping = app.state.user_mapping
    conversations = app.state.conversations

    conv = conversations.get_or_create(user_id, channel_id)
    onboarding_step = conv.get_context("onboarding_step", "start")

    if onboarding_step == "start":
        await slack.send_message(
            channel_id,
            "E aí! 👋 Sou o *Eli*, seu parceiro de recrutamento aqui no InHire.\n\n"
            "Pra gente começar, me diz: qual é o seu *e-mail no InHire*?",
        )
        conv.set_context("onboarding_step", "waiting_email")
        conversations.save(conv)
        return

    if onboarding_step == "waiting_email":
        email = text.strip().lower()

        # Basic email validation
        if "@" not in email or "." not in email:
            await slack.send_message(channel_id, "Hmm, isso não parece um e-mail. Tenta de novo?")
            return

        # Try to find user in InHire by searching requisitions/jobs for this email
        inhire_name = ""
        inhire_user_id = ""
        try:
            reqs = await app.state.inhire._request("GET", "/requisitions", params={"limit": "100"})
            for r in reqs:
                user_email_candidate = r.get("userName", "").lower()
                if email.split("@")[0] in user_email_candidate.lower().replace(" ", "."):
                    inhire_name = r.get("userName", "")
                    inhire_user_id = r.get("userId", "")
                    break
                # Also check approvers
                for approver in r.get("approvers", []):
                    if approver.get("email", "").lower() == email:
                        inhire_name = approver.get("name", "")
                        break
                if inhire_name:
                    break
        except Exception as e:
            logger.warning("Erro ao buscar usuário no InHire: %s", e)

        # Also try to get name from Slack
        if not inhire_name:
            try:
                slack_info = await slack.client.users_info(user=user_id)
                inhire_name = slack_info["user"].get("real_name", email.split("@")[0])
            except Exception:
                inhire_name = email.split("@")[0]

        # Register
        user_mapping.register_user(
            slack_user_id=user_id,
            inhire_email=email,
            inhire_name=inhire_name,
            inhire_user_id=inhire_user_id,
        )

        conv.set_context("onboarding_step", "done")
        conversations.save(conv)

        await slack.send_message(
            channel_id,
            f"Show, *{inhire_name}*! Prazer te conhecer 🎯\n\n"
            f"A partir de agora, fico de olho nas suas vagas e te aviso quando tiver novidade.\n\n"
            f"*O que eu sei fazer:*\n"
            f"• Abrir vagas (me manda o briefing que eu monto a JD)\n"
            f"• Monitorar candidatos e montar shortlists\n"
            f"• Mover candidatos e reprovar em lote com devolutiva\n"
            f"• Analisar perfis (cola aqui ou manda o CV)\n"
            f"• Gerar strings de busca pro LinkedIn\n"
            f"• Relatórios de SLA\n\n"
            f"Me chama quando precisar!",
        )
        return


# ==============================================================================
# STATE HANDLERS
# ==============================================================================

async def _handle_idle(conv, app, channel_id: str, text: str):
    """Detect user intent via Claude tool use and dispatch to the appropriate handler."""
    slack = app.state.slack
    claude = app.state.claude

    # Check if recruiter is returning after inactivity
    is_returning = conv.get_context("_is_returning", False)
    if is_returning:
        conv.set_context("_is_returning", None)  # Clear flag after use

    dynamic = _build_dynamic_context(conv, is_returning=is_returning)

    try:
        result = await claude.detect_intent(conv.messages, dynamic_context=dynamic)
    except Exception as e:
        logger.warning("Intent detection failed, falling back to free chat: %s", e)
        response = await claude.chat(conv.messages)
        await _send(conv, slack, channel_id, response)
        return

    tool = result.get("tool")
    tool_input = result.get("input", {})

    if tool is None:
        # No tool called — use text response directly
        await _send(conv, slack, channel_id, result.get("text", "Não entendi. Pode reformular?"))
        return

    # --- Layer 1: Fully functional tools ---

    if tool == "listar_vagas":
        await _list_jobs(conv, app, channel_id)

    elif tool == "criar_vaga":
        briefing = tool_input.get("briefing", text)
        conv.state = FlowState.COLLECTING_BRIEFING
        conv.set_context("briefing_parts", [briefing])

        # If briefing is rich enough (has salary/requirements/model), go straight to extraction
        briefing_lower = briefing.lower()
        has_salary = any(w in briefing_lower for w in ["salário", "salario", "budget", "faixa", "mil", "k "])
        has_requirements = any(w in briefing_lower for w in ["experiência", "experiencia", "stack", "requisito", "precisa ter"])
        has_basics = any(w in briefing_lower for w in ["remoto", "híbrido", "hibrido", "presencial", "clt", "pj"])

        if has_salary and has_requirements and has_basics:
            # Briefing completo — extrair direto
            await _send(conv, slack, channel_id, "Recebi o briefing! Analisando... ⏳")
            job_data = await claude.extract_job_data(briefing)
            conv.set_context("job_data", job_data)

            missing = job_data.get("missing_info", [])
            if missing and any(m for m in missing if m):
                missing_text = "\n".join(f"• {m}" for m in missing if m)
                await _send(
                    conv, slack, channel_id,
                    f"Entendi! Só faltam alguns detalhes:\n{missing_text}\n\n"
                    'Quer complementar ou digo "gerar" pra prosseguir mesmo assim?',
                )
            else:
                await _generate_and_post_draft(conv, app, channel_id, job_data)
        else:
            # Briefing incompleto — pedir mais info
            await _send(
                conv, slack, channel_id,
                "Bora abrir essa vaga! 🎯\n\n"
                "Me conta tudo que você sabe:\n"
                "• Cargo e área\n"
                "• Modelo (remoto/híbrido/presencial) e local\n"
                "• Faixa salarial e regime (CLT/PJ)\n"
                "• Requisitos técnicos\n"
                "• Urgência\n\n"
                'Pode mandar tudo de uma vez. Quando terminar, diz "pronto".',
            )

    elif tool == "ver_candidatos":
        job_id = _resolve_job_id(conv, tool_input)
        if job_id:
            await _check_candidates(conv, app, channel_id, job_id)
        else:
            await _send(
                conv, slack, channel_id,
                "Para qual vaga? Me passe o ID da vaga.\n"
                'Diga "vagas abertas" para ver a lista.',
            )

    elif tool == "gerar_shortlist":
        job_id = _resolve_job_id(conv, tool_input)
        if not job_id:
            await _send(
                conv, slack, channel_id,
                "Para qual vaga? Me passe o ID.\n"
                'Diga "vagas abertas" para ver a lista.',
            )
        else:
            # Load candidates if not already loaded for this job
            if not conv.get_context("shortlist_candidates"):
                await _check_candidates(conv, app, channel_id, job_id)
            if conv.get_context("shortlist_candidates"):
                await _build_shortlist(conv, app, channel_id)

    elif tool == "status_vaga":
        job_id = _resolve_job_id(conv, tool_input)
        if job_id:
            await _job_status_report(conv, app, channel_id, job_id)
        else:
            await _send(
                conv, slack, channel_id,
                "Para qual vaga? Me passe o ID.\n"
                'Diga "vagas abertas" para ver a lista.',
            )

    elif tool == "busca_linkedin":
        await _generate_linkedin_search(conv, app, channel_id)

    elif tool == "analisar_perfil":
        perfil = tool_input.get("perfil_texto") or text
        await _analyze_profile(conv, app, channel_id, perfil)

    elif tool == "mover_candidatos":
        job_id = _resolve_job_id(conv, tool_input)
        if not job_id:
            await _send(
                conv, slack, channel_id,
                "Para mover candidatos, preciso saber qual vaga. Me passe o ID.\n"
                'Diga "vagas abertas" para ver a lista.',
            )
        else:
            # Load candidates if needed
            if not conv.get_context("shortlist_candidates"):
                await _check_candidates(conv, app, channel_id, job_id)
            shortlist = conv.get_context("shortlist_candidates", [])
            if shortlist:
                await _build_shortlist(conv, app, channel_id)
            else:
                await _send(
                    conv, slack, channel_id,
                    "Nenhum candidato ativo pra mover nessa vaga.",
                )

    elif tool == "reprovar_candidatos":
        job_id = _resolve_job_id(conv, tool_input)
        if not job_id:
            await _send(
                conv, slack, channel_id,
                "Para reprovar candidatos, preciso saber qual vaga. Me passe o ID.\n"
                'Diga "vagas abertas" para ver a lista.',
            )
        else:
            # Load candidates if needed
            if not conv.get_context("all_applications"):
                await _check_candidates(conv, app, channel_id, job_id)
            all_apps = conv.get_context("all_applications", [])
            shortlist_ids = {c["id"] for c in conv.get_context("shortlist_candidates", [])}
            to_reject = [
                {"id": a.get("id"), "name": (a.get("talent", {}) or {}).get("name") or a.get("talentName", "Sem nome")}
                for a in all_apps
                if a.get("id") not in shortlist_ids
                and a.get("status") not in ("rejected", "dropped")
            ]
            if to_reject:
                conv.set_context("candidates_to_reject", to_reject)
                await _send_approval(
                    conv, slack, channel_id,
                    title="Reprovar candidatos?",
                    details=(
                        f"{len(to_reject)} candidatos não selecionados.\n"
                        "Ao aprovar, serão reprovados e receberão devolutiva."
                    ),
                    callback_id="rejection_approval",
                )
                conv.state = FlowState.WAITING_REJECTION_APPROVAL
            else:
                await _send(conv, slack, channel_id, "Não tem candidatos pra reprovar nessa vaga.")

    elif tool == "guia_inhire":
        topic = tool_input.get("topic", "").lower().strip()
        # Normalize topic names
        topic_map = {
            "divulgacao": "divulgacao", "divulgação": "divulgacao", "publicar": "divulgacao",
            "portais": "divulgacao", "linkedin": "divulgacao", "indeed": "divulgacao",
            "formulario": "formulario", "formulário": "formulario", "form": "formulario",
            "perguntas": "formulario", "inscrição": "formulario", "inscricao": "formulario",
            "triagem": "triagem", "screening": "triagem", "criterios": "triagem",
            "critérios": "triagem", "agente de triagem": "triagem",
            "scorecard": "scorecard", "kit": "scorecard", "entrevista": "scorecard",
            "kit de entrevista": "scorecard", "avaliação": "scorecard",
            "automacao": "automacoes", "automação": "automacoes", "automacoes": "automacoes",
            "automações": "automacoes", "gatilho": "automacoes", "teste": "automacoes",
        }
        resolved = topic_map.get(topic, topic)
        guide = _INHIRE_GUIDES.get(resolved)
        if guide:
            await _send(conv, slack, channel_id, guide)
        else:
            # Show all available guides
            topics = "\n".join(f"• *{k}*" for k in ["divulgação", "formulário", "triagem", "scorecard", "automações"])
            await _send(
                conv, slack, channel_id,
                f"Posso te guiar nessas configurações que ainda precisam ser feitas no InHire:\n\n{topics}\n\n"
                "Diz qual delas que eu te explico o passo a passo!",
            )

    elif tool == "agendar_entrevista":
        job_id = _resolve_job_id(conv, tool_input)
        if job_id:
            await _start_scheduling(conv, app, channel_id, text)
        else:
            await _send(
                conv, slack, channel_id,
                "Para agendar entrevista, preciso saber qual vaga. Me passe o ID.\n"
                'Diga "vagas abertas" para ver a lista.',
            )

    elif tool == "carta_oferta":
        job_id = _resolve_job_id(conv, tool_input)
        if job_id:
            await _start_offer_flow(conv, app, channel_id, text)
        else:
            await _send(
                conv, slack, channel_id,
                "Para criar carta oferta, preciso saber qual vaga. Me passe o ID.\n"
                'Diga "vagas abertas" para ver a lista.',
            )

    elif tool == "ver_memorias":
        await _show_memories(conv, app, channel_id)

    elif tool == "conversa_livre":
        response = await claude.chat(conv.messages)
        await _send(conv, slack, channel_id, response)

    # --- Layer 2: Not yet available ---
    elif tool in _NOT_AVAILABLE_MESSAGES:
        await _tool_not_available(conv, app, channel_id, tool)

    else:
        response = await claude.chat(conv.messages)
        await _send(conv, slack, channel_id, response)


async def _handle_waiting_approval(conv, app, channel_id: str, text: str):
    await _send(
        conv, app.state.slack, channel_id,
        "Tô esperando sua decisão ali em cima — ✅ Aprovar, ✏️ Ajustar ou ❌ Rejeitar.\n"
        'Ou diz "cancelar" pra recomeçar.',
    )


async def _handle_general(conv, app, channel_id: str, text: str):
    claude = app.state.claude
    response = await claude.chat(conv.messages)
    await _send(conv, app.state.slack, channel_id, response)


async def _handle_monitoring(conv, app, channel_id: str, text: str):
    """While monitoring candidates, allow all intents — monitoring is a background state."""
    await _handle_idle(conv, app, channel_id, text)


# ==============================================================================
# NOTE: The following handler functions have been extracted to routers/handlers/:
#   helpers.py      — _send, _send_approval, _resolve_job_id, _build_dynamic_context,
#                     _suggest_next_action, _tool_not_available, _NOT_AVAILABLE_MESSAGES, _INHIRE_GUIDES
#   job_creation.py — _handle_briefing, _generate_and_post_draft
#   candidates.py   — _start_screening_flow, _check_candidates, _build_shortlist,
#                     _move_approved_candidates, _reject_candidates
#   interviews.py   — _start_offer_flow, _handle_offer_input, _create_and_send_offer,
#                     _start_scheduling, _handle_scheduling_input
#   hunting.py      — _analyze_profile, _generate_linkedin_search, _job_status_report
# They are imported at the top of this file.
# ==============================================================================


# Kept inline: _show_memories, _list_jobs (small utilities used by _handle_idle)

async def _show_memories(conv, app, channel_id: str):
    """Show what Eli knows/remembers about the recruiter."""
    slack = app.state.slack
    learning = app.state.learning
    user_mapping = app.state.user_mapping
    user_id = conv.user_id

    parts = ["Aqui está o que aprendi trabalhando com você:\n"]

    # 1. User config
    user = user_mapping.get_user(user_id)
    if user:
        name = user.get("inhire_name", "")
        if name:
            parts.append(f"*Seu perfil:* {name} ({user.get('inhire_email', '')})")
        config_lines = []
        start = user.get("working_hours_start", 8)
        end = user.get("working_hours_end", 19)
        if start != 8 or end != 19:
            config_lines.append(f"Horário personalizado: {start}h-{end}h")
        max_msgs = user.get("max_proactive_messages", 3)
        if max_msgs != 3:
            config_lines.append(f"Limite de alertas diários: {max_msgs}")
        comms = user.get("comms_enabled", True)
        if not comms:
            config_lines.append("Comunicação automática com candidatos: *desativada*")
        if config_lines:
            parts.append("*Configurações:*\n" + "\n".join(f"• {l}" for l in config_lines))

    # 2. Active conversation context
    job_name = conv.get_context("current_job_name")
    if job_name:
        parts.append(f"*Vaga ativa na conversa:* {job_name}")
    shortlist = conv.get_context("shortlist_candidates")
    if shortlist:
        parts.append(f"*Shortlist carregado:* {len(shortlist)} candidatos")

    # 3. Decision patterns per job
    all_patterns = learning.get_all_patterns(user_id)
    if all_patterns:
        parts.append("\n*Padrões de decisão por vaga:*")
        for entry in all_patterns[:5]:
            p = entry["patterns"]
            job_id_short = entry["job_id"][:8]
            total = p.get("total_decisions", 0)
            rate = p.get("approval_rate", 0)
            line = f"• Vaga `{job_id_short}…` — {total} decisões, {rate:.0%} aprovação"
            reasons = p.get("top_rejection_reasons", [])
            if reasons:
                top = ", ".join(r[0] for r in reasons[:2])
                line += f" (reprovações: {top})"
            sal = p.get("rejected_salary_avg")
            if sal:
                line += f" | pretensão rejeitada média: R${sal:,.0f}"
            parts.append(line)
    else:
        parts.append("_Ainda não tenho padrões de decisão registrados — com o tempo, vou aprendendo seu estilo!_")

    # 4. Weekly insight (if available from mini-KAIROS)
    try:
        import redis as redis_lib
        from config import get_settings
        r = redis_lib.from_url(get_settings().redis_url, decode_responses=True)
        insight = r.get(f"inhire:insights:{user_id}")
        if insight:
            parts.append(f"\n*Resumo do seu estilo (última análise):*\n{insight}")
    except Exception:
        pass

    await _send(conv, slack, channel_id, "\n\n".join(parts))


async def _list_jobs(conv, app, channel_id: str):
    """List recent jobs from InHire."""
    slack = app.state.slack
    inhire = app.state.inhire

    try:
        # Use POST /jobs/paginated/lean (GET /jobs returns 502)
        data = await inhire._request("POST", "/jobs/paginated/lean", json={})
        jobs = data.get("results", []) if isinstance(data, dict) else data

        if not jobs:
            await _send(conv, slack, channel_id, "Não encontrei nenhuma vaga.")
            return

        msg = "📋 *Suas vagas:*\n\n"
        for j in jobs[:15]:
            name = j.get("name", "Sem nome")
            status = j.get("status", "?")
            jid = j.get("id", "")
            emoji = {"open": "🟢", "closed": "⚫", "frozen": "🔵", "pending": "🟡"}.get(status, "⚪")
            talents = j.get("talentsCount", 0)
            msg += f"{emoji} *{name}* — {talents} candidato(s)\nID: `{jid}`\n\n"

        await _send(conv, slack, channel_id, msg)
    except Exception as e:
        logger.exception("Erro ao listar vagas: %s", e)
        await _send(conv, slack, channel_id, "Ops, não consegui buscar as vagas agora. Tenta de novo em uns minutos?")


# APPROVAL HANDLER
# ==============================================================================

async def _handle_approval(app, user_id: str, channel_id: str, action_id: str, callback_id: str):
    try:
        slack = app.state.slack
        inhire = app.state.inhire
        conversations = app.state.conversations
        learning = app.state.learning

        conv = conversations.get_or_create(user_id, channel_id)

        # Record decision for learning
        job_id = conv.get_context("current_job_id", "")
        if job_id and callback_id in ("shortlist_approval", "rejection_approval"):
            learning.record_decision(
                recruiter_id=user_id,
                job_id=job_id,
                candidate_id=callback_id,
                decision=action_id,
                context={
                    "callback": callback_id,
                    "job_name": conv.get_context("current_job_name", ""),
                },
            )

        # --- Job draft approval ---
        if callback_id == "job_draft_approval":
            if action_id == "approve":
                await _send(conv, slack, channel_id, "Show! Criando a vaga no InHire... ⏳")
                job_data = conv.get_context("job_data", {})
                job_description = conv.get_context("job_description", "")
                title = job_data.get("title", "Nova Vaga")

                try:
                    # Build payload with all available fields
                    payload = {
                        "name": title,
                        "description": job_description,
                        "locationRequired": bool(job_data.get("location")),
                        "talentSuggestions": True,
                    }
                    if job_data.get("salary_range"):
                        sr = job_data["salary_range"]
                        if sr.get("min"):
                            payload["salaryMin"] = sr["min"]
                        if sr.get("max"):
                            payload["salaryMax"] = sr["max"]
                    if job_data.get("positions_count") and job_data["positions_count"] > 0:
                        payload["positions"] = [
                            {"reason": "expansion"}
                            for _ in range(job_data["positions_count"])
                        ]
                    result = await inhire.create_job(payload)
                    job_id = result.get("id")
                    conv.set_context("current_job_id", job_id)
                    conv.set_context("current_job_name", title)
                    conv.set_context("job_stages", result.get("stages", []))

                    stages = result.get("stages", [])
                    stage_info = "\n".join(
                        f"  {s['order']}. {s['name']}" for s in stages[:6]
                    ) if stages else "  (pipeline padrão)"

                    await _send(
                        conv, slack, channel_id,
                        f"✅ Pronto, vaga criada!\n"
                        f"*Nome:* {title}\n"
                        f"*ID:* `{job_id}`\n"
                        f"*Status:* {result.get('status')}\n"
                        f"*Pipeline:*\n{stage_info}\n\n"
                        "Vou ficar de olho nos candidatos e te aviso quando tiver gente boa!"
                        + _suggest_next_action(conv, total_candidates=0),
                    )
                    # Guide: what the recruiter still needs to do in InHire
                    await _send(
                        conv, slack, channel_id,
                        "⚠️ *Pra completar a vaga, você ainda precisa configurar no InHire:*\n\n"
                        f"• *Divulgação* — portais (LinkedIn, Indeed), visibilidade\n"
                        f"• *Formulário* — perguntas de inscrição, pretensão salarial\n"
                        f"• *Triagem IA* — critérios de avaliação automática\n\n"
                        f"Diz *divulgação*, *formulário* ou *triagem* que eu te explico o passo a passo!",
                    )
                    conv.state = FlowState.MONITORING_CANDIDATES
                except Exception as e:
                    logger.exception("Erro ao criar vaga: %s", e)
                    await _send(conv, slack, channel_id, f"❌ Erro ao criar vaga: {e}")

            elif action_id == "adjust":
                conv.state = FlowState.COLLECTING_BRIEFING
                await _send(conv, slack, channel_id, "Beleza! Me diz o que quer ajustar.")

            elif action_id == "reject":
                conv.state = FlowState.IDLE
                await _send(conv, slack, channel_id, "Tudo bem, rascunho descartado.")

        # --- Shortlist approval ---
        elif callback_id == "shortlist_approval":
            if action_id == "approve":
                await _move_approved_candidates(conv, app, channel_id)
            elif action_id == "adjust":
                conv.state = FlowState.MONITORING_CANDIDATES
                await _send(
                    conv, slack, channel_id,
                    "Beleza, me diz quais candidatos quer tirar ou adicionar no shortlist.",
                )
            elif action_id == "reject":
                conv.state = FlowState.MONITORING_CANDIDATES
                await _send(conv, slack, channel_id, "Tudo bem, shortlist descartado. Continuo de olho!")

        # --- Rejection approval ---
        elif callback_id == "rejection_approval":
            if action_id == "approve":
                await _reject_candidates(conv, app, channel_id)
            elif action_id in ("adjust", "reject"):
                conv.state = FlowState.IDLE
                await _send(conv, slack, channel_id, "Ok, reprovação cancelada.")

        # --- Offer letter approval ---
        elif callback_id == "offer_approval":
            if action_id == "approve":
                await _create_and_send_offer(conv, app, channel_id)
            elif action_id in ("adjust", "reject"):
                conv.state = FlowState.IDLE
                await _send(conv, slack, channel_id, "Ok, carta oferta cancelada.")

    except Exception as e:
        logger.exception("Erro ao processar aprovação: %s", e)
        await app.state.slack.send_message(channel_id, f"Erro: {e}")
