import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta

import redis

from config import get_settings

logger = logging.getLogger("agente-inhire.monitor")

REDIS_ALERT_PREFIX = "inhire:alert:"
REDIS_INSIGHTS_PREFIX = "inhire:insights:"
REDIS_THRESHOLD_PREFIX = "inhire:threshold:"
REDIS_BRIEFING_PREFIX = "inhire:briefing:"
REDIS_PROACTIVE_COUNT_PREFIX = "inhire:proactive_count:"
REDIS_QUEUED_MSG_PREFIX = "inhire:queued_msg:"
REDIS_LAST_INTERACTION_PREFIX = "inhire:last_interaction:"
ALERT_TTL = 86400  # Don't repeat same alert within 24h
DEFAULT_STALE_DAYS = 3
DEFAULT_SHORTLIST_THRESHOLD = 5
MAX_PROACTIVE_MESSAGES_PER_DAY = 3
EXCEPTIONAL_CANDIDATE_SCORE = 4.5

# Business hours (BRT = UTC-3)
BRT = timezone(timedelta(hours=-3))
BUSINESS_HOUR_START = 8
BUSINESS_HOUR_END = 19
BUSINESS_DAYS = range(0, 5)  # Monday=0 to Friday=4

# Escalation tiers (days since last activity → alert level)
# Tier 4 "stop" = don't send individual alerts, only mention in daily briefing
ESCALATION_TIERS = [
    (21, "stop"),       # 21+ days → stop insisting, only mention in briefing
    (14, "critical"),   # 14+ days → final reminder
    (7, "warning"),     # 7+ days → second reminder
    (3, "info"),        # 3+ days → first alert
]

# Recruiter inactivity tiers (days since last interaction)
INACTIVITY_TIERS = [
    (10, "long"),   # 10+ days → very gentle, "tá tudo bem?"
    (5, "medium"),  # 5+ days → "faz uns dias que a gente não se fala"
    (2, "short"),   # 2+ days → "tem novidades nas suas vagas"
]


