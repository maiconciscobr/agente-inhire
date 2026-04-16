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
            "urgency": "alta",
            "seniority": "Sênior",
        }
        mock_conv._context["current_job_name"] = "Dev Python"
        mock_app.state.user_mapping.get_user.return_value = {
            "autonomy_mode": "copilot", "auto_advance_threshold": 4.0,
        }
        mock_app.state.inhire.gen_filter_job_talents.return_value = None
        mock_app.state.inhire.list_job_talents.return_value = []
        mock_app.state.learning = MagicMock()
        mock_app.state.learning.total_decisions_count.return_value = 20

        await _post_creation_chain(mock_conv, mock_app, "C123", "job-1")

        # Should call auto_configure (screening)
        mock_app.state.inhire.configure_screening.assert_called_once()
        # Should send consolidated message with mode suggestion
        assert mock_app.state.slack.send_message.call_count >= 1
        # Check that the message contains mode suggestion
        last_call = mock_app.state.slack.send_message.call_args_list[-1]
        msg = last_call[0][1]
        assert "Recomendo" in msg or "Piloto" in msg or "Copiloto" in msg


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


class TestOfferFlow:
    @pytest.mark.asyncio
    async def test_start_offer_no_job_id(self, mock_conv, mock_app):
        from routers.handlers.interviews import _start_offer_flow
        # No job_id in context — _context starts empty
        await _start_offer_flow(mock_conv, mock_app, "C123", "oferta")
        last_msg = mock_app.state.slack.send_message.call_args[0][1]
        assert "qual vaga" in last_msg.lower() or "ID" in last_msg

    @pytest.mark.asyncio
    async def test_start_offer_no_eligible_candidates(self, mock_conv, mock_app):
        from routers.handlers.interviews import _start_offer_flow
        mock_conv._context["current_job_id"] = "job-1"
        mock_conv._context["current_job_name"] = "Dev Python"
        # All candidates rejected — none eligible
        mock_app.state.inhire.list_job_talents.return_value = [
            {"id": "jt-1", "status": "rejected", "talent": {"name": "Ana"}},
        ]
        await _start_offer_flow(mock_conv, mock_app, "C123", "oferta")
        last_msg = mock_app.state.slack.send_message.call_args[0][1]
        assert "nenhum" in last_msg.lower()

    @pytest.mark.asyncio
    async def test_start_offer_shows_candidates_and_templates(self, mock_conv, mock_app):
        from routers.handlers.interviews import _start_offer_flow
        from services.conversation import FlowState
        mock_conv._context["current_job_id"] = "job-1"
        mock_conv._context["current_job_name"] = "Dev Python"
        # One active, one rejected
        mock_app.state.inhire.list_job_talents.return_value = [
            {"id": "jt-1", "status": "active", "talent": {"name": "Ana Silva"}, "stage": {"name": "Offer"}},
            {"id": "jt-2", "status": "rejected", "talent": {"name": "Pedro"}},
        ]
        mock_app.state.inhire.list_offer_templates.return_value = [{"id": "tpl-1", "name": "CLT Padrão"}]
        mock_app.state.inhire.get_offer_template_detail.return_value = {"variables": [{"name": "salario"}]}

        await _start_offer_flow(mock_conv, mock_app, "C123", "oferta")
        last_msg = mock_app.state.slack.send_message.call_args[0][1]
        assert "Ana Silva" in last_msg
        assert "CLT" in last_msg
        assert mock_conv.state == FlowState.CREATING_OFFER


class TestRejectionFlow:
    @pytest.mark.asyncio
    async def test_reject_no_candidates(self, mock_conv, mock_app):
        from routers.handlers.candidates import _reject_candidates
        from services.conversation import FlowState
        # No candidates in context
        await _reject_candidates(mock_conv, mock_app, "C123")
        last_msg = mock_app.state.slack.send_message.call_args[0][1]
        assert "ninguém" in last_msg.lower() or "não tem" in last_msg.lower()
        assert mock_conv.state == FlowState.IDLE

    @pytest.mark.asyncio
    async def test_reject_calls_bulk_reject(self, mock_conv, mock_app):
        from routers.handlers.candidates import _reject_candidates
        mock_conv._context["candidates_to_reject"] = [
            {"id": "jt-1", "name": "Ana", "score": "3.0", "stage": "Triagem", "location": "SP"},
            {"id": "jt-2", "name": "Pedro", "score": "2.5", "stage": "Triagem", "location": "RJ"},
        ]
        mock_conv._context["current_job_name"] = "Dev Python"
        mock_app.state.claude.generate_rejection_message.return_value = "Devolutiva profissional"
        mock_app.state.claude.classify_rejection_reason.return_value = "underqualified"
        mock_app.state.inhire.bulk_reject.return_value = {"rejected": 2, "total": 2}
        mock_app.state.user_mapping.get_user.return_value = {"comms_enabled": False}

        await _reject_candidates(mock_conv, mock_app, "C123")

        mock_app.state.inhire.bulk_reject.assert_called()
        assert mock_app.state.claude.classify_rejection_reason.call_count == 2

    @pytest.mark.asyncio
    async def test_reject_offers_whatsapp_if_phone_available(self, mock_conv, mock_app):
        from routers.handlers.candidates import _reject_candidates
        mock_conv._context["candidates_to_reject"] = [
            {"id": "jt-1", "name": "Ana", "talent": {"phone": "+5511999990001"}, "score": "3.0", "stage": "Triagem"},
        ]
        mock_conv._context["current_job_name"] = "Dev Python"
        mock_app.state.claude.generate_rejection_message.return_value = "Devolutiva"
        mock_app.state.claude.classify_rejection_reason.return_value = "underqualified"
        mock_app.state.claude.generate_personalized_rejection.return_value = "Mensagem personalizada"
        mock_app.state.inhire.bulk_reject.return_value = {"rejected": 1, "total": 1}
        mock_app.state.user_mapping.get_user.return_value = {"comms_enabled": True}

        await _reject_candidates(mock_conv, mock_app, "C123")

        # Should offer WhatsApp approval via send_approval_request
        mock_app.state.slack.send_approval_request.assert_called_once()
        call_args = mock_app.state.slack.send_approval_request.call_args[0]
        assert "WhatsApp" in call_args[1]


