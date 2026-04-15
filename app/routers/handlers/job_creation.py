import logging

from services.conversation import FlowState
from routers.handlers.helpers import _send, _send_approval, _request_or_auto_approve

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


async def _publish_job(conv, app, channel_id: str, job_id: str):
    """Guide recruiter through publishing a job to job boards."""
    slack = app.state.slack
    inhire = app.state.inhire

    job_name = conv.get_context("current_job_name", "")

    await _send(conv, slack, channel_id, "Verificando canais de divulgação disponíveis... ⏳")

    try:
        # Get available integrations
        integrations = await inhire.get_integrations()

        # Determine which job boards are connected
        available_boards = []
        career_page_id = ""

        for integ in integrations:
            jb_settings = integ.get("jobBoardSettings", {}) or {}
            if jb_settings.get("linkedinId"):
                available_boards.append("linkedin")
            if jb_settings.get("indeedEmail") or jb_settings.get("indeed"):
                available_boards.append("indeed")
            if jb_settings.get("tramposCompanyId"):
                available_boards.append("netVagas")
            # Career page ID for publishing
            if integ.get("url"):
                career_page_id = integ.get("id", "")

        if not available_boards and not career_page_id:
            await _send(conv, slack, channel_id,
                       "Nenhum portal de emprego conectado no InHire. "
                       "Configure as integrações em *Configurações → Integrações* no InHire.")
            return

        # Always include career page
        all_channels = ["Página de carreiras"] + [b.capitalize() for b in available_boards]
        board_list = "\n".join(f"  • {ch}" for ch in all_channels)

        await _send(conv, slack, channel_id,
                   f"📢 *Divulgação — {job_name}*\n\n"
                   f"Canais disponíveis:\n{board_list}\n\n"
                   f"Vou publicar em *todos*. Se quiser remover algum, me avisa!\n"
                   f"Caso contrário, confirma e eu publico.")

        # Store for approval flow
        conv.set_context("publish_job_id", job_id)
        conv.set_context("publish_boards", available_boards)
        conv.set_context("publish_career_page_id", career_page_id)

        async def _do_publish():
            try:
                result = await inhire.publish_job(
                    job_id=job_id,
                    career_page_id=career_page_id,
                    display_name=job_name,
                    active_job_boards=available_boards,
                )
                published = result.get("activeJobBoards", available_boards)
                channels_str = ", ".join(b.capitalize() for b in published) if published else "Página de carreiras"
                await _send(conv, slack, channel_id, f"✅ Vaga *{job_name}* publicada em: {channels_str}!")
            except Exception as exc:
                logger.exception("Erro ao publicar vaga: %s", exc)
                await _send(conv, slack, channel_id, f"❌ Erro ao publicar: {exc}")

        await _request_or_auto_approve(
            conv, app, channel_id,
            action="publish_job",
            title="Publicar vaga?",
            details=f"Publicar *{job_name}* em: {', '.join(all_channels)}",
            callback_id="publish_job_approval",
            execute_fn=_do_publish,
        )

    except Exception as e:
        logger.exception("Erro ao preparar divulgação: %s", e)
        await _send(conv, slack, channel_id, f"❌ Erro ao verificar canais: {e}")


