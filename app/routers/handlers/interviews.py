import json
import logging

from services.conversation import FlowState
from routers.handlers.helpers import _send, _send_approval, _talent_phone

logger = logging.getLogger("agente-inhire.slack-router")


async def _send_interview_reminder(app, channel_id: str, candidate_name: str, job_name: str, datetime_str: str):
    """Send interview reminder to recruiter via Slack."""
    slack = app.state.slack
    try:
        await slack.post_message(
            channel_id,
            f"⏰ *Lembrete:* Entrevista com *{candidate_name}* para a vaga *{job_name}* "
            f"começa em 2 horas ({datetime_str}).\n\n"
            f"Tudo pronto? Se precisar remarcar, é só me avisar!",
        )
    except Exception as e:
        logger.warning("Falha ao enviar lembrete: %s", e)


def _talent_name(a: dict) -> str:
    """Extract talent name from job-talent record (handles nested talent object)."""
    return (
        a.get("talentName")
        or (a.get("talent") or {}).get("name")
        or a.get("candidateName")
        or a.get("name")
        or "Sem nome"
    )


def _talent_email(a: dict) -> str:
    """Extract talent email from job-talent record."""
    return (
        a.get("talentEmail")
        or (a.get("talent") or {}).get("email")
        or a.get("email")
        or ""
    )


def _talent_stage(a: dict) -> str:
    """Extract stage name from job-talent record."""
    return (
        a.get("stageName")
        or (a.get("stage") or {}).get("name")
        or ""
    )


async def _start_offer_flow(conv, app, channel_id: str, text: str):
    """Start offer letter creation flow."""
    slack = app.state.slack
    inhire = app.state.inhire

    job_id = conv.get_context("current_job_id")
    if not job_id:
        await _send(
            conv, slack, channel_id,
            "Para criar uma carta oferta, preciso saber qual vaga. Me passe o ID da vaga.",
        )
        return

    job_name = conv.get_context("current_job_name", "")

    try:
        # Get available templates
        try:
            templates = await inhire.list_offer_templates()
            conv.set_context("offer_templates", templates)
        except Exception:
            templates = []

        # Get candidates in offer stage
        applications = await inhire.list_job_talents(job_id)
        # Filter candidates that could receive an offer
        eligible = [
            a for a in applications
            if a.get("status") not in ("rejected", "dropped")
        ]

        if not eligible:
            await _send(conv, slack, channel_id, "Nenhum candidato elegível para carta oferta nesta vaga.")
            return

        conv.set_context("offer_candidates", eligible)

        msg = f"📝 *Carta Oferta — {job_name}*\n\nCandidatos elegíveis:\n\n"
        for i, a in enumerate(eligible[:10], 1):
            name = _talent_name(a)
            stage = _talent_stage(a)
            msg += f"*{i}.* {name} — Etapa: {stage}\n"

        if templates:
            msg += "\n*Templates disponíveis:*\n"
            for i, t in enumerate(templates[:5], 1):
                msg += f"  {i}. {t.get('name', 'Sem nome')}\n"

        msg += (
            "\nMe diga:\n"
            "• *Número* do candidato\n"
            "• *Salário* oferecido\n"
            "• *Email do aprovador* (quem precisa aprovar antes de enviar)\n"
            "• *Data de início* prevista\n\n"
            "Exemplo: `1 salário 18000 aprovador joao@empresa.com início 01/06/2025`\n"
            "Ou me passe as informações de forma livre."
        )

        await _send(conv, slack, channel_id, msg)
        conv.state = FlowState.CREATING_OFFER

    except Exception as e:
        logger.exception("Erro ao iniciar carta oferta: %s", e)
        await _send(conv, slack, channel_id, f"❌ Erro ao carregar dados para carta oferta: {e}")


