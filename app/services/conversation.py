import json
import logging
import time
from enum import Enum
from dataclasses import dataclass, field

import redis

from config import get_settings

logger = logging.getLogger("agente-inhire.conversation")

REDIS_PREFIX = "inhire:conv:"
REDIS_TTL = 86400 * 7  # 7 days
REDIS_FACTS_PREFIX = "inhire:facts:"
REDIS_FACTS_TTL = 86400 * 90  # 90 days
REDIS_PROFILE_PREFIX = "inhire:profile:"
REDIS_SESSION_SUMMARY_PREFIX = "inhire:session_summary:"
REDIS_SESSION_SUMMARY_TTL = 86400 * 30  # 30 days


class FlowState(str, Enum):
    IDLE = "idle"
    # Job creation flow
    COLLECTING_BRIEFING = "collecting_briefing"
    WAITING_JOB_APPROVAL = "waiting_job_approval"
    # Screening flow
    MONITORING_CANDIDATES = "monitoring_candidates"
    WAITING_SHORTLIST_APPROVAL = "waiting_shortlist_approval"
    # Pipeline flow
    WAITING_STAGE_APPROVAL = "waiting_stage_approval"
    WAITING_REJECTION_APPROVAL = "waiting_rejection_approval"
    # Scheduling flow
    SCHEDULING_INTERVIEW = "scheduling_interview"
    # Offer letter flow
    CREATING_OFFER = "creating_offer"
    WAITING_OFFER_APPROVAL = "waiting_offer_approval"
    # WhatsApp communication flow
    WAITING_WHATSAPP_APPROVAL = "waiting_whatsapp_approval"


SUMMARY_THRESHOLD = 20  # Generate summary every N messages
STALE_THRESHOLD = 7200  # 2 hours in seconds


@dataclass
class Conversation:
    user_id: str
    channel_id: str
    state: FlowState = FlowState.IDLE
    messages: list[dict] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    summary: str = ""
    last_activity: float = 0.0
    msgs_since_summary: int = 0

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        self.last_activity = time.time()
        self.msgs_since_summary += 1
        if len(self.messages) > 50:
            self.messages = self.messages[-50:]

    def needs_summary(self) -> bool:
        return self.msgs_since_summary >= SUMMARY_THRESHOLD

    def is_stale(self) -> bool:
        if self.last_activity == 0:
            return False
        return (time.time() - self.last_activity) > STALE_THRESHOLD

    def compress_with_summary(self):
        """Replace message history with summary for stale conversations."""
        if self.summary:
            self.messages = [
                {"role": "assistant", "content": f"[Resumo da conversa anterior]\n{self.summary}"}
            ]
            self.msgs_since_summary = 0

    # Keys that are specific to a job flow and should be cleared when switching jobs
    _JOB_CONTEXT_KEYS = {
        "current_job_name", "job_stages", "job_data", "job_description",
        "shortlist_candidates", "all_applications", "shortlist_summary",
        "next_stage_id", "next_stage_name", "candidates_to_reject",
        "offer_templates", "offer_candidates", "offer_details",
        "schedulable_candidates", "scheduling_job_talent_id",
        "briefing_parts", "analyzed_profile_data", "analyzed_profile_text",
        "whatsapp_pending", "whatsapp_rejection_pending",
        "whatsapp_move_pending", "whatsapp_interview_pending",
    }

    def set_context(self, key: str, value):
        # When switching to a different job, clear stale context from previous job
        if key == "current_job_id" and value != self.context.get("current_job_id"):
            for k in self._JOB_CONTEXT_KEYS:
                self.context.pop(k, None)
        self.context[key] = value

    def get_context(self, key: str, default=None):
        return self.context.get(key, default)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "channel_id": self.channel_id,
            "state": self.state.value,
            "messages": self.messages,
            "context": self.context,
            "summary": self.summary,
            "last_activity": self.last_activity,
            "msgs_since_summary": self.msgs_since_summary,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Conversation":
        return cls(
            user_id=data["user_id"],
            channel_id=data["channel_id"],
            state=FlowState(data.get("state", "idle")),
            messages=data.get("messages", []),
            context=data.get("context", {}),
            summary=data.get("summary", ""),
            last_activity=data.get("last_activity", 0.0),
            msgs_since_summary=data.get("msgs_since_summary", 0),
        )


