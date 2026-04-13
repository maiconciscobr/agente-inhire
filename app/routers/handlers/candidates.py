import logging

from services.conversation import FlowState
from routers.handlers.helpers import _send, _send_approval, _suggest_next_action, _talent_phone

logger = logging.getLogger("agente-inhire.slack-router")


async def _start_screening_flow(conv, app, channel_id: str, text: str):
    """Start screening flow — list jobs or check specific job."""
    slack = app.state.slack
    inhire = app.state.inhire

    # Check if user mentioned a specific job ID
    job_id = conv.get_context("current_job_id")

    if not job_id:
        # Try to find job ID in text (UUID pattern)
        import re
        uuid_match = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', text)
        if uuid_match:
            job_id = uuid_match.group()

    if not job_id:
        await _send(
            conv, slack, channel_id,
            "Para qual vaga? Me passe o ID da vaga.\n"
            "Posso te mostrar suas vagas se quiser.",
        )
        return

    await _check_candidates(conv, app, channel_id, job_id)


async def _check_candidates(conv, app, channel_id: str, job_id: str):
    """Check candidates for a specific job and report screening distribution."""
    slack = app.state.slack
    inhire = app.state.inhire

    await _send(conv, slack, channel_id, "Deixa eu ver os candidatos... ⏳")

    try:
        # Get job info
        job = await inhire.get_job(job_id)
        job_name = job.get("name", "Vaga")
        stages = job.get("stages", [])

        conv.set_context("current_job_id", job_id)
        conv.set_context("current_job_name", job_name)
        conv.set_context("job_stages", stages)

        # Get applications
        applications = await inhire.list_job_talents(job_id)

        if not applications:
            await _send(
                conv, slack, channel_id,
                f"📋 *{job_name}*\nAinda não chegou ninguém. "
                "Fica tranquilo que eu aviso assim que aparecer!"
                + _suggest_next_action(conv, total_candidates=0),
            )
            conv.state = FlowState.MONITORING_CANDIDATES
            return

        # Categorize by screening status
        high_fit = []
        medium_fit = []
        low_fit = []
        no_score = []

        for a in applications:
            screening = a.get("screening", {}) or {}
            status = screening.get("status", "")
            talent = a.get("talent", {}) or {}
            candidate = {
                "id": a.get("id"),
                "talentId": a.get("talentId") or talent.get("id", ""),
                "name": talent.get("name") or a.get("talentName") or a.get("candidateName", "Sem nome"),
                "score": screening.get("score", "N/A"),
                "status": status,
                "stage": a.get("stage", {}).get("name", "") if isinstance(a.get("stage"), dict) else a.get("stageName", ""),
                "linkedin": talent.get("linkedinUsername", ""),
                "location": talent.get("location", ""),
            }
            if status == "pre-aproved":
                high_fit.append(candidate)
            elif status == "need-aproval":
                medium_fit.append(candidate)
            elif status == "pre-rejected":
                low_fit.append(candidate)
            else:
                no_score.append(candidate)

        # Build report
        total = len(applications)
        report = (
            f"📊 *Triagem — {job_name}*\n"
            f"Total: {total} candidatos\n\n"
            f"🟢 Alto fit: {len(high_fit)}\n"
            f"🟡 Médio fit: {len(medium_fit)}\n"
            f"🔴 Baixo fit: {len(low_fit)}\n"
            f"⚪ Sem score: {len(no_score)}\n"
        )

        # Top candidates detail
        if high_fit:
            report += "\n*Top candidatos (Alto fit):*\n"
            for c in high_fit[:10]:
                report += f"• *{c['name']}* — Score: {c['score']}\n"

        # Add next best action suggestion to report
        report += _suggest_next_action(
            conv,
            total_candidates=total,
            high_fit=len(high_fit),
        )
        await _send(conv, slack, channel_id, report)

        # Build shortlist: scored candidates first, then unscored active ones
        shortlist = high_fit + medium_fit[:5]  # High fit + top medium
        if not shortlist and no_score:
            # No screening scores available — include all active unscored candidates
            shortlist = no_score
        if shortlist:
            conv.set_context("shortlist_candidates", shortlist)
            conv.set_context("all_applications", applications)
            conv.state = FlowState.MONITORING_CANDIDATES
        else:
            conv.state = FlowState.MONITORING_CANDIDATES

    except Exception as e:
        logger.exception("Erro ao buscar candidatos: %s", e)
        await _send(conv, slack, channel_id, f"❌ Erro ao buscar candidatos: {e}")


async def _build_shortlist(conv, app, channel_id: str):
    """Build comparative shortlist using Claude and post for approval."""
    slack = app.state.slack
    claude = app.state.claude

    shortlist = conv.get_context("shortlist_candidates", [])
    job_name = conv.get_context("current_job_name", "")

    if not shortlist:
        await _send(conv, slack, channel_id, "Ainda não tem candidatos suficientes pra montar o shortlist.")
        return

    await _send(conv, slack, channel_id, "Montando o comparativo... ⏳")

    summary = await claude.summarize_candidates(shortlist, job_name)
    conv.set_context("shortlist_summary", summary)

    # Find next stage (after "Inscritos")
    stages = conv.get_context("job_stages", [])
    next_stage_id = None
    for i, s in enumerate(stages):
        if s.get("type") in ("applied", "listed"):
            if i + 1 < len(stages):
                next_stage_id = stages[i + 1]["id"]
                conv.set_context("next_stage_id", next_stage_id)
                conv.set_context("next_stage_name", stages[i + 1]["name"])
            break

    await _send(conv, slack, channel_id, summary)

    next_stage_name = conv.get_context("next_stage_name", "próxima etapa")
    await _send_approval(
        conv, slack, channel_id,
        title=f"Shortlist — {job_name}",
        details=(
            f"{len(shortlist)} candidatos selecionados.\n"
            f"Ao aprovar, serão movidos para: *{next_stage_name}*"
        ),
        callback_id="shortlist_approval",
    )
    conv.state = FlowState.WAITING_SHORTLIST_APPROVAL