async def _handle_offer_input(conv, app, channel_id: str, text: str):
    """Handle user input during offer letter creation."""
    slack = app.state.slack
    inhire = app.state.inhire
    claude = app.state.claude

    candidates = conv.get_context("offer_candidates", [])
    templates = conv.get_context("offer_templates", [])

    system = """Extraia do texto do usuário:
1. Qual candidato (número ou nome)
2. Salário oferecido
3. Email do aprovador
4. Data de início (se mencionada)

Retorne JSON puro:
{"candidate_index": number, "salary": number, "approver_email": "email", "approver_name": "nome se mencionado", "start_date": "DD/MM/YYYY ou vazio se não mencionado"}

Se faltar algo obrigatório (candidato, salário ou aprovador), retorne {"error": "o que falta"}"""

    candidate_list = json.dumps([
        {"index": i+1, "name": _talent_name(a)}
        for i, a in enumerate(candidates[:10])
    ], ensure_ascii=False)

    raw = await claude.chat(
        messages=[{"role": "user", "content": f"Candidatos: {candidate_list}\n\nUsuário disse: {text}"}],
        system=system,
    )

    try:
        parsed_text = raw.strip()
        if parsed_text.startswith("```"):
            parsed_text = parsed_text.split("\n", 1)[1].rsplit("```", 1)[0]
        parsed = json.loads(parsed_text)
    except Exception:
        await _send(
            conv, slack, channel_id,
            "Não entendi. Me diga o número do candidato, salário e email do aprovador.\n"
            "Exemplo: `1 salário 18000 aprovador joao@empresa.com`",
        )
        return

    if parsed.get("error"):
        await _send(conv, slack, channel_id, f"Falta informação: {parsed['error']}")
        return

    # Find candidate
    idx = parsed.get("candidate_index", 0)
    if not idx or idx < 1 or idx > len(candidates):
        await _send(conv, slack, channel_id, "Número do candidato inválido. Tente novamente.")
        return

    candidate = candidates[idx - 1]
    candidate_name = _talent_name(candidate)
    candidate_email = _talent_email(candidate)
    salary = parsed.get("salary", "A definir")
    approver_email = parsed.get("approver_email", "")
    approver_name = parsed.get("approver_name", approver_email.split("@")[0] if approver_email else "")
    job_name = conv.get_context("current_job_name", "")

    # Store offer details
    offer_details = {
        "candidate": candidate,
        "candidate_name": candidate_name,
        "candidate_email": candidate_email,
        "salary": salary,
        "approver_email": approver_email,
        "approver_name": approver_name,
        "start_date": parsed.get("start_date", ""),
        "raw_input": text,
    }
    conv.set_context("offer_details", offer_details)

    # Post for approval (human pause point)
    await _send_approval(
        conv, slack, channel_id,
        title=f"Carta Oferta — {candidate_name}",
        details=(
            f"*Vaga:* {job_name}\n"
            f"*Candidato:* {candidate_name}\n"
            f"*Email:* {candidate_email or 'não informado'}\n"
            f"*Salário:* R$ {salary:,.0f}\n" if isinstance(salary, (int, float)) else
            f"*Vaga:* {job_name}\n"
            f"*Candidato:* {candidate_name}\n"
            f"*Email:* {candidate_email or 'não informado'}\n"
            f"*Salário:* {salary}\n"
            f"*Aprovador:* {approver_name} ({approver_email})\n\n"
            f"Ao aprovar, a carta oferta será criada e enviada para aprovação."
        ),
        callback_id="offer_approval",
    )
    conv.state = FlowState.WAITING_OFFER_APPROVAL


