import logging

from slack_sdk.web.async_client import AsyncWebClient

from config import Settings

logger = logging.getLogger("agente-inhire.slack")

SLACK_MAX_TEXT = 3900  # Slack limit is 4000, leave margin


class SlackService:
    """Wrapper around Slack Web API for sending messages."""

    def __init__(self, settings: Settings):
        self.client = AsyncWebClient(token=settings.slack_bot_token)

    async def send_message(self, channel: str, text: str, blocks: list | None = None):
        """Send message, splitting into multiple if text exceeds Slack limit."""
        logger.info("Enviando mensagem para %s", channel)

        if len(text) <= SLACK_MAX_TEXT:
            return await self.client.chat_postMessage(
                channel=channel, text=text, blocks=blocks
            )

        # Split long messages into chunks
        chunks = _split_text(text, SLACK_MAX_TEXT)
        result = None
        for i, chunk in enumerate(chunks):
            # Only send blocks with the first chunk
            b = blocks if i == 0 else None
            result = await self.client.chat_postMessage(
                channel=channel, text=chunk, blocks=b
            )
        return result

    async def send_approval_request(
        self, channel: str, title: str, details: str, callback_id: str
    ):
        """Send a message with approval buttons."""
        # Truncate details for blocks (Slack block text limit is 3000)
        truncated = details[:2900] + "\n..." if len(details) > 2900 else details

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🔔 {title}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": truncated},
            },
            {
                "type": "actions",
                "block_id": callback_id,
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Aprovar"},
                        "style": "primary",
                        "action_id": "approve",
                        "value": callback_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✏️ Ajustar"},
                        "action_id": "adjust",
                        "value": callback_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Rejeitar"},
                        "style": "danger",
                        "action_id": "reject",
                        "value": callback_id,
                    },
                ],
            },
        ]
        return await self.send_message(channel, text=title, blocks=blocks)

    async def get_user_info(self, user_id: str) -> dict:
        resp = await self.client.users_info(user=user_id)
        return resp["user"]


def _split_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks, preferring line breaks."""
    chunks = []
    while len(text) > max_len:
        # Find last newline before limit
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1 or split_at < max_len // 2:
            # No good newline, split at space
            split_at = text.rfind(" ", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    if text:
        chunks.append(text)
    return chunks
