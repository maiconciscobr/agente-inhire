"""Unit tests for autonomy approval flow and undo button (Gap 5)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from services.conversation import FlowState


class TestRequestOrAutoApprove:
    @pytest.mark.asyncio
    async def test_copilot_shows_approval(self, mock_conv, mock_app):
        from routers.handlers.helpers import _request_or_auto_approve
        mock_app.state.user_mapping.get_user.return_value = {"autonomy_mode": "copilot"}
        execute_fn = AsyncMock()

        await _request_or_auto_approve(
            mock_conv, mock_app, "C123",
            action="move_candidates",
            title="Mover candidatos?",
            details="5 candidatos para Entrevista",
            callback_id="shortlist_approval",
            execute_fn=execute_fn,
            flow_state=FlowState.WAITING_SHORTLIST_APPROVAL,
        )

        # Should NOT execute
        execute_fn.assert_not_called()
        # Should show approval
        mock_app.state.slack.send_approval_request.assert_called_once()
        # Should set flow state
        assert mock_conv.state == FlowState.WAITING_SHORTLIST_APPROVAL

    @pytest.mark.asyncio
    async def test_autopilot_executes_directly(self, mock_conv, mock_app):
        from routers.handlers.helpers import _request_or_auto_approve
        mock_app.state.user_mapping.get_user.return_value = {"autonomy_mode": "autopilot"}
        mock_app.state.learning = MagicMock()
        mock_app.state.learning.check_circuit_breaker.return_value = False
        mock_app.state.audit_log = MagicMock()
        execute_fn = AsyncMock()

        await _request_or_auto_approve(
            mock_conv, mock_app, "C123",
            action="move_candidates",
            title="Mover?",
            details="5 candidatos",
            callback_id="shortlist_approval",
            execute_fn=execute_fn,
        )

        # Should execute directly
        execute_fn.assert_called_once()
        # Should NOT show approval
        mock_app.state.slack.send_approval_request.assert_not_called()
        # Should log to audit
        mock_app.state.audit_log.log_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_autopilot_with_circuit_breaker_shows_approval(self, mock_conv, mock_app):
        from routers.handlers.helpers import _request_or_auto_approve
        mock_app.state.user_mapping.get_user.return_value = {"autonomy_mode": "autopilot"}
        mock_app.state.learning = MagicMock()
        mock_app.state.learning.check_circuit_breaker.return_value = True  # Breaker active!
        execute_fn = AsyncMock()

        await _request_or_auto_approve(
            mock_conv, mock_app, "C123",
            action="move_candidates",
            title="Mover?",
            details="5 candidatos",
            callback_id="shortlist_approval",
            execute_fn=execute_fn,
            flow_state=FlowState.WAITING_SHORTLIST_APPROVAL,
        )

        # Circuit breaker active → should NOT execute
        execute_fn.assert_not_called()
        # Should show approval instead
        mock_app.state.slack.send_approval_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_reject_always_shows_approval(self, mock_conv, mock_app):
        from routers.handlers.helpers import _request_or_auto_approve
        mock_app.state.user_mapping.get_user.return_value = {"autonomy_mode": "autopilot"}
        execute_fn = AsyncMock()

        await _request_or_auto_approve(
            mock_conv, mock_app, "C123",
            action="reject_candidates",
            title="Reprovar?",
            details="3 candidatos",
            callback_id="rejection_approval",
            execute_fn=execute_fn,
            flow_state=FlowState.WAITING_REJECTION_APPROVAL,
        )

        # Reject ALWAYS needs approval, even in autopilot
        execute_fn.assert_not_called()
        mock_app.state.slack.send_approval_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_autopilot_whatsapp_auto_sends(self, mock_conv, mock_app):
        from routers.handlers.helpers import _request_or_auto_approve
        mock_app.state.user_mapping.get_user.return_value = {"autonomy_mode": "autopilot"}
        mock_app.state.learning = MagicMock()
        mock_app.state.learning.check_circuit_breaker.return_value = False
        mock_app.state.audit_log = MagicMock()
        execute_fn = AsyncMock()

        await _request_or_auto_approve(
            mock_conv, mock_app, "C123",
            action="send_whatsapp",
            title="Enviar WhatsApp?",
            details="Mensagem para Ana",
            callback_id="whatsapp_free_approval",
            execute_fn=execute_fn,
        )

        # Autopilot allows WhatsApp auto-send
        execute_fn.assert_called_once()


class TestSendWithUndo:
    @pytest.mark.asyncio
    async def test_sends_message_with_undo_button(self, mock_conv, mock_app):
        from routers.handlers.helpers import _send_with_undo
        slack = mock_app.state.slack

        await _send_with_undo(mock_conv, slack, "C123", "Movi Ana ✓", "undo_auto_advance:jt-1")

        slack.send_message.assert_called_once()
        call_args = slack.send_message.call_args
        # blocks can be positional or keyword
        blocks = call_args.kwargs.get("blocks") or (
            call_args.args[2] if len(call_args.args) > 2 else None
        )
        assert blocks is not None, "send_message should be called with blocks"
        # Check undo button exists in blocks
        found_undo = False
        for block in blocks:
            if block.get("type") == "actions":
                for elem in block.get("elements", []):
                    if "Desfazer" in str(elem):
                        found_undo = True
        assert found_undo, "Undo button not found in blocks"
