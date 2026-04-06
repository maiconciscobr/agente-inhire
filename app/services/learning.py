import json
import logging
import time

import redis

from config import get_settings

logger = logging.getLogger("agente-inhire.learning")

REDIS_PREFIX = "inhire:learning:"


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
            self._redis.set(key, json.dumps(decisions, default=str))
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
