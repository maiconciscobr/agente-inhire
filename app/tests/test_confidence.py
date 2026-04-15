import json
import pytest
from unittest.mock import MagicMock


class TestConfidenceEngine:
    def _make_service(self, confidence_data=None):
        from services.learning import LearningService
        svc = LearningService()
        svc._redis = MagicMock()
        if confidence_data:
            svc._redis.get.return_value = json.dumps(confidence_data)
        else:
            svc._redis.get.return_value = None
        return svc

    def test_get_confidence_default(self):
        svc = self._make_service()
        result = svc.get_confidence("user-1")
        assert result["auto_advance_threshold"] == 4.0
        assert result["decisions_count"] == 0
        assert result["reversals_count"] == 0
        assert result["circuit_breaker_active"] is False

    def test_get_confidence_existing(self):
        svc = self._make_service({"auto_advance_threshold": 3.5, "decisions_count": 25,
                                   "reversals_count": 1, "learned_threshold": 3.8})
        result = svc.get_confidence("user-1")
        assert result["auto_advance_threshold"] == 3.5
        assert result["learned_threshold"] == 3.8

    def test_set_threshold(self):
        svc = self._make_service()
        svc.set_threshold("user-1", 4.5)
        svc._redis.setex.assert_called_once()
        stored = json.loads(svc._redis.setex.call_args[0][2])
        assert stored["auto_advance_threshold"] == 4.5

    def test_set_threshold_clamped(self):
        svc = self._make_service()
        svc.set_threshold("user-1", 7.0)
        stored = json.loads(svc._redis.setex.call_args[0][2])
        assert stored["auto_advance_threshold"] == 5.0

    def test_record_reversal(self):
        svc = self._make_service({"auto_advance_threshold": 4.0, "decisions_count": 10,
                                   "reversals_count": 0})
        svc.record_reversal("user-1")
        stored = json.loads(svc._redis.setex.call_args[0][2])
        assert stored["reversals_count"] == 1

    def test_should_auto_advance_above_threshold(self):
        svc = self._make_service({"auto_advance_threshold": 4.0, "decisions_count": 10,
                                   "reversals_count": 0})
        assert svc.should_auto_advance("user-1", 4.5) is True
        assert svc.should_auto_advance("user-1", 3.9) is False
        assert svc.should_auto_advance("user-1", 4.0) is True

    def test_record_auto_advance(self):
        svc = self._make_service({"auto_advance_threshold": 4.0, "auto_advances_recent": 3})
        svc.record_auto_advance("user-1")
        stored = json.loads(svc._redis.setex.call_args[0][2])
        assert stored["auto_advances_recent"] == 4

    def test_circuit_breaker_inactive_by_default(self):
        svc = self._make_service({"auto_advance_threshold": 4.0, "auto_advances_recent": 3, "reversals_recent": 0})
        assert svc.check_circuit_breaker("user-1") is False

    def test_circuit_breaker_activates(self):
        svc = self._make_service({"auto_advance_threshold": 4.0, "auto_advances_recent": 10, "reversals_recent": 4})
        assert svc.check_circuit_breaker("user-1") is True

    def test_circuit_breaker_already_active(self):
        svc = self._make_service({"circuit_breaker_active": True})
        assert svc.check_circuit_breaker("user-1") is True

    def test_reset_circuit_breaker(self):
        svc = self._make_service({"circuit_breaker_active": True, "reversals_recent": 5, "auto_advances_recent": 20})
        svc.reset_circuit_breaker("user-1")
        stored = json.loads(svc._redis.setex.call_args[0][2])
        assert stored["circuit_breaker_active"] is False
        assert stored["reversals_recent"] == 0
        assert stored["auto_advances_recent"] == 0