async def _auto_configure_job(conv, app, channel_id: str, job_id: str):
    """Auto-configure screening and scorecard after job creation."""
    slack = app.state.slack
    inhire = app.state.inhire

    job_data = conv.get_context("job_data", {})
    job_name = conv.get_context("current_job_name", "")

    configured = []

    # 1. Configure AI screening from briefing requirements
    try:
        requirements = job_data.get("requirements", [])
        salary_min = job_data.get("salary_range", {}).get("min") if isinstance(job_data.get("salary_range"), dict) else job_data.get("salaryMin")
        salary_max = job_data.get("salary_range", {}).get("max") if isinstance(job_data.get("salary_range"), dict) else job_data.get("salaryMax")

        if requirements:
            statements = []
            for req in requirements:
                if isinstance(req, str):
                    statements.append({"statement": req, "weight": 3})
                elif isinstance(req, dict):
                    name = req.get("name", req.get("skill", ""))
                    weight_map = {"essential": 5, "important": 3, "nice_to_have": 1}
                    w = weight_map.get(req.get("weight", "important"), 3)
                    if name:
                        statements.append({"statement": name, "weight": w})

            screening_settings = {
                "active": True,
                "activeScreeningCriteria": ["resumeAnalysis"],
            }

            if salary_min or salary_max:
                screening_settings["activeScreeningCriteria"].append("salary")
                if salary_min:
                    screening_settings["lowerSalary"] = salary_min
                if salary_max:
                    screening_settings["higherSalary"] = salary_max

            resume_analyzer = {"active": True, "statements": statements} if statements else None

            await inhire.configure_screening(job_id, screening_settings, resume_analyzer)
            configured.append("triagem IA")
    except Exception as e:
        logger.warning("Erro ao configurar screening: %s", e)

    # 2. Configure scorecard from requirements
    try:
        requirements = job_data.get("requirements", [])
        if requirements:
            technical_skills = []
            for req in requirements:
                name = req if isinstance(req, str) else req.get("name", req.get("skill", ""))
                if name:
                    technical_skills.append({"name": name})

            categories = []
            if technical_skills:
                categories.append({"name": "Conhecimento Técnico", "skills": technical_skills[:10]})
            categories.append({"name": "Comunicação e Fit Cultural", "skills": [
                {"name": "Comunicação"},
                {"name": "Fit cultural"},
                {"name": "Motivação"},
            ]})

            await inhire.create_job_scorecard(job_id, categories)
            configured.append("scorecard")
    except Exception as e:
        logger.warning("Erro ao configurar scorecard: %s", e)

    # 3. Generate application form with AI
    try:
        form_result = await inhire.generate_subscription_form(job_id)
        if form_result:
            configured.append("formulário de inscrição (IA)")
    except Exception as e:
        logger.warning("Erro ao gerar formulário IA: %s", e)

    if configured:
        items = ", ".join(configured)
        await _send(conv, slack, channel_id,
                    f"⚙️ Configurei automaticamente: *{items}* para a vaga *{job_name}*.")

    return configured


def _suggest_autonomy_mode(job_data: dict, decisions_count: int) -> tuple[str, str]:
    """Analyze job characteristics and suggest copilot or autopilot.
    Returns (suggested_mode, reason).
    """
    title = (job_data.get("title") or "").lower()
    urgency = (job_data.get("urgency") or "").lower()
    seniority = (job_data.get("seniority") or "").lower()
    salary_max = 0
    sr = job_data.get("salary_range")
    if isinstance(sr, dict):
        salary_max = sr.get("max") or sr.get("min") or 0
    requirements = job_data.get("requirements", [])

    # Signals for COPILOT (more control)
    copilot_signals = []
    leadership_keywords = ["diretor", "director", "head", "vp", "c-level", "cto", "cfo", "ceo", "gerente geral", "líder", "lider"]
    if any(k in title for k in leadership_keywords):
        copilot_signals.append("vaga de liderança")
    if salary_max and salary_max >= 30000:
        copilot_signals.append("salário alto")
    if seniority in ("especialista", "diretor", "c-level"):
        copilot_signals.append("senioridade alta")
    if decisions_count < 15:
        copilot_signals.append("ainda tenho poucos dados pra calibrar")

    # Signals for AUTOPILOT (speed)
    autopilot_signals = []
    if urgency in ("alta", "high", "urgente"):
        autopilot_signals.append("urgência alta")
    if len(requirements) >= 3:
        autopilot_signals.append("requisitos bem definidos")
    if seniority in ("júnior", "junior", "pleno", "pleno-senior", "sênior", "senior"):
        autopilot_signals.append("perfil técnico")
    if salary_max and salary_max < 30000:
        autopilot_signals.append("faixa salarial padrão")
    if decisions_count >= 15:
        autopilot_signals.append("tenho dados suficientes pra calibrar")

    # Few decisions is a strong signal — override everything
    if decisions_count < 15:
        reason = "ainda tenho poucos dados pra calibrar"
        if autopilot_signals:
            reason += f" (mas a vaga tem {', '.join(autopilot_signals[:2])})"
        return "copilot", reason

    if len(copilot_signals) > len(autopilot_signals):
        reason = ", ".join(copilot_signals[:3])
        return "copilot", reason
    elif len(autopilot_signals) >= 2:
        reason = ", ".join(autopilot_signals[:3])
        return "autopilot", reason
    else:
        return "copilot", "posição nova, melhor acompanhar de perto"


def _get_job_mode(redis_conn, recruiter_id: str, job_id: str) -> str | None:
    """Get autonomy mode for a specific job. Returns None if not set (use default)."""
    if not redis_conn:
        return None
    try:
        return redis_conn.get(f"inhire:job_mode:{recruiter_id}:{job_id}")
    except Exception:
        return None


def _set_job_mode(redis_conn, recruiter_id: str, job_id: str, mode: str):
    """Set autonomy mode for a specific job."""
    if not redis_conn:
        return
    try:
        redis_conn.setex(f"inhire:job_mode:{recruiter_id}:{job_id}", 86400 * 180, mode)
    except Exception:
        pass