class TestInterviewScheduling:
    @pytest.mark.asyncio
    async def test_propose_with_preferred_slots(self, mock_conv, mock_app):
        from routers.handlers.interviews import _propose_interview_times
        mock_conv._context["current_job_name"] = "Dev Python"
        mock_app.state.user_mapping.get_user.return_value = {
            "preferred_interview_slots": [{"day": "tue", "hour": 14}, {"day": "thu", "hour": 10}],
            "default_interview_duration": 60,
        }
        candidates = [
            {"id": "jt-1", "talent": {"name": "Ana Silva"}},
            {"id": "jt-2", "talent": {"name": "Pedro Santos"}},
        ]
        await _propose_interview_times(mock_conv, mock_app, "C123", candidates)
        last_msg = mock_app.state.slack.send_message.call_args[0][1]
        assert "Ana Silva" in last_msg
        assert "agende assim" in last_msg.lower() or "horários" in last_msg.lower()

    @pytest.mark.asyncio
    async def test_propose_without_slots_asks_recruiter(self, mock_conv, mock_app):
        from routers.handlers.interviews import _propose_interview_times
        mock_conv._context["current_job_name"] = "Dev Python"
        mock_app.state.user_mapping.get_user.return_value = {
            "preferred_interview_slots": [],
        }
        candidates = [
            {"id": "jt-1", "talent": {"name": "Ana Silva"}},
        ]
        await _propose_interview_times(mock_conv, mock_app, "C123", candidates)
        last_msg = mock_app.state.slack.send_message.call_args[0][1]
        assert "horários preferidos" in last_msg.lower() or "melhores horários" in last_msg.lower()

    @pytest.mark.asyncio
    async def test_propose_empty_candidates(self, mock_conv, mock_app):
        from routers.handlers.interviews import _propose_interview_times
        mock_app.state.user_mapping.get_user.return_value = {"preferred_interview_slots": []}
        await _propose_interview_times(mock_conv, mock_app, "C123", [])
        # Should not send any message
        mock_app.state.slack.send_message.assert_not_called()


def _import_webhooks():
    """Import routers.webhooks, mocking fastapi if it's not installed."""
    import sys
    import importlib
    from unittest.mock import MagicMock

    # Stub fastapi if not available (unit-test environment without full deps)
    if "fastapi" not in sys.modules:
        fastapi_stub = MagicMock()
        fastapi_stub.APIRouter = MagicMock(return_value=MagicMock())
        fastapi_stub.Request = MagicMock
        fastapi_stub.Response = MagicMock
        sys.modules["fastapi"] = fastapi_stub

    # Force a fresh import if module is not yet loaded
    if "routers.webhooks" not in sys.modules:
        importlib.import_module("routers.webhooks")

    return sys.modules["routers.webhooks"]


class TestWebhookDetection:
    def test_detect_talent_added(self):
        webhooks = _import_webhooks()
        body = {"talentId": "t1", "jobId": "j1", "stageName": "Listados"}
        assert webhooks._detect_event_type(body) == "JOB_TALENT_ADDED"

    def test_detect_requisition_approved(self):
        webhooks = _import_webhooks()
        body = {"requisitionId": "r1", "approvers": [], "status": "approved"}
        assert webhooks._detect_event_type(body) == "REQUISITION_STATUS_UPDATED"

    def test_detect_form_response(self):
        webhooks = _import_webhooks()
        body = {"formId": "f1", "formResponseId": "fr1"}
        assert webhooks._detect_event_type(body) == "FORM_RESPONSE_ADDED"

    def test_detect_job_updated(self):
        webhooks = _import_webhooks()
        body = {"jobId": "j1", "name": "Dev Python"}
        assert webhooks._detect_event_type(body) == "JOB_UPDATED"

    def test_detect_unknown(self):
        webhooks = _import_webhooks()
        body = {"random": "data"}
        assert webhooks._detect_event_type(body) == "UNKNOWN"


