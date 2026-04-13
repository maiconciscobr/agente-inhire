import json
import logging

from routers.handlers.helpers import _send, _suggest_next_action

logger = logging.getLogger("agente-inhire.slack-router")


async def _analyze_profile(conv, app, channel_id: str, text: str):
    """Analyze a pasted candidate profile against the current job."""
    slack = app.state.slack
    claude = app.state.claude

    job_name = conv.get_context("current_job_name", "")
    job_data = conv.get_context("job_data", {})
    job_description = conv.get_context("job_description", "")

    context = ""
    if job_name:
        context = f"\n\nVaga atual: {job_name}"
        if job_data:
            context += f"\nRequisitos: {json.dumps(job_data.get('requirements', []), ensure_ascii=False)}"

    await _send(conv, slack, channel_id, "Analisando perfil... ⏳")

    system = """Você é o Eli, assistente de recrutamento. O recrutador te mandou um perfil pra analisar.
Responda como amigo dando opinião — direto e útil, não genérico.

Formato:
*Candidato:* [nome se identificável]
*Fit com a vaga:* 🟢 Alto / 🟡 Médio / 🔴 Baixo

*Pontos fortes:*
• ...

*Pontos de atenção:*
• ...

*Minha recomendação:* [avançar/não avançar/pedir mais info — com justificativa curta]

Se não houver vaga associada, faça uma análise geral do perfil.
Use formatação Slack. Seja conciso."""

    response = await claude.chat(
        messages=[{"role": "user", "content": f"Analise este perfil:{context}\n\n{text}"}],
        system=system,
    )
    await _send(conv, slack, channel_id, response)


async def _generate_linkedin_search(conv, app, channel_id: str):
    """Generate LinkedIn boolean search string for the current job."""
    slack = app.state.slack
    claude = app.state.claude

    job_name = conv.get_context("current_job_name", "")
    job_data = conv.get_context("job_data", {})

    if not job_name and not job_data:
        await _send(
            conv, slack, channel_id,
            "Preciso saber qual vaga pra gerar a busca. Crie uma vaga primeiro ou me diga o cargo.",
        )
        return

    await _send(conv, slack, channel_id, "Gerando string de busca... ⏳")

    system = """Você é um especialista em hunting e sourcing no LinkedIn.
Gere strings de busca booleanas para o LinkedIn Recruiter e LinkedIn Search.

Retorne no formato:

*Busca principal:*
`(string booleana aqui)`

*Busca alternativa (mais ampla):*
`(string booleana aqui)`

*Dicas de hunting:*
• Onde buscar (grupos, empresas referência)
• Hashtags relevantes
• Termos alternativos pro cargo

Use formatação Slack. As strings devem usar AND, OR, NOT e aspas corretamente."""

    context = f"Vaga: {job_name}\n"
    if job_data:
        context += f"Dados: {json.dumps(job_data, ensure_ascii=False, indent=2)}"

    response = await claude.chat(
        messages=[{"role": "user", "content": f"Gere strings de busca LinkedIn para:\n{context}"}],
        system=system,
    )
    await _send(conv, slack, channel_id, response)


async def _search_talents(conv, app, channel_id: str, tool_input: dict):
    """Search talents in the InHire talent pool using Typesense full-text search."""
    slack = app.state.slack
    talent_search = app.state.talent_search

    query = tool_input.get("query", "")
    max_results = tool_input.get("max_results", 10)

    if not query:
        await _send(conv, slack, channel_id, "Me diz o que buscar — cargo, skill, localização...")
        return

    await _send(conv, slack, channel_id, f"Buscando talentos: *{query}*... 🔍")

    try:
        results = await talent_search.search(query, max_results=max_results)
        found = results["found"]
        hits = results["hits"]

        if not hits:
            await _send(
                conv, slack, channel_id,
                f"Não encontrei ninguém com *{query}* no banco de talentos. "
                "Tenta termos diferentes ou mais amplos.",
            )
            return

        msg = f"🔍 *Busca: {query}* — {found} encontrado(s)\n\n"
        for i, hit in enumerate(hits, 1):
            name = hit.get("name", "Sem nome")
            headline = hit.get("headline", "")
            location = hit.get("location", "")
            email = hit.get("email", "")
            linkedin = hit.get("linkedin", "")

            msg += f"*{i}. {name}*"
            if headline:
                msg += f" — {headline}"
            msg += "\n"
            if location:
                msg += f"  📍 {location}\n"
            if linkedin:
                msg += f"  🔗 linkedin.com/in/{linkedin}\n"
            if email:
                msg += f"  ✉️ {email}\n"
            msg += "\n"

        if found > len(hits):
            msg += f"_Mostrando {len(hits)} de {found} resultados._\n"

        msg += "\nQuer que eu analise algum desses perfis? Ou vincule a uma vaga?"
        await _send(conv, slack, channel_id, msg)

    except Exception as e:
        logger.exception("Erro na busca de talentos: %s", e)
        await _send(
            conv, slack, channel_id,
            "Ops, deu ruim na busca. Pode ser que o serviço de busca esteja fora. "
            "Tenta de novo daqui a pouco? 🤔",
        )