async def _post_creation_chain(conv, app, channel_id: str, job_id: str):
    """Execute the full post-creation automation chain.
    Phase 1 (sequential): auto-configure (screening, scorecard, form)
    Phase 2 (parallel): smart match + linkedin search
    Phase 3: suggest autonomy mode for this job
    Phase 4: consolidated message with mode suggestion
    """
    import asyncio
    slack = app.state.slack
    inhire = app.state.inhire

    job_data = conv.get_context("job_data", {})
    job_name = conv.get_context("current_job_name", "")

    results = {"configured": [], "match_count": 0, "high_fit": 0, "linkedin": ""}

    # Redis connection (for chain flag + job mode)
    r = None
    try:
        import redis as redis_lib
        from config import get_settings
        r = redis_lib.from_url(get_settings().redis_url, decode_responses=True)
        r.set(f"inhire:chain_active:{job_id}", "1", ex=300)
    except Exception:
        pass

    # Phase 1: Auto-configure (SEQUENTIAL — must complete before match/screening)
    configured = await _auto_configure_job(conv, app, channel_id, job_id)
    results["configured"] = configured or []

    # Phase 2: Smart Match + LinkedIn search (PARALLEL)
    async def _run_smart_match():
        try:
            requirements = job_data.get("requirements", [])
            query = " ".join(requirements[:5]) if requirements else job_name
            ai_result = await inhire.gen_filter_job_talents(job_id, query)
            if ai_result:
                results["match_count"] = ai_result.get("total", 0) if isinstance(ai_result, dict) else 0
            if hasattr(app.state, "audit_log"):
                app.state.audit_log.log_action(
                    conv.user_id, "smart_match", job_id,
                    detail=f"{results['match_count']} matches",
                )
        except Exception as e:
            logger.warning("Smart match pós-vaga falhou: %s", e)

    async def _run_linkedin_search():
        try:
            requirements = job_data.get("requirements", [])
            title = job_data.get("title") or job_name or ""
            location = job_data.get("location") or ""
            terms = [t for t in [title] + requirements[:5] if t]
            if not terms:
                return
            required = " AND ".join(f'"{t}"' for t in terms[:3])
            optional = " OR ".join(f'"{t}"' for t in terms[3:] if t)
            search = f"({required})"
            if optional:
                search += f" AND ({optional})"
            if location:
                search += f' AND "{location}"'
            results["linkedin"] = search
            if hasattr(app.state, "audit_log"):
                app.state.audit_log.log_action(
                    conv.user_id, "linkedin_search", job_id, detail="String gerada",
                )
        except Exception as e:
            logger.warning("LinkedIn search pós-vaga falhou: %s", e)

    await asyncio.gather(_run_smart_match(), _run_linkedin_search(), return_exceptions=True)

    # Clear chain-active flag
    try:
        if r is not None:
            r.delete(f"inhire:chain_active:{job_id}")
    except Exception:
        pass

    # Phase 3: Suggest autonomy mode for this job
    decisions_count = 0
    try:
        learning = getattr(app.state, "learning", None)
        if learning:
            decisions_count = learning.total_decisions_count(conv.user_id)
    except Exception:
        pass

    suggested_mode, suggestion_reason = _suggest_autonomy_mode(job_data, decisions_count)

    # Phase 4: Consolidated message (result-oriented + mode suggestion)
    msg = f"Vaga *{job_name}* criada! Já estou trabalhando nela 🚀\n\n"

    if results["match_count"] > 0:
        msg += (
            f"Encontrei {results['match_count']} candidatos no banco de talentos. "
            f"Estou analisando e te mando o shortlist em breve.\n\n"
        )

    if results["linkedin"]:
        msg += f"Busca LinkedIn pronta:\n`{results['linkedin']}`\n\n"

    # Mode suggestion
    if suggested_mode == "autopilot":
        msg += (
            f"💡 Essa vaga tem *{suggestion_reason}*. "
            f"Recomendo *Piloto Automático* — eu cuido de tudo e só paro pra reprovar e enviar oferta.\n"
            f"Quer ativar? Diz \"piloto automático pra essa vaga\"\n\n"
        )
    else:
        msg += (
            f"💡 Essa vaga tem *{suggestion_reason}*. "
            f"Recomendo *Copiloto* — faço o trabalho pesado mas você aprova os passos importantes.\n"
            f"Se preferir mais autonomia, diz \"piloto automático pra essa vaga\"\n\n"
        )

    msg += "Vou ficar de olho nos candidatos e te aviso quando tiver gente boa!"

    await _send(conv, slack, channel_id, msg)

    conv.state = FlowState.MONITORING_CANDIDATES
