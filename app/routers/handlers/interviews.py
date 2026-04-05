import json
import logging

from services.conversation import FlowState
from routers.handlers.helpers import _send, _send_approval

logger = logging.getLogger("agente-inhire.slack-router")


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
            name = a.get("talentName") or a.get("candidateName", "Sem nome")
            stage = a.get("stageName", "")
            msg += f"*{i}.* {name} — Etapa: {stage}\n"

        if templates:
            msg += "\n*Templates disponíveis:*\n"
            for i, t in enumerate(templates[:5], 1):
                msg += f"  {i}. {t.get('name', 'Sem nome')}\n"

        msg += (
            "\nMe diga:\n"
            "• *Número* do candidato\n"
            "• *Salário* oferecido\n"
            "• *Email do aprovador* (quem precisa aprovar antes de enviar)\n\n"
            "Exemplo: `1 salário 18000 aprovador joao@empresa.com`\n"
            "Ou me passe as informações de forma livre."
        )

        await _send(conv, slack, channel_id, msg)
        conv.state = FlowState.CREATING_OFFER

    except Exception as e:
        logger.exception("Erro ao iniciar carta oferta: %s", e)
        if "403" in str(e) or "Forbidden" in str(e):
            await _send(
                conv, slack, channel_id,
                "⚠️ Carta oferta ainda não está habilitada para este tenant.\n"
                "O time do InHire precisa fazer um deploy para liberar. "
                "Já solicitamos — assim que estiver pronto, funciona automaticamente.",
            )
        else:
            await _send(conv, slack, channel_id, f"❌ Erro: {e}")


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

Retorne JSON puro:
{"candidate_index": number, "salary": number, "approver_email": "email", "approver_name": "nome se mencionado"}

Se faltar algo, retorne {"error": "o que falta"}"""

    candidate_list = json.dumps([
        {"index": i+1, "name": a.get("talentName") or a.get("candidateName", "")}
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
    candidate_name = candidate.get("talentName") or candidate.get("candidateName", "Candidato")
    candidate_email = candidate.get("talentEmail") or candidate.get("email", "")
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

        # Use first template if available
        if templates:
            payload["templateId"] = templates[0].get("id", "")
            payload["templateVariableValues"] = {
                "salario": str(details.get("salary", "")),
                "nomeCargo": job_name,
                "nomeCandidato": candidate_name,
                "dataInicio": "",
            }

        result = await inhire.create_offer_letter(payload)
        offer_id = result.get("id", "")
        status = result.get("status", "")

        await _send(
            conv, slack, channel_id,
            f"✅ Carta oferta criada!\n\n"
            f"*Candidato:* {candidate_name}\n"
            f"*ID:* `{offer_id}`\n"
            f"*Status:* {status}\n\n"
            f"O aprovador receberá uma notificação para revisar e assinar.\n"
            f"Após aprovação, a carta será enviada ao candidato automaticamente.",
        )

    except Exception as e:
        error_msg = str(e)
        if "403" in error_msg or "Forbidden" in error_msg:
            await _send(
                conv, slack, channel_id,
                "⚠️ Carta oferta ainda não está habilitada para este tenant.\n"
                "Aguardando deploy do time InHire.",
            )
        else:
            logger.exception("Erro ao criar carta oferta: %s", e)
            await _send(conv, slack, channel_id, f"❌ Erro: {e}")

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
            name = a.get("talentName") or a.get("candidateName", "Sem nome")
            stage = a.get("stageName", "")
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
2. Data e hora desejada

Retorne JSON puro:
{"candidate_index": number ou null, "candidate_name": "string" ou null, "datetime": "YYYY-MM-DDTHH:MM:SS", "datetime_readable": "texto legível"}

Se não conseguir identificar, retorne {"error": "o que falta"}"""

    candidate_list = json.dumps([
        {"index": i+1, "name": a.get("talentName") or a.get("candidateName", "")}
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
            cname = (c.get("talentName") or c.get("candidateName", "")).lower()
            if name_lower in cname:
                candidate = c
                break

    if not candidate:
        await _send(conv, slack, channel_id, "Não encontrei esse candidato. Tente novamente com o número da lista.")
        return

    candidate_name = candidate.get("talentName") or candidate.get("candidateName", "Candidato")
    dt_readable = parsed.get("datetime_readable", parsed.get("datetime", ""))
    job_name = conv.get_context("current_job_name", "")

    # Try to create appointment
    try:
        appointment = await inhire.create_appointment(
            candidate.get("id"),
            {
                "datetime": parsed.get("datetime"),
                "type": "interview",
                "provider": "google",
            },
        )
        await _send(
            conv, slack, channel_id,
            f"✅ Entrevista agendada!\n\n"
            f"*Candidato:* {candidate_name}\n"
            f"*Vaga:* {job_name}\n"
            f"*Data:* {dt_readable}\n"
            f"*Convite:* Enviado via Google Calendar\n\n"
            f"O candidato receberá o link da entrevista automaticamente.",
        )
        conv.state = FlowState.IDLE

    except Exception as e:
        error_msg = str(e)
        if "403" in error_msg or "Forbidden" in error_msg:
            await _send(
                conv, slack, channel_id,
                f"⚠️ O agendamento via API ainda não está liberado para este tenant.\n\n"
                f"*Candidato:* {candidate_name}\n"
                f"*Data sugerida:* {dt_readable}\n\n"
                f"Por enquanto, agende manualmente no InHire. "
                f"Estamos trabalhando com o time do InHire para liberar essa funcionalidade.",
            )
        else:
            await _send(conv, slack, channel_id, f"❌ Erro ao agendar: {e}")

        conv.state = FlowState.MONITORING_CANDIDATES