async def _create_and_send_offer(conv, app, channel_id: str):
    """Create offer letter in InHire after approval."""
    slack = app.state.slack
    inhire = app.state.inhire

    details = conv.get_context("offer_details", {})
    templates = conv.get_context("offer_templates", [])
    job_name = conv.get_context("current_job_name", "")

    candidate = details.get("candidate", {})
    candidate_name = details.get("candidate_name", "Candidato")

    await _send(conv, slack, channel_id, "Criando carta oferta... ⏳")

    try:
        talent_id = candidate.get("talentId") or candidate.get("id", "")
        job_id = conv.get_context("current_job_id", "")

        payload = {
            "name": f"Oferta - {candidate_name} - {job_name}",
            "jobTalentId": f"{job_id}*{talent_id}",
            "talent": {
                "id": talent_id,
                "email": details.get("candidate_email", ""),
            },
            "approvals": [
                {
                    "email": details.get("approver_email", ""),
                    "name": details.get("approver_name", ""),
                }
            ],
            "language": "pt-BR",
        }

        # Select template — match by name or number from user input
        if templates:
            selected_template = templates[0]  # default to first
            if len(templates) > 1:
                text_lower = (details.get("candidate_name", "") or "").lower()
                # Use original user text stored during offer input if available
                raw_input = details.get("raw_input", "").lower()
                search_text = raw_input or text_lower
                for i, t in enumerate(templates):
                    t_name = t.get("name", "").lower()
                    if t_name and t_name in search_text:
                        selected_template = t
                        break
                    # Also match by number ("template 2", "modelo 2")
                    if str(i + 1) in search_text.split():
                        selected_template = t
                        break

            payload["templateId"] = selected_template.get("id", "")
            payload["templateVariableValues"] = {
                "salario": str(details.get("salary", "")),
                "nomeCargo": job_name,
                "nomeCandidato": candidate_name,
                "dataInicio": details.get("start_date", ""),
            }

        result = await inhire.create_offer_letter(payload)
        offer_id = result.get("id", "")
        status = result.get("status", "")

        # Get document URL for preview
        doc_url = ""
        if offer_id:
            try:
                doc_info = await inhire.get_offer_document_url(offer_id)
                doc_url = doc_info.get("url", "") if isinstance(doc_info, dict) else str(doc_info or "")
            except Exception:
                pass

        doc_line = f"\n📄 <{doc_url}|Ver documento da oferta>" if doc_url else ""

        await _send(
            conv, slack, channel_id,
            f"✅ Carta oferta criada!\n\n"
            f"*Candidato:* {candidate_name}\n"
            f"*ID:* `{offer_id}`\n"
            f"*Status:* {status}"
            f"{doc_line}\n\n"
            f"O aprovador receberá uma notificação para revisar e assinar.\n"
            f"Após aprovação, a carta será enviada ao candidato automaticamente.",
        )

    except Exception as e:
        logger.exception("Erro ao criar carta oferta: %s", e)
        error_msg = str(e)
        if "404" in error_msg and "Template" in error_msg:
            await _send(
                conv, slack, channel_id,
                "❌ Template de carta oferta não encontrado.\n"
                "Verifique se há templates configurados no InHire.",
            )
        else:
            await _send(conv, slack, channel_id, f"❌ Erro ao criar carta oferta: {e}")

    conv.state = FlowState.IDLE


