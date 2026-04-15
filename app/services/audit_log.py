import json
import logging
import time
from datetime import datetime, timezone, timedelta

import redis

from config import get_settings

logger = logging.getLogger("agente-inhire.audit")

REDIS_PREFIX = "inhire:audit:"
AUDIT_TTL = 86400 * 30  # 30 days
BRT = timezone(timedelta(hours=-3))


class AuditLog:
    """Records autonomous actions for transparency in briefings."""

    def __init__(self):
        self._redis = None
        try:
            settings = get_settings()
            self._redis = redis.from_url(settings.redis_url, decode_responses=True)
            self._redis.ping()
        except Exception as e:
            logger.warning("Redis indisponível para audit log: %s", e)

    def _today_key(self, recruiter_id: str) -> str:
        today = datetime.now(BRT).strftime("%Y-%m-%d")
        return f"{REDIS_PREFIX}{recruiter_id}:{today}"

    def log_action(self, recruiter_id: str, action: str, job_id: str = "",
                   candidate: str = "", detail: str = ""):
        """Log an autonomous action."""
        if not self._redis:
            return
        try:
            key = self._today_key(recruiter_id)
            raw = self._redis.get(key)
            entries = json.loads(raw) if raw else []
            entries.append({
                "ts": time.time(),
                "action": action,
                "job": job_id,
                "candidate": candidate,
                "detail": detail,
            })
            if len(entries) > 200:
                entries = entries[-200:]
            self._redis.setex(key, AUDIT_TTL, json.dumps(entries))
        except Exception as e:
            logger.warning("Erro ao registrar ação no audit log: %s", e)

    def get_recent(self, recruiter_id: str, days: int = 1) -> list[dict]:
        """Get audit entries for the last N days."""
        if not self._redis:
            return []
        entries = []
        try:
            now = datetime.now(BRT)
            for d in range(days):
                date = (now - timedelta(days=d)).strftime("%Y-%m-%d")
                key = f"{REDIS_PREFIX}{recruiter_id}:{date}"
                raw = self._redis.get(key)
                if raw:
                    entries.extend(json.loads(raw))
        except Exception as e:
            logger.warning("Erro ao buscar audit log: %s", e)
        return sorted(entries, key=lambda e: e.get("ts", 0), reverse=True)

    def format_for_briefing(self, recruiter_id: str) -> str:
        """Format recent actions as a readable summary for the daily briefing."""
        entries = self.get_recent(recruiter_id, days=1)
        if not entries:
            return ""
        lines = []
        for e in entries[:15]:
            action = e.get("action", "?")
            detail = e.get("detail", "")
            candidate = e.get("candidate", "")
            label = {
                "auto_screening": "Triagem automática",
                "auto_advance": "Movimentação automática",
                "smart_match": "Smart Match",
                "auto_configure": "Config automática",
                "auto_publish": "Divulgação automática",
                "linkedin_search": "Busca LinkedIn gerada",
                "follow_up": "Follow-up enviado",
            }.get(action, action)
            parts = [f"• {label}"]
            if candidate:
                parts.append(f"({candidate})")
            if detail:
                parts.append(f"— {detail}")
            lines.append(" ".join(parts))
        return "\n".join(lines)