class ConversationManager:
    """Conversation state manager with Redis persistence."""

    def __init__(self):
        self._conversations: dict[str, Conversation] = {}
        self._redis = None
        try:
            settings = get_settings()
            self._redis = redis.from_url(settings.redis_url, decode_responses=True)
            self._redis.ping()
            logger.info("Redis conectado para persistência de conversas.")
        except Exception as e:
            logger.warning("Redis indisponível, usando apenas memória: %s", e)
            self._redis = None

    def _key(self, user_id: str, channel_id: str) -> str:
        return f"{user_id}:{channel_id}"

    def get_or_create(self, user_id: str, channel_id: str) -> Conversation:
        key = self._key(user_id, channel_id)

        # Check memory first
        if key in self._conversations:
            return self._conversations[key]

        # Try Redis
        if self._redis:
            try:
                data = self._redis.get(f"{REDIS_PREFIX}{key}")
                if data:
                    conv = Conversation.from_dict(json.loads(data))
                    self._conversations[key] = conv
                    return conv
            except Exception as e:
                logger.warning("Erro ao ler do Redis: %s", e)

        # Create new
        conv = Conversation(user_id=user_id, channel_id=channel_id)
        self._conversations[key] = conv
        return conv

    def get(self, user_id: str, channel_id: str) -> Conversation | None:
        return self._conversations.get(self._key(user_id, channel_id))

    def save(self, conv: Conversation):
        """Persist conversation to Redis."""
        if self._redis:
            key = self._key(conv.user_id, conv.channel_id)
            try:
                self._redis.setex(
                    f"{REDIS_PREFIX}{key}",
                    REDIS_TTL,
                    json.dumps(conv.to_dict(), default=str),
                )
            except Exception as e:
                logger.warning("Erro ao salvar no Redis: %s", e)

    def save_facts(self, user_id: str, facts: list[str]):
        """Save extracted facts for a user. Merges with existing, keeps last 20."""
        if not self._redis or not facts:
            return
        try:
            key = f"{REDIS_FACTS_PREFIX}{user_id}"
            existing = self._redis.get(key)
            all_facts = json.loads(existing) if existing else []
            all_facts.extend(facts)
            # Deduplicate and keep last 20
            seen = set()
            unique = []
            for f in reversed(all_facts):
                if f.lower() not in seen:
                    seen.add(f.lower())
                    unique.append(f)
            unique = list(reversed(unique[:20]))
            self._redis.setex(key, REDIS_FACTS_TTL, json.dumps(unique))
        except Exception as e:
            logger.warning("Erro ao salvar fatos: %s", e)

    def get_facts(self, user_id: str) -> list[str]:
        """Get accumulated facts for a user."""
        if not self._redis:
            return []
        try:
            key = f"{REDIS_FACTS_PREFIX}{user_id}"
            data = self._redis.get(key)
            return json.loads(data) if data else []
        except Exception:
            return []

    def save_profile(self, user_id: str, profile: str):
        """Save recruiter profile (no TTL — permanent, refreshed monthly)."""
        if not self._redis or not profile:
            return
        try:
            self._redis.set(f"{REDIS_PROFILE_PREFIX}{user_id}", profile)
        except Exception as e:
            logger.warning("Erro ao salvar perfil: %s", e)

    def get_profile(self, user_id: str) -> str:
        """Get recruiter profile."""
        if not self._redis:
            return ""
        try:
            return self._redis.get(f"{REDIS_PROFILE_PREFIX}{user_id}") or ""
        except Exception:
            return ""

    def save_session_summary(self, user_id: str, summary: str):
        """Save session summary. Keeps last 10 sessions."""
        if not self._redis or not summary:
            return
        try:
            key = f"{REDIS_SESSION_SUMMARY_PREFIX}{user_id}"
            self._redis.lpush(key, summary)
            self._redis.ltrim(key, 0, 9)  # Keep last 10
            self._redis.expire(key, REDIS_SESSION_SUMMARY_TTL)
        except Exception as e:
            logger.warning("Erro ao salvar resumo de sessão: %s", e)

    def get_last_session_summary(self, user_id: str) -> str:
        """Get most recent session summary."""
        if not self._redis:
            return ""
        try:
            key = f"{REDIS_SESSION_SUMMARY_PREFIX}{user_id}"
            items = self._redis.lrange(key, 0, 0)
            return items[0] if items else ""
        except Exception:
            return ""

    def reset(self, user_id: str, channel_id: str):
        key = self._key(user_id, channel_id)
        if key in self._conversations:
            self._conversations[key].state = FlowState.IDLE
            self._conversations[key].context = {}
            self._conversations[key].messages = []
            self.save(self._conversations[key])
        if self._redis:
            try:
                self._redis.delete(f"{REDIS_PREFIX}{key}")
            except Exception:
                pass