class TestWebhookAutoScreening:
    @pytest.mark.asyncio
    async def test_auto_screen_hunting_candidate(self, mock_app):
        webhooks = _import_webhooks()
        mock_app.state.inhire.manual_screening.return_value = {"score": 4.0}

        payload = {"jobId": "j1", "talentId": "t1", "source": "manual", "stageName": "Listados"}
        await webhooks._handle_talent_added(mock_app, payload)

        # Give the background task a moment (it's create_task)
        import asyncio
        await asyncio.sleep(0.1)
        # manual_screening should have been called
        mock_app.state.inhire.manual_screening.assert_called_once_with("j1*t1")

    @pytest.mark.asyncio
    async def test_organic_candidate_not_screened(self, mock_app):
        webhooks = _import_webhooks()

        payload = {"jobId": "j1", "talentId": "t1", "source": "jobPage", "stageName": "Inscritos"}
        await webhooks._handle_talent_added(mock_app, payload)

        import asyncio
        await asyncio.sleep(0.1)
        # Should NOT auto-screen organic candidates
        mock_app.state.inhire.manual_screening.assert_not_called()


class TestSuggestAutonomyMode:
    def test_urgent_tech_suggests_autopilot(self):
        from routers.handlers.job_creation import _suggest_autonomy_mode
        job_data = {
            "title": "Desenvolvedor Python Senior",
            "urgency": "alta",
            "seniority": "Sênior",
            "salary_range": {"min": 15000, "max": 20000},
            "requirements": ["Python", "FastAPI", "Docker"],
        }
        mode, reason = _suggest_autonomy_mode(job_data, decisions_count=20)
        assert mode == "autopilot"
        assert "urgência alta" in reason

    def test_director_suggests_copilot(self):
        from routers.handlers.job_creation import _suggest_autonomy_mode
        job_data = {
            "title": "Diretor de Engenharia",
            "urgency": "média",
            "seniority": "Diretor",
            "salary_range": {"min": 35000, "max": 50000},
            "requirements": ["Liderança", "Visão estratégica"],
        }
        mode, reason = _suggest_autonomy_mode(job_data, decisions_count=30)
        assert mode == "copilot"
        assert "liderança" in reason or "salário alto" in reason

    def test_new_recruiter_suggests_copilot(self):
        from routers.handlers.job_creation import _suggest_autonomy_mode
        job_data = {
            "title": "Dev Backend",
            "urgency": "alta",
            "seniority": "Pleno",
            "salary_range": {"min": 8000, "max": 12000},
            "requirements": ["Java", "Spring"],
        }
        mode, reason = _suggest_autonomy_mode(job_data, decisions_count=3)
        assert mode == "copilot"
        assert "poucos dados" in reason

    def test_standard_job_experienced_recruiter_suggests_autopilot(self):
        from routers.handlers.job_creation import _suggest_autonomy_mode
        job_data = {
            "title": "Analista de QA",
            "urgency": "alta",
            "seniority": "Pleno",
            "salary_range": {"min": 6000, "max": 10000},
            "requirements": ["Selenium", "Python", "CI/CD"],
        }
        mode, reason = _suggest_autonomy_mode(job_data, decisions_count=25)
        assert mode == "autopilot"


class TestBatchApproval:
    @pytest.mark.asyncio
    async def test_batch_sends_block_when_3_plus_actions(self, mock_conv, mock_app):
        from routers.handlers.helpers import _send_batch_approval

        actions = [
            {"callback_id": "publish_job_approval", "title": "Divulgar no LinkedIn"},
            {"callback_id": "shortlist_approval", "title": "Mover 3 candidatos para Entrevista"},
            {"callback_id": "whatsapp_free_approval", "title": "Enviar shortlist por WhatsApp"},
        ]
        await _send_batch_approval(mock_conv, mock_app.state.slack, "C123", actions)

        mock_app.state.slack.send_message.assert_called_once()
        call_kwargs = mock_app.state.slack.send_message.call_args
        blocks = call_kwargs[1]["blocks"] if "blocks" in (call_kwargs[1] or {}) else call_kwargs[0][2] if len(call_kwargs[0]) > 2 else None
        assert blocks is not None

    @pytest.mark.asyncio
    async def test_batch_stores_pending_in_context(self, mock_conv, mock_app):
        from routers.handlers.helpers import _send_batch_approval

        actions = [
            {"callback_id": "publish_job_approval", "title": "Divulgar no LinkedIn"},
            {"callback_id": "shortlist_approval", "title": "Mover candidatos"},
            {"callback_id": "whatsapp_free_approval", "title": "Enviar WhatsApp"},
        ]
        await _send_batch_approval(mock_conv, mock_app.state.slack, "C123", actions)

        stored = mock_conv._context.get("batch_pending")
        assert stored is not None
        assert len(stored) == 3
        assert stored[0]["callback_id"] == "publish_job_approval"
