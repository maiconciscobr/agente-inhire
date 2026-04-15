"""Unit tests for InHireClient — verifies all endpoints use correct paths and methods."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.inhire_client import InHireClient, WhatsAppWindowExpired, WhatsAppInvalidPhone


@pytest.fixture
def client():
    settings = MagicMock()
    settings.inhire_api_url = "https://api.inhire.app"
    auth = AsyncMock()
    auth.headers = {"Authorization": "Bearer test", "X-Tenant": "demo"}
    auth.tenant = "demo"
    auth.ensure_valid_token = AsyncMock()
    return InHireClient(settings, auth)


class TestJobEndpoints:
    @pytest.mark.asyncio
    async def test_create_job(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"id": "j1"}
            result = await client.create_job({"name": "Dev"})
            mock_req.assert_called_once_with("POST", "/jobs", json={"name": "Dev"})
            assert result["id"] == "j1"

    @pytest.mark.asyncio
    async def test_duplicate_job(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"id": "j2"}
            result = await client.duplicate_job("j1")
            mock_req.assert_called_once_with("POST", "/jobs/duplicate", json={"jobId": "j1"})
            assert result["id"] == "j2"

    @pytest.mark.asyncio
    async def test_list_job_templates(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = [{"id": "tpl1"}]
            result = await client.list_job_templates()
            mock_req.assert_called_once_with("GET", "/jobs/templates")
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_list_job_talents_uses_correct_endpoint(self, client):
        """CRITICAL: Must use /job-talents/{id}/talents, NOT /applications."""
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = [{"id": "jt1"}]
            await client.list_job_talents("job-1")
            mock_req.assert_called_once_with("GET", "/job-talents/job-1/talents")


class TestCandidateMovement:
    @pytest.mark.asyncio
    async def test_move_candidate(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            await client.move_candidate("jt-1", "stage-2")
            mock_req.assert_called_once_with(
                "POST", "/job-talents/talents/jt-1/stages", json={"stageId": "stage-2"}
            )

    @pytest.mark.asyncio
    async def test_move_batch(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            await client.move_candidates_batch("stage-2", ["jt-1", "jt-2"])
            call_args = mock_req.call_args
            assert call_args[0][0] == "POST"
            assert call_args[0][1] == "/job-talents/talents/stages/batch"
            assert call_args[1]["json"]["stageId"] == "stage-2"
            assert len(call_args[1]["json"]["jobTalents"]) == 2

    @pytest.mark.asyncio
    async def test_reject_candidate(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            await client.reject_candidate("jt-1", reason="underqualified", comment="Falta XP")
            call_args = mock_req.call_args
            assert call_args[0][1] == "/job-talents/talents/jt-1/statuses"
            assert call_args[1]["json"]["status"] == "rejected"


class TestFormEndpoints:
    @pytest.mark.asyncio
    async def test_generate_subscription_form(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"id": "form-1"}
            result = await client.generate_subscription_form("j1")
            mock_req.assert_called_once_with(
                "POST", "/forms/ai/generate-subscription-form", json={"jobId": "j1"}
            )
            assert result["id"] == "form-1"

    @pytest.mark.asyncio
    async def test_get_interview_kit(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"questions": []}
            result = await client.get_interview_kit("sc-1", "jt-1")
            mock_req.assert_called_once_with(
                "GET", "/forms/scorecards/interview-kit-fill/sc-1/jobTalent/jt-1"
            )

    @pytest.mark.asyncio
    async def test_submit_scorecard(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            payload = {"scores": [{"criteriaId": "c1", "score": 4}]}
            await client.submit_scorecard_evaluation("jt-1", "int-1", payload)
            mock_req.assert_called_once_with(
                "POST", "/forms/scorecards/jobTalent/jt-1/int-1", json=payload
            )

    @pytest.mark.asyncio
    async def test_send_disc(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            await client.send_disc_email(["jt-1", "jt-2"])
            mock_req.assert_called_once_with(
                "POST", "/forms/comms/disc/send/email", json={"jobTalentIds": ["jt-1", "jt-2"]}
            )

    @pytest.mark.asyncio
    async def test_survey_metrics(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"nps": 72}
            result = await client.get_survey_metrics("j1")
            mock_req.assert_called_once_with("GET", "/forms/surveys/jobs/j1/metrics")
            assert result["nps"] == 72


class TestWebhookEndpoints:
    @pytest.mark.asyncio
    async def test_register_webhook_includes_rules(self, client):
        """CRITICAL: rules: {} must always be sent (InHire bug)."""
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"id": "wh-1"}
            await client.register_webhook("https://url", "JOB_TALENT_ADDED", "test")
            payload = mock_req.call_args[1]["json"]
            assert "rules" in payload
            assert payload["rules"] == {}


class TestOfferEndpoints:
    @pytest.mark.asyncio
    async def test_get_offer_template_detail(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"id": "tpl-1", "variables": []}
            result = await client.get_offer_template_detail("tpl-1")
            mock_req.assert_called_once_with("GET", "/offer-letters/templates/tpl-1")


class TestTalentEndpoints:
    @pytest.mark.asyncio
    async def test_react_to_candidate(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            await client.react_to_candidate("jt-1", "like")
            mock_req.assert_called_once_with(
                "POST", "/job-talents/reaction/jt-1", json={"reaction": "like"}
            )

    @pytest.mark.asyncio
    async def test_get_talent_by_linkedin(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"id": "t1", "name": "João"}
            result = await client.get_talent_by_linkedin("joaosilva")
            mock_req.assert_called_once_with("GET", "/talents/linkedin/joaosilva")
            assert result["name"] == "João"


class TestWhatsApp:
    @pytest.mark.asyncio
    async def test_invalid_phone_raises(self, client):
        with pytest.raises(WhatsAppInvalidPhone):
            await client.send_whatsapp("123", "Oi")

    @pytest.mark.asyncio
    async def test_message_truncation(self, client):
        """Messages over 4096 chars should be truncated."""
        long_msg = "x" * 5000
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_req:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"ok": True}
            mock_req.return_value = resp
            await client.send_whatsapp("5511999999999", long_msg)
            sent_msg = mock_req.call_args[1]["json"]["message"]
            assert len(sent_msg) <= 4096
