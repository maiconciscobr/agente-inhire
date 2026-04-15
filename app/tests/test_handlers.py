"""Unit tests for handler functions — verifies business logic without real API calls."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from services.conversation import FlowState


class TestDuplicateJob:
    @pytest.mark.asyncio
    async def test_duplicate_job_success(self, mock_conv, mock_app):
        from routers.handlers.hunting import _duplicate_job

        mock_conv._context["current_job_id"] = "job-1"
        await _duplicate_job(mock_conv, mock_app, "C123", {"job_id": "job-1"})

        mock_app.state.inhire.duplicate_job.assert_called_once_with("job-1")
        # Should set new job as current context
        assert mock_conv._context["current_job_id"] == "job-2"
        # Should send messages via send_message (not post_message)
        assert mock_app.state.slack.send_message.call_count >= 2

    @pytest.mark.asyncio
    async def test_duplicate_job_no_id(self, mock_conv, mock_app):
        from routers.handlers.hunting import _duplicate_job

        await _duplicate_job(mock_conv, mock_app, "C123", {})

        mock_app.state.inhire.duplicate_job.assert_not_called()
        mock_app.state.slack.send_message.assert_called_once()


class TestNpsSurvey:
    @pytest.mark.asyncio
    async def test_send_survey(self, mock_conv, mock_app):
        from routers.handlers.hunting import _handle_nps_survey

        mock_conv._context["current_job_id"] = "job-1"
        await _handle_nps_survey(mock_conv, mock_app, "C123", {"action": "enviar"})

        mock_app.state.inhire.create_survey.assert_called_once_with("job-1")

    @pytest.mark.asyncio
    async def test_view_metrics(self, mock_conv, mock_app):
        from routers.handlers.hunting import _handle_nps_survey

        mock_conv._context["current_job_id"] = "job-1"
        await _handle_nps_survey(mock_conv, mock_app, "C123", {"action": "metricas"})

        mock_app.state.inhire.get_survey_metrics.assert_called_once_with("job-1")

    @pytest.mark.asyncio
    async def test_no_metrics_yet(self, mock_conv, mock_app):
        from routers.handlers.hunting import _handle_nps_survey

        mock_conv._context["current_job_id"] = "job-1"
        mock_app.state.inhire.get_survey_metrics.return_value = None
        await _handle_nps_survey(mock_conv, mock_app, "C123", {"action": "metricas"})

        # Should inform no results via send_message
        last_msg = mock_app.state.slack.send_message.call_args[0][1]
        assert "não tem" in last_msg.lower() or "ainda" in last_msg.lower()


class TestSendTest:
    @pytest.mark.asyncio
    async def test_send_disc(self, mock_conv, mock_app):
        from routers.handlers.interviews import _send_test

        mock_conv._context["current_job_id"] = "job-1"
        await _send_test(mock_conv, mock_app, "C123", {
            "test_type": "disc", "candidate_name": "João",
        })

        mock_app.state.inhire.send_disc_email.assert_called_once()
        call_args = mock_app.state.inhire.send_disc_email.call_args[0]
        assert "job-1*talent-1" in call_args[0]

    @pytest.mark.asyncio
    async def test_send_disc_all(self, mock_conv, mock_app):
        from routers.handlers.interviews import _send_test

        mock_conv._context["current_job_id"] = "job-1"
        await _send_test(mock_conv, mock_app, "C123", {
            "test_type": "disc", "candidate_name": "todos",
        })

        call_args = mock_app.state.inhire.send_disc_email.call_args[0]
        assert len(call_args[0]) == 2  # both candidates

    @pytest.mark.asyncio
    async def test_send_screening_form(self, mock_conv, mock_app):
        from routers.handlers.interviews import _send_test

        mock_conv._context["current_job_id"] = "job-1"
        await _send_test(mock_conv, mock_app, "C123", {
            "test_type": "screening", "candidate_name": "todos",
        })

        mock_app.state.inhire.send_form_email.assert_called_once()


class TestEvaluateInterview:
    @pytest.mark.asyncio
    async def test_evaluate_with_feedback(self, mock_conv, mock_app):
        from routers.handlers.interviews import _evaluate_interview

        mock_conv._context["current_job_id"] = "job-1"
        mock_conv._context["current_job_name"] = "Dev Python"

        # Claude parses feedback into structured scores
        mock_app.state.claude.chat.return_value = (
            '{"scores": [{"criteriaId": "sk-1", "criteriaName": "Python", "score": 5, "comment": "Excelente"}, '
            '{"criteriaId": "sk-2", "criteriaName": "FastAPI", "score": 4, "comment": "Bom"}], '
            '"recommendation": "advance", "overallComment": "Candidato forte"}'
        )

        await _evaluate_interview(mock_conv, mock_app, "C123", {
            "feedback_text": "João foi excelente em Python (5/5), bom em FastAPI (4/5), recomendo avançar",
            "candidate_name": "João",
        })

        # Should submit to InHire
        mock_app.state.inhire.submit_scorecard_evaluation.assert_called_once()
        # Should send result messages via send_message
        assert mock_app.state.slack.send_message.call_count >= 2

    @pytest.mark.asyncio
    async def test_evaluate_no_scorecard(self, mock_conv, mock_app):
        from routers.handlers.interviews import _evaluate_interview

        mock_conv._context["current_job_id"] = "job-1"
        mock_app.state.inhire.get_job_scorecard.return_value = None

        await _evaluate_interview(mock_conv, mock_app, "C123", {
            "feedback_text": "Foi bem",
        })

        mock_app.state.inhire.submit_scorecard_evaluation.assert_not_called()


class TestAutoConfigureJob:
    @pytest.mark.asyncio
    async def test_configures_screening_scorecard_and_form(self, mock_conv, mock_app):
        from routers.handlers.job_creation import _auto_configure_job

        mock_conv._context["job_data"] = {
            "requirements": ["Python", "FastAPI"],
            "salary_range": {"min": 10000, "max": 15000},
        }
        mock_conv._context["current_job_name"] = "Dev Python"

        result = await _auto_configure_job(mock_conv, mock_app, "C123", "job-1")

        mock_app.state.inhire.configure_screening.assert_called_once()
        mock_app.state.inhire.create_job_scorecard.assert_called_once()
        mock_app.state.inhire.generate_subscription_form.assert_called_once_with("job-1")
        assert "triagem IA" in result
        assert "scorecard" in result
        assert "formulário de inscrição (IA)" in result


class TestConversationStates:
    def test_flow_states_are_clean(self):
        """Verify no orphan states exist."""
        from services.conversation import FlowState

        # These should NOT exist anymore
        state_names = [s.name for s in FlowState]
        assert "WAITING_TECHNICAL_INPUT" not in state_names
        assert "REVIEWING_JOB_DRAFT" not in state_names

        # These should exist
        assert "IDLE" in state_names
        assert "COLLECTING_BRIEFING" in state_names
        assert "SCHEDULING_INTERVIEW" in state_names
        assert "CREATING_OFFER" in state_names


class TestToolDefinitions:
    def test_all_tools_have_required_fields(self):
        from services.claude_client import ELI_TOOLS

        for tool in ELI_TOOLS:
            assert "name" in tool, f"Tool missing name: {tool}"
            assert "description" in tool, f"Tool {tool['name']} missing description"
            assert "input_schema" in tool, f"Tool {tool['name']} missing input_schema"
            assert tool["input_schema"]["type"] == "object"

    def test_tool_count(self):
        from services.claude_client import ELI_TOOLS

        assert len(ELI_TOOLS) == 27, f"Expected 27 tools, got {len(ELI_TOOLS)}"

    def test_new_tools_exist(self):
        from services.claude_client import ELI_TOOLS

        tool_names = {t["name"] for t in ELI_TOOLS}
        new_tools = {"duplicar_vaga", "avaliar_entrevista", "enviar_teste", "pesquisa_candidato"}
        assert new_tools.issubset(tool_names), f"Missing tools: {new_tools - tool_names}"

    def test_conversa_livre_is_last(self):
        """conversa_livre must be last (fallback)."""
        from services.claude_client import ELI_TOOLS

        assert ELI_TOOLS[-1]["name"] == "conversa_livre"


class TestAutonomySettings:
    def test_default_settings_include_autonomy(self):
        from services.user_mapping import UserMapping
        defaults = UserMapping.DEFAULT_SETTINGS
        assert defaults["autonomy_mode"] == "copilot"
        assert defaults["auto_advance_threshold"] == 4.0
        assert defaults["followup_intensity"] == "normal"
        assert defaults["realtime_notifications"] is True
        assert defaults["daily_briefing"] is True
        assert defaults["preferred_interview_slots"] == []
        assert defaults["default_interview_duration"] == 60
        assert defaults["notification_mode"] == "realtime"
        assert defaults["muted_until"] is None


class TestShouldAutoApprove:
    def test_copilot_blocks_move(self, mock_app):
        from routers.handlers.helpers import _should_auto_approve
        user = {"autonomy_mode": "copilot", "auto_advance_threshold": 4.0}
        assert _should_auto_approve(user, "move_candidates") is False

    def test_copilot_allows_screening(self, mock_app):
        from routers.handlers.helpers import _should_auto_approve
        user = {"autonomy_mode": "copilot", "auto_advance_threshold": 4.0}
        assert _should_auto_approve(user, "auto_screening") is True

    def test_copilot_allows_smart_match(self, mock_app):
        from routers.handlers.helpers import _should_auto_approve
        user = {"autonomy_mode": "copilot", "auto_advance_threshold": 4.0}
        assert _should_auto_approve(user, "smart_match") is True

    def test_autopilot_allows_move(self, mock_app):
        from routers.handlers.helpers import _should_auto_approve
        user = {"autonomy_mode": "autopilot", "auto_advance_threshold": 4.0}
        assert _should_auto_approve(user, "move_candidates") is True

    def test_autopilot_allows_publish(self, mock_app):
        from routers.handlers.helpers import _should_auto_approve
        user = {"autonomy_mode": "autopilot", "auto_advance_threshold": 4.0}
        assert _should_auto_approve(user, "publish_job") is True

    def test_neither_mode_allows_reject(self, mock_app):
        from routers.handlers.helpers import _should_auto_approve
        user_cp = {"autonomy_mode": "copilot", "auto_advance_threshold": 4.0}
        user_ap = {"autonomy_mode": "autopilot", "auto_advance_threshold": 4.0}
        assert _should_auto_approve(user_cp, "reject_candidates") is False
        assert _should_auto_approve(user_ap, "reject_candidates") is False

    def test_neither_mode_allows_offer(self, mock_app):
        from routers.handlers.helpers import _should_auto_approve
        user_cp = {"autonomy_mode": "copilot", "auto_advance_threshold": 4.0}
        user_ap = {"autonomy_mode": "autopilot", "auto_advance_threshold": 4.0}
        assert _should_auto_approve(user_cp, "send_offer") is False
        assert _should_auto_approve(user_ap, "send_offer") is False

    def test_copilot_blocks_external_comms(self, mock_app):
        from routers.handlers.helpers import _should_auto_approve
        user = {"autonomy_mode": "copilot", "auto_advance_threshold": 4.0}
        assert _should_auto_approve(user, "send_whatsapp") is False
        assert _should_auto_approve(user, "send_email") is False

    def test_autopilot_allows_external_comms(self, mock_app):
        from routers.handlers.helpers import _should_auto_approve
        user = {"autonomy_mode": "autopilot", "auto_advance_threshold": 4.0}
        assert _should_auto_approve(user, "send_whatsapp") is True
        assert _should_auto_approve(user, "send_email") is True

    def test_circuit_breaker_blocks_move(self, mock_app):
        from routers.handlers.helpers import _should_auto_approve
        user = {"autonomy_mode": "autopilot", "auto_advance_threshold": 4.0}
        mock_learning = MagicMock()
        mock_learning.check_circuit_breaker.return_value = True
        assert _should_auto_approve(user, "move_candidates", learning=mock_learning, recruiter_id="u1") is False

    def test_no_circuit_breaker_allows_move(self, mock_app):
        from routers.handlers.helpers import _should_auto_approve
        user = {"autonomy_mode": "autopilot", "auto_advance_threshold": 4.0}
        mock_learning = MagicMock()
        mock_learning.check_circuit_breaker.return_value = False
        assert _should_auto_approve(user, "move_candidates", learning=mock_learning, recruiter_id="u1") is True

    def test_circuit_breaker_blocks_auto_advance(self, mock_app):
        from routers.handlers.helpers import _should_auto_approve
        user = {"autonomy_mode": "autopilot", "auto_advance_threshold": 4.0}
        mock_learning = MagicMock()
        mock_learning.check_circuit_breaker.return_value = True
        assert _should_auto_approve(user, "auto_advance", learning=mock_learning, recruiter_id="u1") is False

    def test_no_learning_service_allows_move(self, mock_app):
        from routers.handlers.helpers import _should_auto_approve
        user = {"autonomy_mode": "autopilot", "auto_advance_threshold": 4.0}
        # Without learning service, should still allow
        assert _should_auto_approve(user, "move_candidates") is True


class TestModoAutonomiaTool:
    def test_tool_exists(self):
        from services.claude_client import ELI_TOOLS
        tool_names = {t["name"] for t in ELI_TOOLS}
        assert "modo_autonomia" in tool_names

    def test_tool_schema(self):
        from services.claude_client import ELI_TOOLS
        tool = next(t for t in ELI_TOOLS if t["name"] == "modo_autonomia")
        props = tool["input_schema"]["properties"]
        assert "mode" in props
        assert "threshold" in props
        assert "mute_hours" in props


class TestPostCreationChain:
    @pytest.mark.asyncio
    async def test_chain_runs_config_and_sends_message(self, mock_conv, mock_app):
        from routers.handlers.job_creation import _post_creation_chain

        mock_conv._context["job_data"] = {
            "title": "Dev Python",
            "requirements": ["Python", "FastAPI"],
            "salary_range": {"min": 10000, "max": 15000},
        }
        mock_conv._context["current_job_name"] = "Dev Python"
        mock_app.state.user_mapping.get_user.return_value = {
            "autonomy_mode": "copilot", "auto_advance_threshold": 4.0,
        }
        mock_app.state.inhire.gen_filter_job_talents.return_value = None
        mock_app.state.inhire.list_job_talents.return_value = []

        await _post_creation_chain(mock_conv, mock_app, "C123", "job-1")

        # Should call auto_configure (screening)
        mock_app.state.inhire.configure_screening.assert_called_once()
        # Should send consolidated message
        assert mock_app.state.slack.send_message.call_count >= 1


class TestIsMuted:
    def test_not_muted_when_none(self):
        from routers.handlers.helpers import _is_muted
        assert _is_muted({"muted_until": None}) is False

    def test_not_muted_when_empty(self):
        from routers.handlers.helpers import _is_muted
        assert _is_muted({}) is False

    def test_muted_when_future(self):
        from routers.handlers.helpers import _is_muted
        from datetime import datetime, timedelta, timezone
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        assert _is_muted({"muted_until": future}) is True

    def test_not_muted_when_past(self):
        from routers.handlers.helpers import _is_muted
        from datetime import datetime, timedelta, timezone
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert _is_muted({"muted_until": past}) is False
