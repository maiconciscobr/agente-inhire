import json
import logging

import redis

from config import get_settings

logger = logging.getLogger("agente-inhire.user-mapping")

REDIS_PREFIX = "inhire:user:"


class UserMapping:
    """Maps Slack user IDs to InHire user profiles. Persisted in Redis."""

    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._redis = None
        try:
            settings = get_settings()
            self._redis = redis.from_url(settings.redis_url, decode_responses=True)
            self._redis.ping()
        except Exception as e:
            logger.warning("Redis indisponível para user mapping: %s", e)

    def get_user(self, slack_user_id: str) -> dict | None:
        """Get InHire user info for a Slack user."""
        if slack_user_id in self._cache:
            return self._cache[slack_user_id]
        if self._redis:
            try:
                data = self._redis.get(f"{REDIS_PREFIX}{slack_user_id}")
                if data:
                    user = json.loads(data)
                    self._cache[slack_user_id] = user
                    return user
            except Exception:
                pass
        return None

    # Default settings per recruiter (overridable)
    DEFAULT_SETTINGS = {
        "working_hours_start": 8,
        "working_hours_end": 19,
        "working_days": [0, 1, 2, 3, 4],  # Mon-Fri
        "daily_briefing_time": 9,
        "max_proactive_messages": 3,
        "stale_threshold_days": 3,
        "reminder_interval_days": 7,
        "comms_enabled": True,
    }

    def register_user(self, slack_user_id: str, inhire_email: str, inhire_name: str,
                      inhire_user_id: str = "") -> dict:
        """Register a Slack user with their InHire profile and default settings."""
        user = {
            "slack_user_id": slack_user_id,
            "inhire_email": inhire_email,
            "inhire_name": inhire_name,
            "inhire_user_id": inhire_user_id,
            **self.DEFAULT_SETTINGS,
        }
        self._cache[slack_user_id] = user
        if self._redis:
            try:
                self._redis.set(
                    f"{REDIS_PREFIX}{slack_user_id}",
                    json.dumps(user),
                )
            except Exception as e:
                logger.warning("Erro ao salvar user mapping: %s", e)
        logger.info("Usuário mapeado: %s → %s (%s)", slack_user_id, inhire_name, inhire_email)
        return user

    def get_all_users(self) -> list[dict]:
        """Get all registered users."""
        users = list(self._cache.values())
        if self._redis and not users:
            try:
                for key in self._redis.scan_iter(f"{REDIS_PREFIX}*"):
                    data = self._redis.get(key)
                    if data:
                        user = json.loads(data)
                        self._cache[user["slack_user_id"]] = user
                        users.append(user)
            except Exception:
                pass
        return users

    def set_comms_enabled(self, slack_user_id: str, enabled: bool):
        """Toggle candidate communication for a user."""
        user = self.get_user(slack_user_id)
        if user:
            user["comms_enabled"] = enabled
            self._cache[slack_user_id] = user
            if self._redis:
                try:
                    self._redis.set(f"{REDIS_PREFIX}{slack_user_id}", json.dumps(user))
                except Exception:
                    pass

    def update_settings(self, slack_user_id: str, **kwargs):
        """Update per-recruiter settings (working_hours_start, stale_threshold_days, etc.)."""
        user = self.get_user(slack_user_id)
        if not user:
            return
        valid_keys = set(self.DEFAULT_SETTINGS.keys())
        for key, value in kwargs.items():
            if key in valid_keys:
                user[key] = value
        self._cache[slack_user_id] = user
        if self._redis:
            try:
                self._redis.set(f"{REDIS_PREFIX}{slack_user_id}", json.dumps(user))
            except Exception:
                pass

    def get_setting(self, slack_user_id: str, key: str):
        """Get a per-recruiter setting, falling back to default."""
        user = self.get_user(slack_user_id)
        if user and key in user:
            return user[key]
        return self.DEFAULT_SETTINGS.get(key)

    def is_registered(self, slack_user_id: str) -> bool:
        return self.get_user(slack_user_id) is not None
