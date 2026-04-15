"""Shared fixtures for unit tests."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add app dir to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# --- Fake Settings ---
class FakeSettings:
    inhire_api_url = "https://api.inhire.app"
    anthropic_api_key = "sk-test"
    claude_model = "claude-sonnet-4-20250514"
    claude_model_fast = "claude-haiku-4-5-20251001"
    redis_url = "redis://localhost:6379/2"
    slack_bot_token = "xoxb-test"
    slack_signing_secret = "test-secret"


@pytest.fixture
def settings():
    return FakeSettings()


# --- Mock InHire Client ---
@pytest.fixture
def mock_inhire():
    client = AsyncMock()
    # Jobs
    client.create_job.return_value = {"id": "job-1", "name": "Dev Python", "status": "open", "stages": []}
    client.get_job.return_value = {
        "id": "job-1", "name": "Dev Python", "status": "open",
        "stages": [
            {"id": "s1", "name": "Listados", "type": "listing", "order": 1},
            {"id": "s2", "name": "Entrevista", "type": "culturalFit", "order": 4},
        ],
        "sla": 30, "createdAt": "2026-04-01T10:00:00Z",
    }
    client.duplicate_job.return_value = {"id": "job-2", "name": "Dev Python (Cópia)", "status": "open"}
    client.list_job_templates.return_value = [{"id": "tpl-1", "name": "Dev Backend"}]

    # Candidates
    client.list_job_talents.return_value = [
        {
            "id": "job-1*talent-1", "talentId": "talent-1", "status": "active",
            "stage": {"name": "Listados", "type": "listing", "order": 1},
            "talent": {"name": "João Silva", "email": "joao@test.com", "phone": "+5511999990001", "linkedinUsername": "joaosilva"},
            "screening": {"score": 4.5, "status": "pre-aproved"},
        },
        {
            "id": "job-1*talent-2", "talentId": "talent-2", "status": "active",
            "stage": {"name": "Entrevista", "type": "culturalFit", "order": 4},
            "talent": {"name": "Maria Santos", "email": "maria@test.com", "phone": "+5511999990002"},
            "screening": {"score": 3.2, "status": "need-aproval"},
        },
    ]

    # Forms
    client.get_job_scorecard.return_value = {
        "id": "sc-1",
        "skillCategories": [
            {"name": "Técnico", "skills": [{"id": "sk-1", "name": "Python"}, {"id": "sk-2", "name": "FastAPI"}]},
            {"name": "Cultural", "skills": [{"id": "sk-3", "name": "Comunicação"}]},
        ],
    }
    client.generate_subscription_form.return_value = {"id": "form-1", "questions": []}
    client.get_interview_kit.return_value = {
        "resumeSummary": "10 anos de Python, 5 de FastAPI",
        "skillCategories": [{"name": "Técnico", "skills": [{"name": "Python"}]}],
        "questions": ["Conte sobre um projeto desafiador", "Como lida com prazos apertados"],
    }
    client.submit_scorecard_evaluation.return_value = {"id": "eval-1"}
    client.generate_scorecard_feedback.return_value = {"feedback": "Candidato forte tecnicamente."}
    client.send_disc_email.return_value = None
    client.send_form_email.return_value = None
    client.get_job_form.return_value = [{"id": "form-1"}]

    # Surveys
    client.create_survey.return_value = {"id": "survey-1"}
    client.get_survey_metrics.return_value = {"nps": 72, "totalResponses": 15, "averageScore": 4.2}

    # Offers
    client.list_offer_templates.return_value = [{"id": "otpl-1", "name": "CLT Padrão"}]
    client.get_offer_template_detail.return_value = {
        "id": "otpl-1", "name": "CLT Padrão",
        "variables": [{"name": "nomeCandidato"}, {"name": "salario"}, {"name": "dataInicio"}],
    }

    # Appointments
    client.list_candidate_appointments.return_value = [{"id": "appt-1", "startDateTime": "2026-04-20T14:00:00Z"}]

    # Search
    client.get_typesense_key.return_value = {"key": "test-key", "indexName": "talents_demo"}

    # Reactions
    client.react_to_candidate.return_value = {"reaction": "like"}

    # Smart CV
    client.get_smart_cv.return_value = None
    client.create_smart_cv.return_value = None

    return client


# --- Mock Slack Client ---
@pytest.fixture
def mock_slack():
    client = AsyncMock()
    client.post_message.return_value = {"ok": True, "ts": "123.456"}
    return client


# --- Mock Claude Client ---
@pytest.fixture
def mock_claude():
    client = AsyncMock()
    client.chat.return_value = "Resposta do Claude"
    client.detect_intent.return_value = {"tool": "conversa_livre", "input": {}, "text": "Oi!"}
    client.extract_job_data.return_value = {
        "title": "Dev Python", "requirements": ["Python", "FastAPI"],
        "salary_range": {"min": 10000, "max": 15000}, "missing_info": [],
    }
    client.generate_job_description.return_value = "# Dev Python\n\nDescrição..."
    client.summarize_candidates.return_value = "Ranking dos candidatos..."
    client.classify_rejection_reason.return_value = "underqualified"
    client.generate_personalized_rejection.return_value = "Devolutiva personalizada..."
    client.generate_whatsapp_message.return_value = "Olá João, tudo bem?"
    return client


# --- Mock Conversation ---
@pytest.fixture
def mock_conv():
    from services.conversation import FlowState

    conv = MagicMock()
    conv.state = FlowState.IDLE
    conv.user_id = "U07M0E04WRY"
    conv.messages = []
    conv._context = {}

    def get_context(key, default=None):
        return conv._context.get(key, default)

    def set_context(key, value):
        conv._context[key] = value

    conv.get_context = MagicMock(side_effect=get_context)
    conv.set_context = MagicMock(side_effect=set_context)
    return conv


# --- Mock App (FastAPI .state) ---
@pytest.fixture
def mock_app(mock_inhire, mock_slack, mock_claude):
    app = MagicMock()
    app.state.inhire = mock_inhire
    app.state.slack = mock_slack
    app.state.claude = mock_claude
    app.state.scheduler = MagicMock()
    app.state.user_mapping = MagicMock()
    app.state.user_mapping.get_user.return_value = {"comms_enabled": True}
    return app
