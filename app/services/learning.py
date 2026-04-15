import json
import logging
import time

import redis

from config import get_settings

logger = logging.getLogger("agente-inhire.learning")

REDIS_PREFIX = "inhire:learning:"
REDIS_ALERT_LOG_PREFIX = "inhire:alert_log:"
REDIS_ALERT_STATS_PREFIX = "inhire:alert_stats:"
ALERT_RESPONSE_WINDOW = 1800  # 30 minutes
DECISION_TTL = 86400 * 180  # 180 days — decisions expire after 6 months
ALERT_STATS_TTL = 86400 * 90  # 90 days


class LearningService:
    """Records recruiter decisions and extracts patterns to improve suggestions."""

    def __init__(self):
        self._redis = None
        try:
            settings = get_settings()
            self._redis = redis.from_url(settings.redis_url, decode_responses=True)
            self._redis.ping()
        except Exception as e:
            logger.warning("Redis indisponível para learning: %s", e)

    def record_decision(self, recruiter_id: str, job_id: str, candidate_id: str,
                        decision: str, context: dict):
        """Record a recruiter decision (approve/reject/adjust) with context."""
        if not self._redis:
            return

        entry = {
            "candidate_id": candidate_id,
            "decision": decision,
            "context": context,
            "timestamp": time.time(),
        }

        key = f"{REDIS_PREFIX}{recruiter_id}:{job_id}"
        try:
            existing = self._redis.get(key)
            decisions = json.loads(existing) if existing else []
            decisions.append(entry)
            # Keep last 100 decisions per job
            if len(decisions) > 100:
                decisions = decisions[-100:]
            self._redis.setex(key, DECISION_TTL, json.dumps(decisions, default=str))
        except Exception as e:
            logger.warning("Erro ao salvar decisão: %s", e)

    def get_patterns(self, recruiter_id: str, job_id: str) -> dict:
        """Analyze decision history and return patterns."""
        if not self._redis:
            return {}

        key = f"{REDIS_PREFIX}{recruiter_id}:{job_id}"
        try:
            data = self._redis.get(key)
            if not data:
                return {}

            decisions = json.loads(data)
            approved = [d for d in decisions if d["decision"] == "approve"]
            rejected = [d for d in decisions if d["decision"] == "reject"]

            patterns = {
                "total_decisions": len(decisions),
                "approved": len(approved),
                "rejected": len(rejected),
                "approval_rate": len(approved) / max(len(decisions), 1),
            }

            # Analyze salary patterns from rejections
            rejected_salaries = [
                d["context"].get("salary") for d in rejected
                if d["context"].get("salary")
            ]
            if rejected_salaries:
                patterns["rejected_salary_avg"] = sum(rejected_salaries) / len(rejected_salaries)

            # Analyze common rejection reasons
            rejection_reasons = {}
            for d in rejected:
                reason = d["context"].get("reason", "não especificado")
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
            if rejection_reasons:
                patterns["top_rejection_reasons"] = sorted(
                    rejection_reasons.items(), key=lambda x: x[1], reverse=True
                )[:5]

            return patterns

        except Exception as e:
            logger.warning("Erro ao buscar padrões: %s", e)
            return {}

    def get_all_patterns(self, recruiter_id: str) -> list[dict]:
        """Get patterns for ALL jobs a recruiter has interacted with.
        Returns list of {"job_id": ..., "patterns": {...}} dicts.
        """
        if not self._redis:
            return []

        results = []
        try:
            prefix = f"{REDIS_PREFIX}{recruiter_id}:"
            for key in self._redis.scan_iter(f"{prefix}*"):
                job_id = key.replace(prefix, "")
                patterns = self.get_patterns(recruiter_id, job_id)
                if patterns and patterns.get("total_decisions", 0) > 0:
                    results.append({"job_id": job_id, "patterns": patterns})
        except Exception as e:
            logger.warning("Erro ao buscar todos os padrões: %s", e)
        return results

    def total_decisions_count(self, recruiter_id: str) -> int:
        """Count total decisions across all jobs for a recruiter."""
        total = 0
        for entry in self.get_all_patterns(recruiter_id):
            total += entry["patterns"].get("total_decisions", 0)
        return total

    def get_all_decisions_summary(self, recruiter_id: str) -> str:
        """Build a text summary of all decisions for Claude to consolidate."""
        if not self._redis:
            return ""

        lines = []
        try:
            prefix = f"{REDIS_PREFIX}{recruiter_id}:"
            for key in self._redis.scan_iter(f"{prefix}*"):
                raw = self._redis.get(key)
                if not raw:
                    continue
                decisions = json.loads(raw)
                for d in decisions[-20:]:  # Last 20 per job
                    ctx = d.get("context", {})
                    line = f"- {d['decision']}"
                    if ctx.get("job_name"):
                        line += f" | vaga: {ctx['job_name']}"
                    if ctx.get("reason"):
                        line += f" | motivo: {ctx['reason']}"
                    if ctx.get("salary"):
                        line += f" | salário: R${ctx['salary']:,.0f}"
                    lines.append(line)
        except Exception as e:
            logger.warning("Erro ao buscar decisões: %s", e)
        return "\n".join(lines[-50:])  # Cap at 50 most recent

    def get_insights_text(self, recruiter_id: str, job_id: str) -> str:
        """Get human-readable insights for Claude to use in shortlist ranking."""
        patterns = self.get_patterns(recruiter_id, job_id)
        if not patterns or patterns.get("total_decisions", 0) < 3:
            return ""

        insights = []
        if patterns.get("rejected_salary_avg"):
            insights.append(
                f"Candidatos com pretensão acima de R${patterns['rejected_salary_avg']:,.0f} "
                f"tendem a ser reprovados nesta vaga."
            )
        if patterns.get("top_rejection_reasons"):
            reasons = ", ".join(r[0] for r in patterns["top_rejection_reasons"][:3])
            insights.append(f"Motivos frequentes de reprovação: {reasons}")
        if patterns.get("approval_rate", 1) < 0.3:
            insights.append("Taxa de aprovação baixa — critérios podem estar rígidos.")

        return "\n".join(insights) if insights else ""

    # --- Alert utility tracking ---

    def record_alert_sent(self, user_id: str, alert_type: str):
        """Record that a proactive alert was sent. Stores timestamp and type
        so we can later check if the recruiter responded within 30 min.
        """
        if not self._redis:
            return
        try:
            key = f"{REDIS_ALERT_LOG_PREFIX}{user_id}:last"
            entry = json.dumps({"type": alert_type, "ts": time.time()})
            # Keep for 1h (enough for the 30min response window + margin)
            self._redis.setex(key, 3600, entry)
        except Exception as e:
            logger.warning("Erro ao registrar alerta enviado: %s", e)

    def check_alert_response(self, user_id: str):
        """Called when recruiter sends a message. If within 30min of the last
        proactive alert, infer the alert was useful and record it.
        """
        if not self._redis:
            return
        try:
            key = f"{REDIS_ALERT_LOG_PREFIX}{user_id}:last"
            raw = self._redis.get(key)
            if not raw:
                return
            entry = json.loads(raw)
            elapsed = time.time() - entry["ts"]
            responded = elapsed <= ALERT_RESPONSE_WINDOW
            self._record_alert_response(user_id, entry["type"], responded)
            # Clear so we don't double-count
            self._redis.delete(key)
        except Exception as e:
            logger.warning("Erro ao verificar resposta ao alerta: %s", e)

    def _record_alert_response(self, user_id: str, alert_type: str, responded: bool):
        """Increment counters for alert type: sent + responded."""
        if not self._redis:
            return
        try:
            key = f"{REDIS_ALERT_STATS_PREFIX}{user_id}:{alert_type}"
            raw = self._redis.get(key)
            stats = json.loads(raw) if raw else {"sent": 0, "responded": 0}
            stats["sent"] += 1
            if responded:
                stats["responded"] += 1
            self._redis.setex(key, ALERT_STATS_TTL, json.dumps(stats))
        except Exception as e:
            logger.warning("Erro ao salvar stats de alerta: %s", e)

    def get_alert_stats(self, user_id: str) -> dict[str, dict]:
        """Get alert response stats for a user. Returns {alert_type: {sent, responded}}."""
        if not self._redis:
            return {}
        results = {}
        try:
            prefix = f"{REDIS_ALERT_STATS_PREFIX}{user_id}:"
            for key in self._redis.scan_iter(f"{prefix}*"):
                alert_type = key.replace(prefix, "")
                raw = self._redis.get(key)
                if raw:
                    results[alert_type] = json.loads(raw)
        except Exception as e:
            logger.warning("Erro ao buscar stats de alertas: %s", e)
        return results

    # --- Confidence engine (auto-advance threshold) ---

    CONFIDENCE_PREFIX = "inhire:confidence:"
    CONFIDENCE_TTL = 86400 * 365  # 1 year

    def _default_confidence(self) -> dict:
        return {
            "auto_advance_threshold": 4.0,
            "learned_threshold": None,
            "decisions_count": 0,
            "approval_rate_above_threshold": 0.0,
            "reversals_count": 0,
            "reversals_recent": 0,
            "auto_advances_recent": 0,
            "last_calibration": None,
            "circuit_breaker_active": False,
        }

    def get_confidence(self, recruiter_id: str) -> dict:
        """Get confidence data for a recruiter."""
        if not self._redis:
            return self._default_confidence()
        try:
            raw = self._redis.get(f"{self.CONFIDENCE_PREFIX}{recruiter_id}")
            if raw:
                data = self._default_confidence()
                data.update(json.loads(raw))
                return data
        except Exception as e:
            logger.warning("Erro ao buscar confidence: %s", e)
        return self._default_confidence()

    def _save_confidence(self, recruiter_id: str, data: dict):
        if not self._redis:
            return
        try:
            self._redis.setex(
                f"{self.CONFIDENCE_PREFIX}{recruiter_id}",
                self.CONFIDENCE_TTL,
                json.dumps(data, default=str),
            )
        except Exception as e:
            logger.warning("Erro ao salvar confidence: %s", e)

    def set_threshold(self, recruiter_id: str, threshold: float):
        """Manually set auto-advance threshold."""
        data = self.get_confidence(recruiter_id)
        data["auto_advance_threshold"] = max(0.0, min(5.0, threshold))
        self._save_confidence(recruiter_id, data)

    def record_reversal(self, recruiter_id: str):
        """Record that the recruiter reversed an auto-advance decision."""
        data = self.get_confidence(recruiter_id)
        data["reversals_count"] = data.get("reversals_count", 0) + 1
        data["reversals_recent"] = data.get("reversals_recent", 0) + 1
        self._save_confidence(recruiter_id, data)
        logger.info("Reversal recorded for %s (total: %d)", recruiter_id, data["reversals_count"])

    def record_auto_advance(self, recruiter_id: str):
        """Record that an auto-advance happened."""
        data = self.get_confidence(recruiter_id)
        data["auto_advances_recent"] = data.get("auto_advances_recent", 0) + 1
        self._save_confidence(recruiter_id, data)

    def should_auto_advance(self, recruiter_id: str, candidate_score: float) -> bool:
        """Check if a candidate should be auto-advanced based on score threshold."""
        data = self.get_confidence(recruiter_id)
        threshold = data.get("auto_advance_threshold", 4.0)
        return candidate_score >= threshold

    def check_circuit_breaker(self, recruiter_id: str) -> bool:
        """Returns True if circuit breaker is active (auto-advance should be disabled).
        Activates if >30% of recent auto-advances were reversed (min 5 advances)."""
        data = self.get_confidence(recruiter_id)
        if data.get("circuit_breaker_active", False):
            return True
        recent_advances = data.get("auto_advances_recent", 0)
        recent_reversals = data.get("reversals_recent", 0)
        if recent_advances >= 5 and recent_reversals / max(recent_advances, 1) > 0.3:
            data["circuit_breaker_active"] = True
            self._save_confidence(recruiter_id, data)
            return True
        return False

    def reset_circuit_breaker(self, recruiter_id: str):
        """Reset circuit breaker (called by recruiter or weekly calibration)."""
        data = self.get_confidence(recruiter_id)
        data["circuit_breaker_active"] = False
        data["reversals_recent"] = 0
        data["auto_advances_recent"] = 0
        self._save_confidence(recruiter_id, data)

    def calibrate(self, recruiter_id: str):
        """Recalculate confidence from decision history. Called weekly by cron."""
        all_patterns = self.get_all_patterns(recruiter_id)
        if not all_patterns:
            return

        data = self.get_confidence(recruiter_id)
        total_decisions = sum(
            entry.get("patterns", {}).get("total_decisions", 0)
            for entry in all_patterns
        )
        data["decisions_count"] = total_decisions

        # Bump threshold if too many reversals
        if data.get("reversals_count", 0) >= 3:
            current = data.get("auto_advance_threshold", 4.0)
            data["auto_advance_threshold"] = min(5.0, current + 0.3)
            data["reversals_count"] = 0

        data["last_calibration"] = time.strftime("%Y-%m-%d")
        data["reversals_recent"] = 0
        data["auto_advances_recent"] = 0
        self._save_confidence(recruiter_id, data)
