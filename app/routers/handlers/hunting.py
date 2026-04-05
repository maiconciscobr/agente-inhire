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

        suggestion = _suggest_next_action(
            conv,
            total_candidates=total,
            high_fit=screening_counts.get("pre-aproved", 0),
            stage_counts=stage_counts,
        )
        report += suggestion

        await _send(conv, slack, channel_id, report)

    except Exception as e:
        logger.exception("Erro ao gerar relatório: %s", e)
        await _send(conv, slack, channel_id, f"❌ Erro: {e}")