class ProactiveMonitor:
    """Monitors jobs and sends proactive alerts to recruiters via Slack."""

    def __init__(self, inhire, slack, user_mapping, learning, conversations=None, claude=None):
        self.inhire = inhire
        self.slack = slack
        self.user_mapping = user_mapping
        self.learning = learning
        self.conversations = conversations
        self.claude = claude
        self._redis = None
        try:
            settings = get_settings()
            self._redis = redis.from_url(settings.redis_url, decode_responses=True)
            self._redis.ping()
        except Exception:
            pass

    def _alert_key(self, job_id: str, alert_type: str, extra: str = "") -> str:
        return f"{REDIS_ALERT_PREFIX}{job_id}:{alert_type}:{extra}"

    def _was_alerted(self, job_id: str, alert_type: str, extra: str = "") -> bool:
        """Check if this alert was already sent recently."""
        if not self._redis:
            return False
        try:
            return self._redis.exists(self._alert_key(job_id, alert_type, extra)) > 0
        except Exception:
            return False

    def _mark_alerted(self, job_id: str, alert_type: str, extra: str = "", ttl: int = 0):
        """Mark an alert as sent. Returns True if marked (was not set), False if already existed."""
        if self._redis:
            try:
                actual_ttl = ttl or ALERT_TTL
                return self._redis.set(
                    self._alert_key(job_id, alert_type, extra),
                    "1", ex=actual_ttl, nx=True,
                ) is not None
            except Exception:
                return False
        return False

    def _get_threshold(self, user_id: str, job_id: str, stage: str = "") -> int:
        """Get configurable stale threshold in days."""
        if self._redis:
            try:
                key = f"{REDIS_THRESHOLD_PREFIX}{user_id}:{job_id}:{stage}"
                val = self._redis.get(key)
                if val:
                    return int(val)
            except Exception:
                pass
        return DEFAULT_STALE_DAYS

    def _proactive_count_today(self, slack_user_id: str) -> int:
        """Get number of proactive messages sent today to this user."""
        if not self._redis:
            return 0
        try:
            key = f"{REDIS_PROACTIVE_COUNT_PREFIX}{slack_user_id}:{datetime.now(BRT).strftime('%Y-%m-%d')}"
            val = self._redis.get(key)
            return int(val) if val else 0
        except Exception:
            return 0

    def _increment_proactive_count(self, slack_user_id: str):
        """Increment daily proactive message counter."""
        if self._redis:
            try:
                key = f"{REDIS_PROACTIVE_COUNT_PREFIX}{slack_user_id}:{datetime.now(BRT).strftime('%Y-%m-%d')}"
                pipe = self._redis.pipeline()
                pipe.incr(key)
                pipe.expire(key, 86400)
                pipe.execute()
            except Exception:
                pass

    def _queue_message(self, slack_user_id: str, channel_id: str, text: str):
        """Queue a message for delivery at next business hours window."""
        if self._redis:
            try:
                msg = json.dumps({"user_id": slack_user_id, "channel_id": channel_id, "text": text})
                self._redis.rpush(f"{REDIS_QUEUED_MSG_PREFIX}{slack_user_id}", msg)
                self._redis.expire(f"{REDIS_QUEUED_MSG_PREFIX}{slack_user_id}", 86400 * 2)
                logger.info("Mensagem enfileirada para %s (fora do horário comercial)", slack_user_id)
            except Exception as e:
                logger.warning("Erro ao enfileirar mensagem: %s", e)

    async def _flush_queued_messages(self, slack_user_id: str, channel_id: str):
        """Send all queued messages for a user (called during business hours)."""
        if not self._redis:
            return
        key = f"{REDIS_QUEUED_MSG_PREFIX}{slack_user_id}"
        try:
            while True:
                raw = self._redis.lpop(key)
                if not raw:
                    break
                msg = json.loads(raw)
                # Check daily limit before sending queued messages too
                if self._proactive_count_today(slack_user_id) >= MAX_PROACTIVE_MESSAGES_PER_DAY:
                    # Re-queue remaining messages
                    self._redis.lpush(key, raw)
                    logger.info("Limite diário atingido ao esvaziar fila de %s", slack_user_id)
                    break
                await self.slack.send_message(msg["channel_id"], msg["text"])
                self._increment_proactive_count(slack_user_id)
                if self.conversations:
                    conv = self.conversations.get_or_create(slack_user_id, msg["channel_id"])
                    conv.add_message("assistant", msg["text"])
                    self.conversations.save(conv)
        except Exception as e:
            logger.warning("Erro ao esvaziar fila de %s: %s", slack_user_id, e)

    async def _send_proactive(self, slack_user_id: str, channel_id: str, text: str,
                              alert_type: str = "generic"):
        """Send a proactive message with daily limit and business hours queue.
        - If outside business hours: queue for next window
        - If daily limit reached: silently drop (logged)
        - Otherwise: send and record in conversation history
        - Records alert_type in LearningService for utility tracking
        """
        # Outside business hours → queue (uses per-recruiter config)
        if not self._is_business_hours(slack_user_id):
            self._queue_message(slack_user_id, channel_id, text)
            return

        # Check daily limit (per-recruiter or global default)
        max_msgs = self.user_mapping.get_setting(slack_user_id, "max_proactive_messages") or MAX_PROACTIVE_MESSAGES_PER_DAY
        if self._proactive_count_today(slack_user_id) >= max_msgs:
            logger.info("Limite proativo atingido para %s (%d/%d), mensagem suprimida",
                        slack_user_id, max_msgs, max_msgs)
            return

        await self.slack.send_message(channel_id, text)
        self._increment_proactive_count(slack_user_id)
        if self.conversations:
            conv = self.conversations.get_or_create(slack_user_id, channel_id)
            conv.add_message("assistant", text)
            self.conversations.save(conv)

        # Record alert for utility tracking
        if self.learning:
            self.learning.record_alert_sent(slack_user_id, alert_type)

    def set_threshold(self, user_id: str, job_id: str, days: int, stage: str = ""):
        """Set stale threshold for a user/job/stage."""
        if self._redis:
            try:
                key = f"{REDIS_THRESHOLD_PREFIX}{user_id}:{job_id}:{stage}"
                self._redis.setex(key, 86400 * 90, str(days))  # 90 days
            except Exception:
                pass

    def _is_business_hours(self, slack_user_id: str | None = None) -> bool:
        """Check if current time is within business hours.
        Uses per-recruiter config if available, otherwise global defaults.
        """
        now_brt = datetime.now(BRT)
        if slack_user_id:
            start = self.user_mapping.get_setting(slack_user_id, "working_hours_start") or BUSINESS_HOUR_START
            end = self.user_mapping.get_setting(slack_user_id, "working_hours_end") or BUSINESS_HOUR_END
            days = self.user_mapping.get_setting(slack_user_id, "working_days") or BUSINESS_DAYS
        else:
            start, end, days = BUSINESS_HOUR_START, BUSINESS_HOUR_END, BUSINESS_DAYS
        return now_brt.weekday() in days and start <= now_brt.hour < end

    def _briefing_sent_today(self, slack_user_id: str) -> bool:
        """Check if daily briefing was already sent today."""
        if not self._redis:
            return False
        try:
            key = f"{REDIS_BRIEFING_PREFIX}{slack_user_id}:{datetime.now(BRT).strftime('%Y-%m-%d')}"
            return self._redis.exists(key) > 0
        except Exception:
            return False

    def _mark_briefing_sent(self, slack_user_id: str):
        """Mark daily briefing as sent for today."""
        if self._redis:
            try:
                key = f"{REDIS_BRIEFING_PREFIX}{slack_user_id}:{datetime.now(BRT).strftime('%Y-%m-%d')}"
                self._redis.setex(key, 86400, "1")
            except Exception:
                pass

    def record_interaction(self, slack_user_id: str):
        """Record that a recruiter interacted (called from slack.py on every DM)."""
        if self._redis:
            try:
                self._redis.setex(
                    f"{REDIS_LAST_INTERACTION_PREFIX}{slack_user_id}",
                    86400 * 30,  # 30 days
                    str(time.time()),
                )
            except Exception:
                pass

    def _days_since_interaction(self, slack_user_id: str) -> int | None:
        """Get days since last recruiter interaction. None if never tracked."""
        if not self._redis:
            return None
        try:
            val = self._redis.get(f"{REDIS_LAST_INTERACTION_PREFIX}{slack_user_id}")
            if val:
                return int((time.time() - float(val)) / 86400)
        except Exception:
            pass
        return None

    @staticmethod
    def _inactivity_message(days: int, tier: str, has_news: bool) -> str:
        """Build inactivity message per AGENT_BEHAVIOR_GUIDE section 3.8."""
        if tier == "short":
            if has_news:
                return f"E aí, tudo bem? Suas vagas têm novidades — quer dar uma olhada?"
            return f"E aí, tudo bem? Faz {days} dias que a gente não se fala. Quando precisar, é só chamar!"
        elif tier == "medium":
            return (
                f"Faz uns dias que a gente não se fala! "
                f"Suas vagas continuam rolando. Quer um resumo de como tá tudo?"
            )
        else:  # long
            return (
                f"Oi! Faz um tempo que você não aparece. Tá tudo bem? "
                f"Quando quiser, é só me chamar que te atualizo de tudo."
            )

    async def _check_recruiter_inactivity(self, user: dict, channel_id: str, has_open_jobs: bool):
        """Check if recruiter has been inactive and send appropriate nudge."""
        slack_user_id = user["slack_user_id"]
        days = self._days_since_interaction(slack_user_id)
        if days is None:
            return  # Never tracked — skip

        for tier_days, tier_level in INACTIVITY_TIERS:
            if days >= tier_days and has_open_jobs:
                alert_key = f"inactive_{tier_level}"
                if not self._was_alerted(slack_user_id, alert_key):
                    msg = self._inactivity_message(days, tier_level, has_open_jobs)
                    await self._send_proactive(slack_user_id, channel_id, msg,
                                               alert_type=f"inactivity_{tier_level}")
                    # TTL: don't repeat for a while
                    ttl = {"short": ALERT_TTL * 2, "medium": ALERT_TTL * 5, "long": ALERT_TTL * 10}
                    if self._redis:
                        try:
                            self._redis.setex(
                                self._alert_key(slack_user_id, alert_key),
                                ttl.get(tier_level, ALERT_TTL),
                                "1",
                            )
                        except Exception:
                            pass
                break  # Only send highest applicable tier

    async def send_daily_briefing(self):
        """Send morning briefing to all recruiters. Called by cron at 9h BRT."""
        users = self.user_mapping.get_all_users()
        if not users:
            return

        logger.info("Briefing diário: enviando para %d recrutadores", len(users))

        async def _safe_briefing(user):
            try:
                await self._send_user_briefing(user)
            except Exception as e:
                logger.exception("Erro no briefing de %s: %s", user.get("inhire_name"), e)

        await asyncio.gather(*[_safe_briefing(user) for user in users])

    async def _send_user_briefing(self, user: dict):
        """Build and send daily briefing for a single recruiter."""
        slack_user_id = user["slack_user_id"]
        inhire_name = user.get("inhire_name", "")

        if self._briefing_sent_today(slack_user_id):
            return

        # Open DM
        try:
            dm_resp = await self.slack.client.conversations_open(users=slack_user_id)
            channel_id = dm_resp["channel"]["id"]
        except Exception as e:
            logger.warning("Não consegui abrir DM com %s: %s", slack_user_id, e)
            return

        # Get user's open jobs
        try:
            jobs_data = await self.inhire._request("POST", "/jobs/paginated/lean", json={})
            all_jobs = jobs_data.get("results", []) if isinstance(jobs_data, dict) else jobs_data
            user_jobs = [j for j in all_jobs if j.get("userName") == inhire_name and j.get("status") == "open"]
        except Exception as e:
            logger.warning("Erro ao buscar jobs para briefing: %s", e)
            return

        if not user_jobs:
            return  # No active jobs, skip briefing

        # Build briefing lines
        now = datetime.now(timezone.utc)
        lines = []
        has_news = False

        for job in user_jobs:
            job_id = job.get("id", "")
            job_name = job.get("name", "Vaga")
            talents_count = job.get("talentsCount", 0)
            created_at = job.get("createdAt", "")
            sla = job.get("sla")

            # Calculate days open
            days_open = 0
            if created_at:
                try:
                    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    days_open = (now - created).days
                except Exception:
                    pass

            # Try to get new candidates count (last 24h)
            new_count = 0
            high_fit_count = 0
            try:
                talents = await self.inhire.list_job_talents(job_id)
                for t in talents:
                    t_created = t.get("createdAt", "")
                    if t_created:
                        try:
                            t_dt = datetime.fromisoformat(t_created.replace("Z", "+00:00"))
                            if (now - t_dt).total_seconds() < 86400:
                                new_count += 1
                        except Exception:
                            pass
                    if t.get("screening", {}).get("status") == "pre-aproved":
                        high_fit_count += 1
            except Exception:
                pass

            # Build line for this job
            parts = [f"• *{job_name}*"]
            details = []

            if new_count > 0:
                details.append(f"{new_count} candidato{'s' if new_count > 1 else ''} novo{'s' if new_count > 1 else ''}")
                has_news = True

            if high_fit_count > 0:
                details.append(f"{high_fit_count} alto fit")
                has_news = True

            if talents_count == 0:
                details.append("0 candidatos")
                has_news = True

            if sla and isinstance(sla, (int, float)) and sla > 0:
                days_remaining = sla - days_open
                if days_remaining <= 7:
                    details.append(f"SLA em {max(days_remaining, 0)} dias")
                    has_news = True

            # Check stale pipeline
            status_history = job.get("statusHistory", [])
            last_activity = created_at
            if status_history:
                last_activity = status_history[-1].get("createdAt", created_at)
            try:
                last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
                days_since = (now - last_dt).days
                if days_since >= 4:
                    details.append(f"sem movimento há {days_since} dias")
                    has_news = True
            except Exception:
                pass

            if details:
                parts.append(f" — {', '.join(details)}")
            else:
                parts.append(f" — {talents_count} candidato{'s' if talents_count != 1 else ''}, tudo em dia ✓")

            lines.append("".join(parts))

        if not has_news:
            return  # Nothing new, don't bother the recruiter

        # Compose and send
        text = "Bom dia! ☀️ Resumo das suas vagas:\n\n" + "\n".join(lines)

        # Add suggestion based on most urgent item
        urgent_jobs = [j for j in user_jobs if j.get("talentsCount", 0) >= DEFAULT_SHORTLIST_THRESHOLD]
        if urgent_jobs:
            text += f"\n\nQuer que eu monte o shortlist da vaga de *{urgent_jobs[0].get('name')}*?"

        # Add audit log section (what Eli did automatically yesterday)
        try:
            from services.audit_log import AuditLog
            audit = AuditLog()
            audit_text = audit.format_for_briefing(slack_user_id)
            if audit_text:
                text += f"\n\n🤖 *O que eu fiz ontem:*\n{audit_text}\n"
        except Exception:
            pass

        await self._send_proactive(slack_user_id, channel_id, text,
                                   alert_type="daily_briefing")
        self._mark_briefing_sent(slack_user_id)
        logger.info("Briefing enviado para %s", inhire_name or slack_user_id)

    @staticmethod
    def _stale_message(job_name: str, days: int, talents: int, tier: str) -> str:
        """Build stale pipeline message with escalating tone per AGENT_BEHAVIOR_GUIDE."""
        if tier == "info":
            return (
                f"💤 *Pipeline parado — {job_name}*\n"
                f"Tem candidatos parados há {days} dias. Candidatos: {talents}\n"
                f"Quer mover alguém ou precisa de ajuda pra agendar?"
            )
        elif tier == "warning":
            return (
                f"💤 *Lembrete — {job_name}*\n"
                f"Os candidatos continuam parados, já fazem {days} dias.\n"
                f"Candidatos: {talents}\n"
                f"Se precisar de uma mão pra destravar, me avisa!"
            )
        else:  # critical
            return (
                f"⚠️ *Atenção — {job_name}*\n"
                f"Faz {days} dias que essa vaga tem candidatos parados.\n"
                f"Candidatos: {talents}\n"
                f"Tá tudo bem por aí? Quando quiser, posso te dar um resumo atualizado pra facilitar a decisão."
            )

    async def check_all_jobs(self):
        """Main monitoring loop — called by cron every hour. Checks all recruiters in parallel.
        Respects business hours: only sends proactive alerts Mon-Fri 8h-19h BRT.
        """
        if not self._is_business_hours():
            logger.debug("Fora do horário comercial, pulando monitoramento proativo.")
            return

        users = self.user_mapping.get_all_users()
        if not users:
            logger.info("Nenhum recrutador mapeado, pulando monitoramento.")
            return

        logger.info("Monitoramento proativo: verificando vagas de %d recrutadores em paralelo", len(users))

        async def _safe_check(user):
            try:
                await self._check_user_jobs(user)
            except Exception as e:
                logger.exception("Erro ao monitorar vagas de %s: %s", user.get("inhire_name"), e)

        await asyncio.gather(*[_safe_check(user) for user in users])

    async def _check_user_jobs(self, user: dict):
        """Check all open jobs for a specific recruiter."""
        slack_user_id = user["slack_user_id"]
        inhire_name = user.get("inhire_name", "")

        # Get DM channel for this user
        try:
            dm_resp = await self.slack.client.conversations_open(users=slack_user_id)
            channel_id = dm_resp["channel"]["id"]
        except Exception as e:
            logger.warning("Não consegui abrir DM com %s: %s", slack_user_id, e)
            return

        # Flush queued messages from outside business hours
        await self._flush_queued_messages(slack_user_id, channel_id)

        # Get all open requisitions and find ones belonging to this user
        try:
            requisitions = await self.inhire._request("GET", "/requisitions")
        except Exception:
            requisitions = []

        # Filter by user name (since we can't filter by userId in the API)
        user_jobs = []
        try:
            # Use POST /jobs/paginated/lean (GET /jobs returns 502)
            jobs_data = await self.inhire._request("POST", "/jobs/paginated/lean", json={})
            all_jobs = jobs_data.get("results", []) if isinstance(jobs_data, dict) else jobs_data
            user_jobs = [j for j in all_jobs if j.get("userName") == inhire_name and j.get("status") == "open"]
        except Exception as e:
            logger.warning("Erro ao buscar jobs: %s", e)
            return

        # Check recruiter inactivity
        await self._check_recruiter_inactivity(user, channel_id, has_open_jobs=bool(user_jobs))

        for job in user_jobs:
            try:
                await self._check_single_job(job, user, channel_id)
            except Exception as e:
                logger.warning("Erro ao verificar vaga %s: %s", job.get("id"), e)

    async def _check_single_job(self, job: dict, user: dict, channel_id: str):
        """Run all checks for a single job."""
        job_id = job.get("id", "")
        job_name = job.get("name", "Vaga")
        created_at = job.get("createdAt", "")
        sla = job.get("sla")
        talents_count = job.get("talentsCount", 0)
        slack_user_id = user["slack_user_id"]

        now = datetime.now(timezone.utc)

        # Calculate days open
        days_open = 0
        if created_at:
            try:
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                days_open = (now - created).days
            except Exception:
                pass

        # --- Check SLA ---
        if sla and isinstance(sla, (int, float)) and sla > 0:
            days_remaining = sla - days_open
            if days_remaining <= 0 and not self._was_alerted(job_id, "sla_expired"):
                await self._send_proactive(
                    slack_user_id, channel_id,
                    f"🚨 *SLA estourado — {job_name}*\n"
                    f"SLA era de {sla} dias, vaga está aberta há {days_open} dias.\n"
                    f"Candidatos: {talents_count}\n"
                    f"Quer ver o status detalhado?",
                    alert_type="sla_expired",
                )
                self._mark_alerted(job_id, "sla_expired")

            elif 0 < days_remaining <= 3 and not self._was_alerted(job_id, "sla_warning"):
                await self._send_proactive(
                    slack_user_id, channel_id,
                    f"⚠️ *SLA em {days_remaining} dias — {job_name}*\n"
                    f"Candidatos: {talents_count}\n"
                    f"Quer ver a triagem dos candidatos?",
                    alert_type="sla_warning",
                )
                self._mark_alerted(job_id, "sla_warning")

        # --- Check pipeline stale (escalation: 3d → 7d → 14d) ---
        status_history = job.get("statusHistory", [])
        last_activity = created_at
        if status_history:
            last_activity = status_history[-1].get("createdAt", created_at)

        try:
            last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
            days_since_activity = (now - last_dt).days
        except Exception:
            days_since_activity = days_open

        # Walk escalation tiers from highest to lowest
        for tier_days, tier_level in ESCALATION_TIERS:
            if days_since_activity >= tier_days:
                if tier_level == "stop":
                    # Tier 4: stop insisting — will only appear in daily briefing
                    break
                alert_key = f"stale_{tier_level}"
                if not self._was_alerted(job_id, alert_key):
                    ttl_map = {"info": ALERT_TTL, "warning": ALERT_TTL * 3, "critical": ALERT_TTL * 7}
                    msg = self._stale_message(job_name, days_since_activity, talents_count, tier_level)
                    await self._send_proactive(slack_user_id, channel_id, msg,
                                               alert_type=f"stale_{tier_level}")
                    if self._redis:
                        try:
                            self._redis.setex(
                                self._alert_key(job_id, alert_key),
                                ttl_map.get(tier_level, ALERT_TTL),
                                "1",
                            )
                        except Exception:
                            pass
                break  # Only send the highest applicable tier

        # --- Check high fit accumulation ---
        try:
            apps = await self.inhire.list_job_talents(job_id)
            high_fit = [a for a in apps if a.get("screening", {}).get("status") == "pre-aproved"]
            low_fit = [a for a in apps if a.get("screening", {}).get("status") == "pre-rejected"]
            total_scored = len([a for a in apps if a.get("screening", {}).get("status")])

            # Alert: exceptional candidate (score >= 4.5) — immediate notification
            for a in apps:
                screening = a.get("screening", {}) or {}
                score = screening.get("score")
                if score and isinstance(score, (int, float)) and score >= EXCEPTIONAL_CANDIDATE_SCORE:
                    talent = a.get("talent", {}) or {}
                    candidate_name = talent.get("name") or a.get("talentName", "Candidato")
                    candidate_id = a.get("id", "")
                    if not self._was_alerted(job_id, "exceptional", candidate_id):
                        await self._send_proactive(
                            slack_user_id, channel_id,
                            f"🌟 *Candidato excepcional — {job_name}*\n"
                            f"*{candidate_name}* chegou com score *{score}*!\n"
                            f"Quer que eu te passe os detalhes?",
                            alert_type="exceptional_candidate",
                        )
                        self._mark_alerted(job_id, "exceptional", candidate_id)

            # Alert: enough high fit for shortlist
            if len(high_fit) >= DEFAULT_SHORTLIST_THRESHOLD and not self._was_alerted(job_id, "shortlist_ready"):
                await self._send_proactive(
                    slack_user_id, channel_id,
                    f"🎯 *Shortlist pronto — {job_name}*\n"
                    f"{len(high_fit)} candidatos com alto fit!\n"
                    f"Quer ver o resumo comparativo?",
                    alert_type="shortlist_ready",
                )
                self._mark_alerted(job_id, "shortlist_ready")

            # Alert: too many low fit
            if total_scored >= 10 and len(low_fit) / max(total_scored, 1) >= 0.8:
                if not self._was_alerted(job_id, "low_fit_high"):
                    await self._send_proactive(
                        slack_user_id, channel_id,
                        f"⚠️ *Critérios rígidos? — {job_name}*\n"
                        f"{len(low_fit)}/{total_scored} candidatos com baixo fit ({int(len(low_fit)/total_scored*100)}%).\n"
                        f"Considere revisar os critérios da vaga ou a descrição.",
                        alert_type="low_fit_high",
                    )
                    self._mark_alerted(job_id, "low_fit_high")

        except Exception:
            pass  # Applications may be empty for hunting-only jobs

        # --- Check interview follow-up ---
        # Detect candidates stuck in interview stages for 3+ days without feedback
        INTERVIEW_KEYWORDS = ("entrevista", "interview", "bate-papo", "batepapo", "conversa")
        FOLLOWUP_DAYS = 3
        try:
            talents = await self.inhire._request("GET", f"/job-talents/{job_id}/talents")
            if isinstance(talents, list):
                for talent in talents:
                    stage_name = talent.get("stageName", "")
                    talent_name = talent.get("talentName") or talent.get("name", "Candidato")
                    job_talent_id = talent.get("id", "")

                    if not any(kw in stage_name.lower() for kw in INTERVIEW_KEYWORDS):
                        continue

                    # Check how long they've been in this stage
                    stage_date = talent.get("stageUpdatedAt") or talent.get("updatedAt", "")
                    if not stage_date:
                        continue
                    try:
                        stage_dt = datetime.fromisoformat(stage_date.replace("Z", "+00:00"))
                        days_in_stage = (now - stage_dt).days
                    except Exception:
                        continue

                    if days_in_stage >= FOLLOWUP_DAYS:
                        alert_id = f"followup_{job_talent_id}"
                        if not self._was_alerted(job_id, alert_id):
                            await self._send_proactive(
                                slack_user_id, channel_id,
                                f"💬 *{talent_name}* fez entrevista pra *{job_name}* há {days_in_stage} dias "
                                f"(etapa: *{stage_name}*).\n"
                                f"Já tem um retorno? Se quiser, posso mover ou precisa de mais tempo?",
                                alert_type="interview_followup",
                            )
                            self._mark_alerted(job_id, alert_id)
        except Exception:
            pass  # Talent list may fail for some jobs

        # Stage-specific follow-ups
        await self._check_stage_followups(job, user, channel_id)

    async def _check_stage_followups(self, job: dict, user: dict, channel_id: str):
        """Stage-specific follow-ups: interview feedback, offer decision, exceptional urgency."""
        job_id = job.get("id", "")
        job_name = job.get("name", "")
        user_id = user.get("slack_user_id", "")
        intensity = user.get("followup_intensity", "normal")
        multiplier = {"gentle": 2.0, "normal": 1.0, "aggressive": 0.5}.get(intensity, 1.0)

        try:
            candidates = await self.inhire.list_job_talents(job_id)
        except Exception:
            return

        now = datetime.now(timezone.utc)

        for c in candidates:
            if c.get("status") in ("rejected", "dropped"):
                continue

            stage = c.get("stage", {}) or {}
            stage_name = stage.get("name", "")
            stage_type = stage.get("type", "")
            talent = c.get("talent", {}) or {}
            name = talent.get("name", "?")
            jt_id = c.get("id", "")
            screening = c.get("screening", {}) or {}
            score = screening.get("score")

            updated = c.get("updatedAt") or c.get("createdAt", "")
            if not updated:
                continue
            try:
                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                hours_in_stage = (now - updated_dt).total_seconds() / 3600
            except Exception:
                continue

            # Check if candidate was recently moved (webhook set this flag)
            try:
                if self._redis and self._redis.exists(f"inhire:stage_changed:{jt_id}"):
                    continue
            except Exception:
                pass

            # --- Interview stages: follow-up for feedback ---
            if stage_type in ("culturalFit", "technicalFit"):
                followup_hours = 24 * multiplier
                if hours_in_stage >= followup_hours:
                    alert_key = f"followup_interview:{jt_id}"
                    if not self._was_recently_sent(user_id, alert_key, ttl_hours=48 * multiplier):
                        days = int(hours_in_stage / 24)
                        msg = (
                            f"📝 *{name}* está em *{stage_name}* há "
                            f"{days} dia(s) na vaga *{job_name}*.\n"
                            f"Se já entrevistou, me conta como foi que eu preencho o scorecard!"
                        )
                        await self._send_proactive(user_id, channel_id, msg, alert_type="interview_followup")

            # --- Offer stage: follow-up for decision ---
            elif stage_type == "offer":
                followup_hours = 72 * multiplier
                if hours_in_stage >= followup_hours:
                    alert_key = f"followup_offer:{jt_id}"
                    if not self._was_recently_sent(user_id, alert_key, ttl_hours=72 * multiplier):
                        days = int(hours_in_stage / 24)
                        msg = (
                            f"📋 A proposta de *{name}* está aberta há *{days} dias* "
                            f"na vaga *{job_name}*.\nQuer que eu entre em contato com o candidato?"
                        )
                        await self._send_proactive(user_id, channel_id, msg, alert_type="offer_followup")

            # --- Exceptional candidate urgency ---
            if score and isinstance(score, (int, float)) and score >= 4.5:
                urgency_hours = 8 * multiplier  # T+8h (not T+4h per specialist review)
                if hours_in_stage >= urgency_hours:
                    alert_key = f"exceptional_urgent:{jt_id}"
                    if not self._was_recently_sent(user_id, alert_key, ttl_hours=24):
                        msg = (
                            f"🚨 *{name}* (score {score:.1f}) está na vaga *{job_name}* "
                            f"há {int(hours_in_stage)}h sem avançar.\n"
                            f"Perfis assim costumam receber outras propostas rápido."
                        )
                        await self._send_proactive(user_id, channel_id, msg, alert_type="exceptional_urgent")

    def _was_recently_sent(self, user_id: str, alert_key: str, ttl_hours: float = 24) -> bool:
        """Check if this specific follow-up was sent recently. Returns True if already sent (skip)."""
        try:
            if not self._redis:
                return False
            key = f"inhire:followup_sent:{user_id}:{alert_key}"
            if self._redis.get(key):
                return True
            self._redis.set(key, "1", ex=int(ttl_hours * 3600))
            return False
        except Exception:
            return False

    # ==============================================================================
    # WEEKLY CONSOLIDATED REPORT
    # ==============================================================================

    async def _weekly_report(self):
        """Send weekly consolidated report of all active jobs to all recruiters.
        Called by cron every Monday at 9:30 BRT.
        """
        users = self.user_mapping.get_all_users()
        if not users:
            return

        logger.info("Relatório semanal: enviando para %d recrutadores", len(users))

        async def _safe_report(user):
            try:
                await self._send_user_weekly_report(user)
            except Exception as e:
                logger.exception("Erro no relatório semanal de %s: %s", user.get("inhire_name"), e)

        await asyncio.gather(*[_safe_report(user) for user in users])

    async def _send_user_weekly_report(self, user: dict):
        """Build and send weekly consolidated report for a single recruiter."""
        slack_user_id = user["slack_user_id"]
        inhire_name = user.get("inhire_name", "")

        # Open DM
        try:
            dm_resp = await self.slack.client.conversations_open(users=slack_user_id)
            channel_id = dm_resp["channel"]["id"]
        except Exception as e:
            logger.warning("Não consegui abrir DM com %s: %s", slack_user_id, e)
            return

        # Get all open jobs for this user
        try:
            jobs_data = await self.inhire._request("POST", "/jobs/paginated/lean", json={})
            all_jobs = jobs_data.get("results", []) if isinstance(jobs_data, dict) else jobs_data
            user_jobs = [j for j in all_jobs if j.get("userName") == inhire_name and j.get("status") == "open"]
        except Exception as e:
            logger.warning("Erro ao buscar jobs para relatório semanal de %s: %s", inhire_name, e)
            return

        if not user_jobs:
            return  # No active jobs, skip

        now = datetime.now(timezone.utc)
        job_lines = []
        total_candidates = 0
        at_risk_count = 0

        for job in user_jobs:
            job_id = job.get("id", "")
            job_name = job.get("name", "Vaga")
            created_at = job.get("createdAt", "")

            # Calculate days open
            days_open = 0
            if created_at:
                try:
                    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    days_open = (now - created).days
                except Exception:
                    pass

            # Status emoji based on days open
            if days_open < 15:
                emoji = "🟢"
            elif days_open < 30:
                emoji = "🟡"
            else:
                emoji = "🔴"
                at_risk_count += 1

            # Fetch candidates and build stage distribution
            candidate_count = 0
            stage_dist: dict[str, int] = {}
            try:
                talents = await self.inhire._request("GET", f"/job-talents/{job_id}/talents")
                if isinstance(talents, list):
                    candidate_count = len(talents)
                    for t in talents:
                        stage = t.get("stageName") or "Sem etapa"
                        stage_dist[stage] = stage_dist.get(stage, 0) + 1
            except Exception:
                # Fallback to talentsCount from job listing
                candidate_count = job.get("talentsCount", 0)

            total_candidates += candidate_count

            # Build pipeline summary string
            if stage_dist:
                pipeline_parts = [f"{stage}({count})" for stage, count in stage_dist.items()]
                pipeline_str = " → ".join(pipeline_parts)
            else:
                pipeline_str = "(vazio)"

            candidate_label = f"{candidate_count} candidato{'s' if candidate_count != 1 else ''}"
            day_label = f"{days_open}d aberta"

            job_lines.append(
                f"{emoji} *{job_name}* — {candidate_label}, {day_label}\n"
                f"  Pipeline: {pipeline_str}"
            )

        total_jobs = len(user_jobs)
        candidate_total_label = f"{total_candidates} candidato{'s' if total_candidates != 1 else ''}"
        risk_label = f"{at_risk_count} em risco (30d+)" if at_risk_count > 0 else "nenhuma em risco"

        summary = (
            f"*Resumo:* {total_jobs} vaga{'s' if total_jobs != 1 else ''} ativa{'s' if total_jobs != 1 else ''}, "
            f"{candidate_total_label}, {risk_label}"
        )

        text = "📊 *Relatório Semanal*\n\n" + "\n\n".join(job_lines) + "\n\n" + summary

        await self._send_proactive(slack_user_id, channel_id, text, alert_type="weekly_report")
        logger.info("Relatório semanal enviado para %s", inhire_name or slack_user_id)

    # ==============================================================================
    # WEEKLY PATTERN CONSOLIDATION (mini KAIROS)
    # ==============================================================================

    async def weekly_pattern_consolidation(self):
        """Consolidate recruiter decision patterns into 3-line insights via Claude.
        Called weekly (Monday 9:30 BRT). For each recruiter with 5+ decisions,
        generates a natural-language summary stored in Redis for context injection.
        """
        if not self.claude:
            logger.warning("ClaudeService não disponível para consolidação semanal")
            return

        users = self.user_mapping.get_all_users()
        if not users:
            return

        logger.info("Consolidação semanal: processando %d recrutadores", len(users))

        for user in users:
            try:
                await self._consolidate_user_patterns(user)
            except Exception as e:
                logger.warning("Erro na consolidação de %s: %s",
                               user.get("inhire_name"), e)

    async def _consolidate_user_patterns(self, user: dict):
        """Generate pattern consolidation for a single recruiter."""
        slack_user_id = user["slack_user_id"]

        # Only consolidate if recruiter has 5+ decisions
        total = self.learning.total_decisions_count(slack_user_id)
        if total < 5:
            return

        decisions_text = self.learning.get_all_decisions_summary(slack_user_id)
        if not decisions_text:
            return

        recruiter_name = user.get("inhire_name", "recrutador")

        system = (
            "Você é um analista de padrões de recrutamento. A partir do histórico "
            "de decisões de um recrutador (aprovações e reprovações com contexto), "
            "identifique os 3 padrões mais marcantes do estilo de decisão.\n\n"
            "Retorne EXATAMENTE 3 frases curtas e diretas, uma por linha.\n"
            "Foque em: perfil preferido, critérios de rejeição recorrentes, "
            "peso relativo de fatores (salário vs experiência vs localização).\n"
            "Não use bullet points ou numeração. Apenas 3 frases."
        )

        insight = await self.claude.chat(
            messages=[{
                "role": "user",
                "content": (
                    f"Histórico de decisões de {recruiter_name} "
                    f"({total} decisões):\n\n{decisions_text}"
                ),
            }],
            system=system,
        )

        # Store in Redis with 10-day TTL (refreshed weekly, buffer for missed runs)
        if self._redis and insight.strip():
            try:
                self._redis.setex(
                    f"{REDIS_INSIGHTS_PREFIX}{slack_user_id}",
                    86400 * 10,  # 10 days
                    insight.strip(),
                )
                logger.info("Insight semanal gerado para %s: %s",
                            recruiter_name, insight.strip()[:80])
            except Exception as e:
                logger.warning("Erro ao salvar insight: %s", e)