async def _start_scheduling(conv, app, channel_id: str, text: str):
    """Start interview scheduling flow."""
    slack = app.state.slack
    inhire = app.state.inhire

    job_id = conv.get_context("current_job_id")

    if not job_id:
        await _send(
            conv, slack, channel_id,
            "Para agendar entrevistas, preciso saber qual vaga. "
            "Crie uma vaga primeiro ou me passe o ID.",
        )
        return

    job_name = conv.get_context("current_job_name", "")

    # Get applications for this job
    try:
        applications = await inhire.list_job_talents(job_id)
        if not applications:
            await _send(conv, slack, channel_id, "Nenhum candidato nesta vaga para agendar entrevista.")
            return

        # Filter active candidates (not rejected)
        active = [
            a for a in applications
            if a.get("status") not in ("rejected", "dropped")
        ]

        if not active:
            await _send(conv, slack, channel_id, "Nenhum candidato ativo para agendar.")
            return

        conv.set_context("schedulable_candidates", active)

        # List candidates available for scheduling
        msg = f"📅 *Agendar entrevista — {job_name}*\n\nCandidatos disponíveis:\n\n"
        for i, a in enumerate(active[:15], 1):
            name = _talent_name(a)
            stage = _talent_stage(a)
            score = a.get("screening", {}).get("score", "N/A")
            msg += f"*{i}.* {name} — Etapa: {stage} | Score: {score}\n"

        msg += (
            "\nMe diga:\n"
            "• O *número* do candidato (ex: `1`)\n"
            "• Ou *nome* do candidato\n"
            "• E a *data/hora* desejada (ex: `amanhã às 14h`, `05/04 10:00`)\n\n"
            "Exemplo: `1 amanhã às 14h`"
        )

        await _send(conv, slack, channel_id, msg)
        conv.state = FlowState.SCHEDULING_INTERVIEW

    except Exception as e:
        logger.exception("Erro ao iniciar agendamento: %s", e)
        await _send(conv, slack, channel_id, f"❌ Erro: {e}")