async def _move_approved_candidates(conv, app, channel_id: str):
    """Move approved shortlist candidates to next stage using batch endpoint."""
    slack = app.state.slack
    inhire = app.state.inhire

    shortlist = conv.get_context("shortlist_candidates", [])
    next_stage_id = conv.get_context("next_stage_id")

    if not shortlist or not next_stage_id:
        await _send(conv, slack, channel_id, "Ops, não tenho candidatos ou etapa destino definida pra mover.")
        return

    next_stage_name = conv.get_context("next_stage_name", "próxima etapa")
    await _send(
        conv, slack, channel_id,
        f"Movendo {len(shortlist)} candidatos para *{next_stage_name}*... ⏳",
    )

    # Try batch first, fall back to individual
    ids = [c["id"] for c in shortlist]
    try:
        await inhire.move_candidates_batch(next_stage_id, ids)
        moved = len(ids)
        errors = []
    except Exception as batch_err:
        logger.warning("Batch move falhou (%s), tentando individual...", batch_err)
        moved = 0
        errors = []
        for c in shortlist:
            try:
                await inhire.move_candidate(c["id"], next_stage_id)
                moved += 1
            except Exception as e:
                errors.append(f"{c['name']}: {e}")
                logger.error("Erro ao mover %s: %s", c["id"], e)

    result_msg = f"✅ {moved}/{len(shortlist)} candidatos movidos para *{next_stage_name}*!"
    if errors:
        result_msg += "\n⚠️ Erros:\n" + "\n".join(f"• {e}" for e in errors[:5])

    await _send(conv, slack, channel_id, result_msg)

    # Offer to reject remaining candidates
    all_apps = conv.get_context("all_applications", [])
    shortlist_ids = {c["id"] for c in shortlist}
    remaining = [
        {"id": a.get("id"), "name": (a.get("talent", {}) or {}).get("name") or a.get("talentName", "Sem nome")}
        for a in all_apps
        if a.get("id") not in shortlist_ids
        and a.get("status") not in ("rejected", "dropped")
    ]

    if remaining:
        conv.set_context("candidates_to_reject", remaining)
        await _send_approval(
            conv, slack, channel_id,
            title="Reprovar candidatos restantes?",
            details=(
                f"{len(remaining)} candidatos não selecionados.\n"
                "Ao aprovar, serão reprovados e receberão devolutiva."
            ),
            callback_id="rejection_approval",
        )
        conv.state = FlowState.WAITING_REJECTION_APPROVAL
    else:
        conv.state = FlowState.IDLE


async def _reject_candidates(conv, app, channel_id: str):
    """Reject non-shortlisted candidates with feedback."""
    slack = app.state.slack
    inhire = app.state.inhire
    claude = app.state.claude

    to_reject = conv.get_context("candidates_to_reject", [])
    job_name = conv.get_context("current_job_name", "")

    if not to_reject:
        await _send(conv, slack, channel_id, "Não tem ninguém pra reprovar.")
        conv.state = FlowState.IDLE
        return

    await _send(conv, slack, channel_id, f"Reprovando {len(to_reject)} candidatos... ⏳")

    # Generate rejection message (goes as comment, not reason — reason is enum)
    rejection_msg = await claude.generate_rejection_message(job_name)

    result = await inhire.bulk_reject(
        [c["id"] for c in to_reject],
        reason="other",
        comment=rejection_msg,
    )

    next_stage = conv.get_context("next_stage_name", "")
    tip = ""
    if next_stage:
        tip = f"\n\n💡 Agora o foco são os candidatos em *{next_stage}*. Quando tiver retorno das entrevistas, me avisa!"

    await _send(
        conv, slack, channel_id,
        f"Feito! {result['rejected']}/{result['total']} reprovados e devolutiva enviada.\n"
        f"> {rejection_msg[:300]}"
        + tip,
    )

    # Offer WhatsApp devolutiva if comms enabled and candidates have phone
    user_data = app.state.user_mapping.get_user(conv.user_id) or {}
    if user_data.get("comms_enabled", True):
        with_phone = []
        for c in to_reject:
            phone = _talent_phone(c)
            if phone:
                c_name = (c.get("talent") or {}).get("name") or c.get("talentName") or "Sem nome"
                with_phone.append({"phone": phone, "candidate_name": c_name, "message": rejection_msg})
        if with_phone:
            conv.set_context("whatsapp_rejection_pending", with_phone)
            await _send_approval(
                conv, slack, channel_id,
                title="Enviar devolutiva por WhatsApp?",
                details=f"{len(with_phone)} candidato(s) com telefone.\nMensagem:\n> {rejection_msg[:200]}",
                callback_id="whatsapp_rejection_approval",
            )
            return

    conv.state = FlowState.IDLE