async def _compare_jobs(conv, app, channel_id: str):
    """Compare active jobs performance side by side."""
    slack = app.state.slack
    inhire = app.state.inhire

    await _send(conv, slack, channel_id, "Comparando suas vagas... ⏳")

    try:
        jobs_resp = await inhire._request("POST", "/jobs/paginated/lean", json={"limit": 20})
        active = [j for j in jobs_resp.get("results", []) if j.get("status") == "active"]

        if not active:
            await _send(conv, slack, channel_id, "Nenhuma vaga ativa pra comparar.")
            return

        from datetime import datetime, timezone

        comparisons = []
        for job in active[:10]:
            job_id = job.get("id", "")
            job_name = job.get("name", "")
            candidates = await inhire.list_job_talents(job_id)

            days_open = 0
            created = job.get("createdAt", "")
            if created:
                try:
                    c_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    days_open = (datetime.now(timezone.utc) - c_dt).days
                except Exception:
                    pass

            comparisons.append({
                "name": job_name,
                "candidates": len(candidates),
                "days_open": days_open,
                "velocity": round(len(candidates) / max(days_open, 1), 1),
            })

        comparisons.sort(key=lambda x: x["velocity"], reverse=True)

        msg = "📊 *Comparação de Vagas*\n\n"
        for i, c in enumerate(comparisons, 1):
            emoji = "🏆" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"*{i}.*"
            msg += (
                f"{emoji} *{c['name']}*\n"
                f"  Candidatos: {c['candidates']} | Dias aberta: {c['days_open']} | "
                f"Velocidade: {c['velocity']} cand/dia\n\n"
            )

        await _send(conv, slack, channel_id, msg)

    except Exception as e:
        logger.exception("Erro ao comparar vagas: %s", e)
        await _send(conv, slack, channel_id, f"❌ Erro ao comparar: {e}")


async def _job_status_report(conv, app, channel_id: str, job_id: str):
    """Generate a status report for a job including SLA tracking."""
    slack = app.state.slack
    inhire = app.state.inhire

    try:
        job = await inhire.get_job(job_id)
        job_name = job.get("name", "Vaga")
        status = job.get("status", "?")
        created_at = job.get("createdAt", "")
        stages = job.get("stages", [])

        # Calculate SLA
        days_open = None
        sla_info = ""
        if created_at:
            from datetime import datetime, timezone
            try:
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                days_open = (now - created).days
                sla_info = f"*Dias aberta:* {days_open} dias\n"
            except Exception:
                pass

        # Get applications
        applications = await inhire.list_job_talents(job_id)
        total = len(applications)

        # Count by stage
        stage_counts = {}
        screening_counts = {"pre-aproved": 0, "need-aproval": 0, "pre-rejected": 0, "other": 0}
        for a in applications:
            stage = a.get("stageName", "Sem etapa")
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
            s_status = a.get("screening", {}).get("status", "other")
            if s_status in screening_counts:
                screening_counts[s_status] += 1
            else:
                screening_counts["other"] += 1

        status_emoji = {"open": "🟢", "closed": "⚫", "frozen": "🔵"}.get(status, "⚪")

        report = (
            f"📊 *Relatório — {job_name}*\n\n"
            f"*Status:* {status_emoji} {status}\n"
            f"{sla_info}"
            f"*Total candidatos:* {total}\n\n"
        )

        if total > 0:
            report += "*Triagem:*\n"
            report += f"  🟢 Alto fit: {screening_counts['pre-aproved']}\n"
            report += f"  🟡 Médio fit: {screening_counts['need-aproval']}\n"
            report += f"  🔴 Baixo fit: {screening_counts['pre-rejected']}\n"
            report += f"  ⚪ Sem score: {screening_counts['other']}\n\n"

            report += "*Por etapa:*\n"
            for stage_name, count in stage_counts.items():
                report += f"  • {stage_name}: {count}\n"

            # Calculate conversion funnel
            if stages:
                funnel_lines = ["\n*Funil de conversão:*"]
                for stage in stages:
                    stage_name = stage.get("name", "")
                    count = stage_counts.get(stage_name, 0)
                    pct = (count / total * 100) if total > 0 else 0
                    bar_filled = int(pct / 5)
                    bar = "█" * bar_filled + "░" * (20 - bar_filled)
                    funnel_lines.append(f"  {stage_name}: `{bar}` {count} ({pct:.0f}%)")
                funnel_text = "\n".join(funnel_lines)
                report += funnel_text + "\n"

        suggestion = _suggest_next_action(
            conv,
            total_candidates=total,
            high_fit=screening_counts.get("pre-aproved", 0),
            stage_counts=stage_counts,
        )
        report += suggestion

        # AI-powered closing prediction
        try:
            if applications and stages:
                claude = app.state.claude
                prediction_prompt = (
                    f"Vaga: {job_name}\n"
                    f"Dias aberta: {days_open if days_open is not None else 'desconhecido'}\n"
                    f"Total candidatos: {total}\n"
                    f"Distribuição por etapa: {json.dumps(stage_counts, ensure_ascii=False)}\n"
                    f"Alto fit: {screening_counts.get('pre-aproved', 0)}\n\n"
                    f"Em UMA frase curta, estime quando esta vaga pode ser fechada e por quê. "
                    f"Se a vaga está em risco, diga o que fazer. Seja direto."
                )
                pred_resp = await claude.client.messages.create(
                    model=claude.fast_model,
                    max_tokens=100,
                    system=[{"type": "text", "text": "Você é analista de recrutamento. Faça previsões diretas baseadas nos dados. Uma frase apenas."}],
                    messages=[{"role": "user", "content": prediction_prompt}],
                )
                prediction = pred_resp.content[0].text.strip()
                report += f"\n\n🔮 *Previsão:* {prediction}"
        except Exception as pred_err:
            logger.warning("Erro na previsão de fechamento: %s", pred_err)

        await _send(conv, slack, channel_id, report)

    except Exception as e:
        logger.exception("Erro ao gerar relatório: %s", e)
        await _send(conv, slack, channel_id, f"❌ Erro: {e}")
