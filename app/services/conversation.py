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


class FlowState(str, Enum):
    IDLE = "idle"
    # Job creation flow
    COLLECTING_BRIEFING = "collecting_briefing"
    WAITING_TECHNICAL_INPUT = "waiting_technical_input"
    REVIEWING_JOB_DRAFT = "reviewing_job_draft"
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

    def set_context(self, key: str, value):
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
