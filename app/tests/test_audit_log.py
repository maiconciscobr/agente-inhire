import pytest
from unittest.mock import MagicMock
import json


class TestAuditLog:
    def test_log_action_stores_entry(self):
        from services.audit_log import AuditLog
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        log = AuditLog()
        log._redis = mock_redis

        log.log_action("user-1", "auto_screening", "job-1", detail="5 candidatos")

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        key = call_args[0][0]
        assert "inhire:audit:user-1:" in key

    def test_get_recent_returns_entries(self):
        from services.audit_log import AuditLog
        mock_redis = MagicMock()
        entries = [{"ts": 1000, "action": "auto_screening", "job": "j1", "detail": "5"}]
        mock_redis.get.return_value = json.dumps(entries)

        log = AuditLog()
        log._redis = mock_redis

        result = log.get_recent("user-1")
        assert len(result) == 1
        assert result[0]["action"] == "auto_screening"

    def test_get_recent_empty(self):
        from services.audit_log import AuditLog
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        log = AuditLog()
        log._redis = mock_redis

        result = log.get_recent("user-1")
        assert result == []

    def test_format_for_briefing(self):
        from services.audit_log import AuditLog
        mock_redis = MagicMock()
        entries = [
            {"ts": 1000, "action": "auto_screening", "job": "j1", "candidate": "", "detail": "5 candidatos"},
            {"ts": 1001, "action": "auto_advance", "job": "j1", "candidate": "Ana", "detail": "score 4.3"},
        ]
        mock_redis.get.return_value = json.dumps(entries)

        log = AuditLog()
        log._redis = mock_redis

        result = log.format_for_briefing("user-1")
        assert "Triagem automática" in result
        assert "Movimentação automática" in result
        assert "Ana" in result