async def _handle_scheduling_input(conv, app, channel_id: str, text: str):
    """Handle user input during scheduling flow."""
    slack = app.state.slack
    inhire = app.state.inhire
    claude = app.state.claude

    candidates = conv.get_context("schedulable_candidates", [])

    if not candidates:
        conv.state = FlowState.IDLE
        await _send(conv, slack, channel_id, "Erro: lista de candidatos perdida. Diga 'agendar' novamente.")
        return

    # Use Claude to extract candidate selection and datetime from natural language
    system = """Extraia do texto do usuário:
1. Qual candidato ele quer agendar (número ou nome)
2. Data e hora desejada (início)
3. Duração estimada (default: 1 hora)

Retorne JSON puro:
{"candidate_index": number ou null, "candidate_name": "string" ou null, "datetime": "YYYY-MM-DDTHH:MM:SS", "end_datetime": "YYYY-MM-DDTHH:MM:SS", "datetime_readable": "texto legível", "duration_minutes": 60}

Se não conseguir identificar, retorne {"error": "o que falta"}"""

    candidate_list = json.dumps([
        {"index": i+1, "name": _talent_name(a)}
        for i, a in enumerate(candidates[:15])
    ], ensure_ascii=False)

    raw = await claude.chat(
        messages=[{"role": "user", "content": f"Candidatos: {candidate_list}\n\nUsuário disse: {text}"}],
        system=system,
    )

    try:
        parsed_text = raw.strip()
        if parsed_text.startswith("```"):
            parsed_text = parsed_text.split("\n", 1)[1].rsplit("```", 1)[0]
        parsed = json.loads(parsed_text)
    except Exception:
        await _send(
            conv, slack, channel_id,
            "Não entendi. Me diga o número do candidato e a data/hora.\n"
            "Exemplo: `1 quinta às 14h`",
        )
        return

    if parsed.get("error"):
        await _send(conv, slack, channel_id, f"Falta informação: {parsed['error']}")
        return

    # Find candidate
    candidate = None
    idx = parsed.get("candidate_index")
    if idx and 1 <= idx <= len(candidates):
        candidate = candidates[idx - 1]
    elif parsed.get("candidate_name"):
        name_lower = parsed["candidate_name"].lower()
        for c in candidates:
            cname = _talent_name(c).lower()
            if name_lower in cname:
                candidate = c
                break

    if not candidate:
        await _send(conv, slack, channel_id, "Não encontrei esse candidato. Tente novamente com o número da lista.")
        return

    candidate_name = _talent_name(candidate)
    dt_readable = parsed.get("datetime_readable", parsed.get("datetime", ""))
    job_name = conv.get_context("current_job_name", "")

    # Build appointment payload (provider: manual — no calendar integration needed)
    from datetime import datetime as dt_cls, timedelta
    start_dt = parsed.get("datetime", "")
    end_dt = parsed.get("end_datetime", "")
    duration = parsed.get("duration_minutes", 60)

    # Calculate end_datetime if missing (default: start + 1 hour)
    if start_dt and not end_dt:
        try:
            clean = start_dt.replace("Z", "").replace(".000", "").split("+")[0]
            start_obj = dt_cls.fromisoformat(clean)
            end_obj = start_obj + timedelta(minutes=duration or 60)
            end_dt = end_obj.isoformat()
        except Exception:
            end_dt = start_dt  # Fallback: same as start

    # Ensure ISO format with Z suffix
    if start_dt and not start_dt.endswith("Z"):
        start_dt = start_dt.replace("+00:00", "") + ".000Z"
    if end_dt and not end_dt.endswith("Z"):
        end_dt = end_dt.replace("+00:00", "") + ".000Z"

    candidate_email = _talent_email(candidate)
    appointment_payload = {
        "name": f"Entrevista - {candidate_name} - {job_name}",
        "startDateTime": start_dt,
        "endDateTime": end_dt,
        "userEmail": conv.get_context("recruiter_email", "") or (app.state.user_mapping.get_user(conv.user_id) or {}).get("inhire_email", ""),
        "guests": [
            {"email": candidate_email, "name": candidate_name, "type": "talent"},
        ],
        "hasCallLink": False,
        "provider": "manual",
    }

    try:
        appointment = await inhire.create_appointment(
            candidate.get("id"),
            appointment_payload,
        )
        appt_id = appointment.get("id", "")
        await _send(
            conv, slack, channel_id,
            f"✅ Entrevista agendada!\n\n"
            f"*Candidato:* {candidate_name}\n"
            f"*Vaga:* {job_name}\n"
            f"*Data:* {dt_readable}\n"
            f"*ID:* `{appt_id}`",
        )

        # Schedule reminder 2 hours before interview
        try:
            from datetime import datetime as dt_cls, timedelta, timezone

            start_str = appointment_payload.get("startDateTime", "")
            if start_str:
                clean = start_str.replace("Z", "").replace(".000", "").split("+")[0]
                start_dt = dt_cls.fromisoformat(clean).replace(tzinfo=timezone.utc)
                reminder_time = start_dt - timedelta(hours=2)

                if reminder_time > dt_cls.now(timezone.utc):
                    scheduler = app.state.scheduler
                    scheduler.add_job(
                        _send_interview_reminder,
                        trigger="date",
                        run_date=reminder_time,
                        args=[app, channel_id, candidate_name, job_name, start_str],
                        id=f"reminder_{appt_id}",
                        replace_existing=True,
                    )
                    logger.info("Lembrete agendado para %s", reminder_time)
        except Exception as reminder_err:
            logger.warning("Não agendou lembrete: %s", reminder_err)

        # Offer WhatsApp confirmation
        phone = _talent_phone(candidate)
        user_data = app.state.user_mapping.get_user(conv.user_id) or {}
        if phone and user_data.get("comms_enabled", True):
            claude = app.state.claude
            msg_text = await claude.generate_whatsapp_message(
                intent=f"Confirmar entrevista agendada para {dt_readable}",
                candidate_name=candidate_name,
                job_name=job_name,
            )
            conv.set_context("whatsapp_interview_pending", {
                "phone": phone,
                "message": msg_text,
                "candidate_name": candidate_name,
            })
            await _send_approval(
                conv, slack, channel_id,
                title="Confirmar por WhatsApp?",
                details=f"📱 *Para:* {candidate_name}\n\n{msg_text}",
                callback_id="whatsapp_interview_approval",
            )
            return

        conv.state = FlowState.IDLE

    except Exception as e:
        logger.exception("Erro ao agendar entrevista: %s", e)
        await _send(conv, slack, channel_id, f"❌ Erro ao agendar: {e}")
        conv.state = FlowState.MONITORING_CANDIDATES
