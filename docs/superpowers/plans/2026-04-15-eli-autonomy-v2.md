# Eli Autonomia v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Eli from a reactive assistant with 13 approval points into an autonomous copilot (5 approvals) / autopilot (2 approvals) that executes the full post-creation chain automatically and follows up intelligently per pipeline stage.

**Architecture:** Two modes (`copilot`/`autopilot`) stored per-recruiter in Redis via `user_mapping`. A new `_should_auto_approve(conv, action)` helper centralizes all autonomy decisions. The `ProactiveMonitor` gains stage-specific follow-ups and an audit log. A confidence engine in `LearningService` calibrates auto-advance thresholds weekly.

**Tech Stack:** Python 3.12, FastAPI, Redis, Anthropic SDK (claude-sonnet-4-20250514), APScheduler, httpx.

---

### Task 1: Add Autonomy Fields to User Mapping

**Files:**
- Modify: `app/services/user_mapping.py:43-52`
- Test: `app/tests/test_handlers.py`

- [ ] **Step 1: Write failing test for new settings**

```python
# In app/tests/test_handlers.py — add at the end of the file

class TestAutonomySettings:
    def test_default_settings_include_autonomy(self):
        from services.user_mapping import UserMapping
        defaults = UserMapping.DEFAULT_SETTINGS
        assert defaults["autonomy_mode"] == "copilot"
        assert defaults["auto_advance_threshold"] == 4.0
        assert defaults["followup_intensity"] == "normal"
        assert defaults["realtime_notifications"] is True
        assert defaults["daily_briefing"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_handlers.py::TestAutonomySettings -v`
Expected: FAIL — `KeyError: 'autonomy_mode'`

- [ ] **Step 3: Add autonomy fields to DEFAULT_SETTINGS**

In `app/services/user_mapping.py`, replace lines 43-52:

```python
    DEFAULT_SETTINGS = {
        "working_hours_start": 8,
        "working_hours_end": 19,
        "working_days": [0, 1, 2, 3, 4],
        "daily_briefing_time": 9,
        "max_proactive_messages": 3,
        "stale_threshold_days": 3,
        "reminder_interval_days": 7,
        "comms_enabled": True,
        # Autonomy
        "autonomy_mode": "copilot",
        "auto_advance_threshold": 4.0,
        # Follow-up
        "followup_intensity": "normal",
        # Notifications
        "realtime_notifications": True,
        "daily_briefing": True,
    }
```

Also update `update_settings` at line 104 — the `valid_keys` already reads from `DEFAULT_SETTINGS.keys()`, so no change needed there.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_handlers.py::TestAutonomySettings -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/user_mapping.py app/tests/test_handlers.py
git commit -m "feat: add autonomy settings to user_mapping (copilot/autopilot mode)"
```

---

### Task 2: Create the Autonomy Helper (`_should_auto_approve`)

**Files:**
- Modify: `app/routers/handlers/helpers.py`
- Test: `app/tests/test_handlers.py`

- [ ] **Step 1: Write failing test**

```python
# In app/tests/test_handlers.py — add at the end

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_handlers.py::TestShouldAutoApprove -v`
Expected: FAIL — `ImportError: cannot import name '_should_auto_approve'`

- [ ] **Step 3: Implement `_should_auto_approve`**

Add to the end of `app/routers/handlers/helpers.py` (after `_talent_phone`):

```python
# Actions that NEVER auto-approve (require human in both modes)
_ALWAYS_REQUIRE_APPROVAL = {
    "reject_candidates",
    "send_offer",
}

# Actions that auto-approve ONLY in autopilot mode
_AUTOPILOT_ONLY = {
    "move_candidates",
    "publish_job",
    "auto_advance",
    "send_whatsapp",
    "send_email",
    "send_external_comms",
}

# Actions that auto-approve in BOTH modes (internal, no external impact)
_ALWAYS_AUTO = {
    "auto_screening",
    "smart_match",
    "configure_job",
    "generate_shortlist",
    "generate_linkedin_search",
    "send_interview_kit",
    "follow_up",
}


def _should_auto_approve(user: dict, action: str) -> bool:
    """Check if an action should be auto-approved based on recruiter's autonomy mode.

    Returns True if the action can proceed without explicit recruiter approval.
    """
    if action in _ALWAYS_REQUIRE_APPROVAL:
        return False
    if action in _ALWAYS_AUTO:
        return True
    mode = user.get("autonomy_mode", "copilot")
    if mode == "autopilot" and action in _AUTOPILOT_ONLY:
        return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_handlers.py::TestShouldAutoApprove -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add app/routers/handlers/helpers.py app/tests/test_handlers.py
git commit -m "feat: add _should_auto_approve helper for autonomy decisions"
```

---

### Task 3: Create the Audit Log Service

**Files:**
- Create: `app/services/audit_log.py`
- Test: `app/tests/test_audit_log.py`

- [ ] **Step 1: Write failing test**

Create `app/tests/test_audit_log.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
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
        stored = json.loads(call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("value", "[]"))
        # The key should contain today's date
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_audit_log.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.audit_log'`

- [ ] **Step 3: Implement AuditLog**

Create `app/services/audit_log.py`:

```python
import json
import logging
import time
from datetime import datetime, timezone, timedelta

import redis

from config import get_settings

logger = logging.getLogger("agente-inhire.audit")

REDIS_PREFIX = "inhire:audit:"
AUDIT_TTL = 86400 * 30  # 30 days
BRT = timezone(timedelta(hours=-3))


class AuditLog:
    """Records autonomous actions for transparency in briefings."""

    def __init__(self):
        self._redis = None
        try:
            settings = get_settings()
            self._redis = redis.from_url(settings.redis_url, decode_responses=True)
            self._redis.ping()
        except Exception as e:
            logger.warning("Redis indisponível para audit log: %s", e)

    def _today_key(self, recruiter_id: str) -> str:
        today = datetime.now(BRT).strftime("%Y-%m-%d")
        return f"{REDIS_PREFIX}{recruiter_id}:{today}"

    def log_action(self, recruiter_id: str, action: str, job_id: str = "",
                   candidate: str = "", detail: str = ""):
        """Log an autonomous action."""
        if not self._redis:
            return
        try:
            key = self._today_key(recruiter_id)
            raw = self._redis.get(key)
            entries = json.loads(raw) if raw else []
            entries.append({
                "ts": time.time(),
                "action": action,
                "job": job_id,
                "candidate": candidate,
                "detail": detail,
            })
            # Cap at 200 entries per day
            if len(entries) > 200:
                entries = entries[-200:]
            self._redis.setex(key, AUDIT_TTL, json.dumps(entries))
        except Exception as e:
            logger.warning("Erro ao registrar ação no audit log: %s", e)

    def get_recent(self, recruiter_id: str, days: int = 1) -> list[dict]:
        """Get audit entries for the last N days."""
        if not self._redis:
            return []
        entries = []
        try:
            now = datetime.now(BRT)
            for d in range(days):
                date = (now - timedelta(days=d)).strftime("%Y-%m-%d")
                key = f"{REDIS_PREFIX}{recruiter_id}:{date}"
                raw = self._redis.get(key)
                if raw:
                    entries.extend(json.loads(raw))
        except Exception as e:
            logger.warning("Erro ao buscar audit log: %s", e)
        return sorted(entries, key=lambda e: e.get("ts", 0), reverse=True)

    def format_for_briefing(self, recruiter_id: str) -> str:
        """Format recent actions as a readable summary for the daily briefing."""
        entries = self.get_recent(recruiter_id, days=1)
        if not entries:
            return ""
        lines = []
        for e in entries[:15]:
            action = e.get("action", "?")
            detail = e.get("detail", "")
            candidate = e.get("candidate", "")
            label = {
                "auto_screening": "Triagem automática",
                "auto_advance": "Movimentação automática",
                "smart_match": "Smart Match",
                "auto_configure": "Config automática",
                "auto_publish": "Divulgação automática",
                "linkedin_search": "Busca LinkedIn gerada",
                "follow_up": "Follow-up enviado",
            }.get(action, action)
            parts = [f"• {label}"]
            if candidate:
                parts.append(f"({candidate})")
            if detail:
                parts.append(f"— {detail}")
            lines.append(" ".join(parts))
        return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_audit_log.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/services/audit_log.py app/tests/test_audit_log.py
git commit -m "feat: add AuditLog service for tracking autonomous actions"
```

---

### Task 4: Add Confidence Engine to LearningService

**Files:**
- Modify: `app/services/learning.py`
- Test: `app/tests/test_confidence.py`

- [ ] **Step 1: Write failing test**

Create `app/tests/test_confidence.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_confidence.py -v`
Expected: FAIL — `AttributeError: 'LearningService' object has no attribute 'get_confidence'`

- [ ] **Step 3: Implement confidence engine methods**

Add to the end of `app/services/learning.py` (inside class `LearningService`, after `get_alert_stats`):

```python
    # --- Confidence engine (auto-advance threshold) ---

    CONFIDENCE_PREFIX = "inhire:confidence:"
    CONFIDENCE_TTL = 86400 * 365  # 1 year

    def _default_confidence(self) -> dict:
        return {
            "auto_advance_threshold": 4.0,
            "learned_threshold": None,
            "decisions_count": 0,
            "approval_rate_above_threshold": 0.0,
            "reversals_count": 0,
            "last_calibration": None,
        }

    def get_confidence(self, recruiter_id: str) -> dict:
        """Get confidence data for a recruiter."""
        if not self._redis:
            return self._default_confidence()
        try:
            raw = self._redis.get(f"{self.CONFIDENCE_PREFIX}{recruiter_id}")
            if raw:
                data = self._default_confidence()
                data.update(json.loads(raw))
                return data
        except Exception as e:
            logger.warning("Erro ao buscar confidence: %s", e)
        return self._default_confidence()

    def _save_confidence(self, recruiter_id: str, data: dict):
        if not self._redis:
            return
        try:
            self._redis.setex(
                f"{self.CONFIDENCE_PREFIX}{recruiter_id}",
                self.CONFIDENCE_TTL,
                json.dumps(data, default=str),
            )
        except Exception as e:
            logger.warning("Erro ao salvar confidence: %s", e)

    def set_threshold(self, recruiter_id: str, threshold: float):
        """Manually set auto-advance threshold."""
        data = self.get_confidence(recruiter_id)
        data["auto_advance_threshold"] = max(0.0, min(5.0, threshold))
        self._save_confidence(recruiter_id, data)

    def record_reversal(self, recruiter_id: str):
        """Record that the recruiter reversed an auto-advance decision."""
        data = self.get_confidence(recruiter_id)
        data["reversals_count"] = data.get("reversals_count", 0) + 1
        self._save_confidence(recruiter_id, data)
        logger.info("Reversal recorded for %s (total: %d)", recruiter_id, data["reversals_count"])

    def should_auto_advance(self, recruiter_id: str, candidate_score: float) -> bool:
        """Check if a candidate should be auto-advanced based on score threshold."""
        data = self.get_confidence(recruiter_id)
        threshold = data.get("auto_advance_threshold", 4.0)
        return candidate_score >= threshold

    def calibrate(self, recruiter_id: str):
        """Recalculate learned_threshold from decision history.
        Called weekly by ProactiveMonitor cron.
        Finds the lowest score where 85%+ of candidates were approved."""
        all_patterns = self.get_all_patterns(recruiter_id)
        if not all_patterns:
            return

        # Collect all decisions with scores
        score_decisions = []  # [(score, approved)]
        for entry in all_patterns:
            patterns = entry.get("patterns", {})
            # We need raw decisions, not just aggregates
            # This is a simplified heuristic based on approval rate
            total = patterns.get("total_decisions", 0)
            approved = patterns.get("approved", 0)
            if total > 0:
                score_decisions.append((patterns.get("approval_rate", 0), total))

        if not score_decisions:
            return

        data = self.get_confidence(recruiter_id)
        total_decisions = sum(t for _, t in score_decisions)
        data["decisions_count"] = total_decisions

        # If 3+ reversals in recent history, bump threshold up
        if data.get("reversals_count", 0) >= 3:
            current = data.get("auto_advance_threshold", 4.0)
            data["auto_advance_threshold"] = min(5.0, current + 0.3)
            data["reversals_count"] = 0  # Reset after adjustment
            logger.info("Threshold bumped to %.1f for %s (3+ reversals)", data["auto_advance_threshold"], recruiter_id)

        data["last_calibration"] = time.strftime("%Y-%m-%d")
        self._save_confidence(recruiter_id, data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_confidence.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add app/services/learning.py app/tests/test_confidence.py
git commit -m "feat: add confidence engine to LearningService (threshold, calibrate, reversals)"
```

---

### Task 5: Add `modo_autonomia` Tool to Claude

**Files:**
- Modify: `app/services/claude_client.py`
- Modify: `app/routers/slack.py`
- Test: `app/tests/test_handlers.py`

- [ ] **Step 1: Write failing test**

```python
# In app/tests/test_handlers.py — add at the end

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_handlers.py::TestModoAutonomiaTool -v`
Expected: FAIL — `StopIteration`

- [ ] **Step 3: Add tool definition to ELI_TOOLS**

In `app/services/claude_client.py`, add this tool BEFORE `conversa_livre` (which must remain last):

```python
    {
        "name": "modo_autonomia",
        "description": (
            "Troca entre modo copiloto e piloto automático, ou ajusta threshold. "
            "Use quando o recrutador pedir mais/menos autonomia, modo piloto, "
            "modo copiloto, ou quiser ajustar o score de auto-advance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": "'copilot' ou 'autopilot'",
                },
                "threshold": {
                    "type": "number",
                    "description": "Score mínimo para auto-advance (0-5). Só no autopilot.",
                },
            },
        },
    },
```

- [ ] **Step 4: Add handler in slack.py**

In `app/routers/slack.py`, add this elif before `conversa_livre` in the `_handle_idle` dispatch:

```python
    elif tool == "modo_autonomia":
        mode = tool_input.get("mode")
        threshold = tool_input.get("threshold")
        user_mapping = app.state.user_mapping
        learning = app.state.learning

        if mode:
            mode = mode.lower().strip()
            if mode not in ("copilot", "autopilot"):
                mode = "autopilot" if "auto" in mode or "piloto" in mode else "copilot"
            user_mapping.update_settings(conv.user_id, autonomy_mode=mode)
            mode_label = "Piloto Automático ✈️" if mode == "autopilot" else "Copiloto 🧑‍✈️"
            msg = f"Modo alterado para *{mode_label}*!\n\n"
            if mode == "autopilot":
                t = user_mapping.get_setting(conv.user_id, "auto_advance_threshold") or 4.0
                msg += (
                    f"Vou agir sozinho no máximo possível:\n"
                    f"• Configuro vagas automaticamente\n"
                    f"• Divulgo em portais sem perguntar\n"
                    f"• Avanço candidatos com score ≥ {t}\n"
                    f"• Comunico candidatos direto (WhatsApp/email)\n"
                    f"• Só paro pra reprovar candidatos ou enviar oferta\n\n"
                    f"Threshold atual: *{t}*. Diz se quiser ajustar."
                )
            else:
                msg += (
                    "Vou continuar fazendo tudo automaticamente (screening, config, busca),\n"
                    "mas peço aprovação antes de divulgar vagas e mover candidatos."
                )
            await _send(conv, slack, channel_id, msg)

        if threshold is not None:
            threshold = max(0.0, min(5.0, float(threshold)))
            user_mapping.update_settings(conv.user_id, auto_advance_threshold=threshold)
            learning.set_threshold(conv.user_id, threshold)
            if not mode:
                await _send(
                    conv, slack, channel_id,
                    f"Threshold de auto-advance ajustado para *{threshold}*.\n"
                    f"Candidatos com score ≥ {threshold} serão avançados automaticamente no modo Piloto.",
                )
```

- [ ] **Step 5: Run tests**

Run: `cd app && python -m pytest tests/test_handlers.py::TestModoAutonomiaTool -v`
Expected: PASS

- [ ] **Step 6: Update tool count test**

In `app/tests/test_handlers.py`, update `test_tool_count`:

```python
    def test_tool_count(self):
        from services.claude_client import ELI_TOOLS
        # 26 previous + 1 modo_autonomia = 27
        assert len(ELI_TOOLS) == 27, f"Expected 27 tools, got {len(ELI_TOOLS)}"
```

- [ ] **Step 7: Run full test suite**

Run: `cd app && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add app/services/claude_client.py app/routers/slack.py app/tests/test_handlers.py
git commit -m "feat: add modo_autonomia tool (switch copilot/autopilot, adjust threshold)"
```

---

### Task 6: Implement Post-Creation Chain

**Files:**
- Modify: `app/routers/handlers/job_creation.py`
- Modify: `app/routers/slack.py:1344-1400`

- [ ] **Step 1: Write failing test**

```python
# In app/tests/test_handlers.py — add at the end

class TestPostCreationChain:
    @pytest.mark.asyncio
    async def test_chain_runs_config_match_linkedin(self, mock_conv, mock_app):
        from routers.handlers.job_creation import _post_creation_chain

        mock_conv._context["job_data"] = {
            "title": "Dev Python",
            "requirements": ["Python", "FastAPI"],
            "salary_range": {"min": 10000, "max": 15000},
        }
        mock_app.state.user_mapping.get_user.return_value = {
            "autonomy_mode": "copilot", "auto_advance_threshold": 4.0,
        }

        await _post_creation_chain(mock_conv, mock_app, "C123", "job-1")

        # Should call auto_configure
        mock_app.state.inhire.configure_screening.assert_called_once()
        # Should send consolidated message
        assert mock_app.state.slack.send_message.call_count >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_handlers.py::TestPostCreationChain -v`
Expected: FAIL — `ImportError: cannot import name '_post_creation_chain'`

- [ ] **Step 3: Implement `_post_creation_chain`**

Add to `app/routers/handlers/job_creation.py` (after `_auto_configure_job`):

```python
async def _post_creation_chain(conv, app, channel_id: str, job_id: str):
    """Execute the full post-creation automation chain.
    Runs in both copilot and autopilot. The only difference is whether
    the job gets auto-published (autopilot only).
    """
    import asyncio
    slack = app.state.slack
    inhire = app.state.inhire
    claude = app.state.claude

    job_data = conv.get_context("job_data", {})
    job_name = conv.get_context("current_job_name", "")
    user = app.state.user_mapping.get_user(conv.user_id) or {}
    mode = user.get("autonomy_mode", "copilot")

    results = {"configured": [], "match_count": 0, "high_fit": 0, "linkedin": ""}

    # Phase 1: Auto-configure (screening + scorecard + form) — already exists
    configured = await _auto_configure_job(conv, app, channel_id, job_id)
    results["configured"] = configured

    # Phase 2: Smart Match + LinkedIn search (parallel)
    async def _run_smart_match():
        try:
            from routers.handlers.hunting import _smart_match
            # Simulate tool_input for smart_match
            candidates = await inhire.list_job_talents(job_id)
            existing_ids = {c.get("talentId") for c in candidates}

            ai_result = await inhire.gen_filter_job_talents(
                job_id,
                " ".join(job_data.get("requirements", [])[:5]),
            )
            if ai_result and ai_result.get("filter"):
                results["match_count"] = len(ai_result.get("results", []))
            # Log the action
            if hasattr(app.state, "audit_log"):
                app.state.audit_log.log_action(
                    conv.user_id, "smart_match", job_id,
                    detail=f"{results['match_count']} matches encontrados",
                )
        except Exception as e:
            logger.warning("Smart match pós-vaga falhou: %s", e)

    async def _run_linkedin_search():
        try:
            requirements = job_data.get("requirements", [])
            location = job_data.get("location", "")
            title = job_data.get("title", "")
            terms = [title] + requirements[:5]
            required = " AND ".join(f'"{t}"' for t in terms[:3] if t)
            optional = " OR ".join(f'"{t}"' for t in terms[3:] if t)
            search = f'({required})'
            if optional:
                search += f' AND ({optional})'
            if location:
                search += f' AND "{location}"'
            results["linkedin"] = search
            if hasattr(app.state, "audit_log"):
                app.state.audit_log.log_action(
                    conv.user_id, "linkedin_search", job_id, detail="String gerada",
                )
        except Exception as e:
            logger.warning("LinkedIn search pós-vaga falhou: %s", e)

    await asyncio.gather(_run_smart_match(), _run_linkedin_search(), return_exceptions=True)

    # Phase 3: Auto-publish (autopilot only)
    auto_published = False
    if mode == "autopilot":
        try:
            integrations = await inhire.get_integrations()
            career_pages = [i for i in integrations if i.get("type") == "careerPage"]
            if career_pages:
                page_id = career_pages[0].get("id", "")
                if page_id:
                    await inhire.publish_job(job_id, page_id, job_name, ["linkedin", "indeed"])
                    auto_published = True
                    if hasattr(app.state, "audit_log"):
                        app.state.audit_log.log_action(
                            conv.user_id, "auto_publish", job_id,
                            detail="LinkedIn + Indeed",
                        )
        except Exception as e:
            logger.warning("Auto-publish falhou: %s", e)

    # Phase 4: Consolidated message
    msg = f"✅ Vaga *{job_name}* criada e configurada!\n\n"

    if results["configured"]:
        items = ", ".join(results["configured"])
        msg += f"⚙️ *Setup automático:* {items}\n\n"

    if results["match_count"] > 0 or results["linkedin"]:
        msg += "🔍 *Busca no banco de talentos:*\n"
        if results["match_count"] > 0:
            msg += f"• {results['match_count']} talentos compatíveis encontrados\n"
        if results["linkedin"]:
            msg += f"• String LinkedIn pronta:\n  `{results['linkedin']}`\n"
        msg += "\n"

    if auto_published:
        msg += "📢 Divulguei no LinkedIn e Indeed ✓\n\n"
    elif mode == "copilot":
        msg += "📢 Quer que eu divulgue no LinkedIn e Indeed?\n\n"

    msg += "Vou ficar de olho nos candidatos e te aviso quando tiver gente boa!"

    await _send(conv, slack, channel_id, msg)
```

- [ ] **Step 4: Wire into slack.py approval handler**

In `app/routers/slack.py`, replace the post-approval block at line ~1382-1399 (inside `callback_id == "job_draft_approval"`, after `conv.set_context("job_stages", ...)`):

Replace this:
```python
                    await _send(
                        conv, slack, channel_id,
                        f"✅ Pronto, vaga criada!\n"
                        ...
                    )
                    # Guide: what the recruiter still needs to do in InHire
                    await _send(
                        conv, slack, channel_id,
                        "⚠️ *Pra completar a vaga, você ainda precisa configurar no InHire:*\n\n"
                        ...
                    )
```

With this:
```python
                    from routers.handlers.job_creation import _post_creation_chain
                    await _post_creation_chain(conv, app, channel_id, job_id)
```

- [ ] **Step 5: Run test**

Run: `cd app && python -m pytest tests/test_handlers.py::TestPostCreationChain -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/routers/handlers/job_creation.py app/routers/slack.py app/tests/test_handlers.py
git commit -m "feat: post-creation chain (auto-config + smart match + linkedin + publish)"
```

---

### Task 7: Auto-Screening on Webhook (JOB_TALENT_ADDED)

**Files:**
- Modify: `app/routers/webhooks.py:58`

- [ ] **Step 1: Read current `_handle_talent_added`**

Read `app/routers/webhooks.py` at line 58 to understand current handler.

- [ ] **Step 2: Add auto-screening logic**

In `app/routers/webhooks.py`, expand `_handle_talent_added` to dispatch screening for hunting candidates:

```python
async def _handle_talent_added(app, payload: dict):
    """Handle JOB_TALENT_ADDED webhook — auto-screen hunting candidates."""
    job_id = payload.get("jobId", "")
    talent_id = payload.get("talentId", "")
    source = payload.get("source", "")
    job_talent_id = f"{job_id}*{talent_id}" if job_id and talent_id else ""

    # Auto-screen hunting candidates (no form → no automatic screening in InHire)
    if source in ("manual", "api") and job_talent_id:
        try:
            inhire = app.state.inhire
            # Try manual screening first, fallback to resume analysis
            result = await inhire.manual_screening(job_talent_id)
            if not result:
                await inhire.analyze_resume(job_talent_id)
            if hasattr(app.state, "audit_log"):
                app.state.audit_log.log_action(
                    "", "auto_screening", job_id,
                    candidate=talent_id, detail=f"source={source}",
                )
            logger.info("Auto-screening dispatched for %s (source=%s)", job_talent_id, source)
        except Exception as e:
            logger.warning("Auto-screening failed for %s: %s", job_talent_id, e)
```

- [ ] **Step 3: Verify compilation**

Run: `cd app && python -m py_compile routers/webhooks.py && echo OK`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add app/routers/webhooks.py
git commit -m "feat: auto-screening for hunting candidates on JOB_TALENT_ADDED webhook"
```

---

### Task 8: Stage-Specific Follow-Up in ProactiveMonitor

**Files:**
- Modify: `app/services/proactive_monitor.py`

- [ ] **Step 1: Add follow-up method to ProactiveMonitor**

Add new method `_check_stage_followups` inside the `ProactiveMonitor` class. This replaces the generic "pipeline parado" approach with stage-aware follow-ups.

At the end of the `ProactiveMonitor` class, add:

```python
    async def _check_stage_followups(self, job: dict, user: dict, channel_id: str):
        """Check for stage-specific follow-up opportunities."""
        job_id = job.get("id", "")
        job_name = job.get("name", "")
        user_id = user.get("slack_user_id", "")
        intensity = user.get("followup_intensity", "normal")
        multiplier = {"gentle": 2.0, "normal": 1.0, "aggressive": 0.5}.get(intensity, 1.0)

        try:
            candidates = await self.inhire.list_job_talents(job_id)
        except Exception:
            return

        now = datetime.now(timezone.utc)

        for c in candidates:
            if c.get("status") in ("rejected", "dropped"):
                continue

            stage = c.get("stage", {}) or {}
            stage_name = stage.get("name", "")
            stage_type = stage.get("type", "")
            talent = c.get("talent", {}) or {}
            name = talent.get("name", "?")
            jt_id = c.get("id", "")
            screening = c.get("screening", {}) or {}
            score = screening.get("score")

            # Calculate time in current stage from candidate's updatedAt
            updated = c.get("updatedAt") or c.get("createdAt", "")
            if not updated:
                continue
            try:
                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                hours_in_stage = (now - updated_dt).total_seconds() / 3600
            except Exception:
                continue

            # --- Interview stages: follow-up for feedback ---
            if stage_type in ("culturalFit", "technicalFit"):
                followup_hours = 24 * multiplier
                if hours_in_stage >= followup_hours:
                    alert_key = f"followup_interview:{jt_id}"
                    if not self._was_recently_sent(user_id, alert_key, ttl_hours=48 * multiplier):
                        msg = (
                            f"📝 *{name}* está em *{stage_name}* há "
                            f"{int(hours_in_stage / 24)} dia(s) na vaga *{job_name}*.\n"
                            f"Se já entrevistou, me conta como foi que eu preencho o scorecard!"
                        )
                        await self._send_proactive(user_id, channel_id, msg, alert_type="interview_followup")

            # --- Offer stage: follow-up for decision ---
            elif stage_type == "offer":
                followup_hours = 72 * multiplier
                if hours_in_stage >= followup_hours:
                    alert_key = f"followup_offer:{jt_id}"
                    if not self._was_recently_sent(user_id, alert_key, ttl_hours=72 * multiplier):
                        days = int(hours_in_stage / 24)
                        msg = (
                            f"📋 A proposta de *{name}* está aberta há *{days} dias* "
                            f"na vaga *{job_name}*. Quer que eu envie um follow-up?"
                        )
                        await self._send_proactive(user_id, channel_id, msg, alert_type="offer_followup")

            # --- Exceptional candidate: urgency ---
            if score and isinstance(score, (int, float)) and score >= 4.5:
                if hours_in_stage >= 4 * multiplier:
                    alert_key = f"exceptional_urgent:{jt_id}"
                    if not self._was_recently_sent(user_id, alert_key, ttl_hours=24):
                        msg = (
                            f"🚨 *{name}* (score {score:.1f}) está na vaga *{job_name}* "
                            f"há {int(hours_in_stage)}h sem avançar.\n"
                            f"Perfis assim costumam receber outras propostas rápido."
                        )
                        await self._send_proactive(user_id, channel_id, msg, alert_type="exceptional_urgent")

    def _was_recently_sent(self, user_id: str, alert_key: str, ttl_hours: float = 24) -> bool:
        """Check if this specific alert was sent recently (prevents spam)."""
        try:
            r = self._get_redis()
            if not r:
                return False
            key = f"inhire:followup_sent:{user_id}:{alert_key}"
            if r.get(key):
                return True
            r.setex(key, int(ttl_hours * 3600), "1")
            return False
        except Exception:
            return False
```

- [ ] **Step 2: Wire into `_check_single_job`**

In `_check_single_job` (line ~537), add a call to the new method at the end of the existing checks:

```python
        # Stage-specific follow-ups (after existing stale/shortlist/exceptional checks)
        await self._check_stage_followups(job, user, channel_id)
```

- [ ] **Step 3: Verify compilation**

Run: `cd app && python -m py_compile services/proactive_monitor.py && echo OK`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add app/services/proactive_monitor.py
git commit -m "feat: stage-specific follow-ups (interview feedback, offer, exceptional urgency)"
```

---

### Task 9: Smart Interview Scheduling

**Files:**
- Modify: `app/services/user_mapping.py:43-65`
- Modify: `app/routers/handlers/interviews.py`
- Modify: `app/routers/slack.py` (shortlist_approval handler)

- [ ] **Step 1: Add interview scheduling fields to user_mapping**

In `app/services/user_mapping.py`, add to `DEFAULT_SETTINGS`:

```python
        # Entrevistas
        "preferred_interview_slots": [],    # [{"day": "tue", "hour": 14}, ...]
        "default_interview_duration": 60,   # minutes
```

- [ ] **Step 2: Add `_propose_interview_times` helper to interviews.py**

Add at the end of `app/routers/handlers/interviews.py`:

```python
async def _propose_interview_times(conv, app, channel_id: str, candidates: list[dict]):
    """Proactively propose interview times for shortlisted candidates.
    Checks recruiter's preferred slots and availability, then presents options."""
    slack = app.state.slack
    inhire = app.state.inhire
    user_mapping = app.state.user_mapping

    user = user_mapping.get_user(conv.user_id) or {}
    preferred_slots = user.get("preferred_interview_slots", [])
    duration = user.get("default_interview_duration", 60)
    job_name = conv.get_context("current_job_name", "")

    if not candidates:
        return

    # Try to check availability via InHire
    try:
        availability = await inhire.check_availability()
    except Exception:
        availability = {}

    from datetime import datetime, timedelta, timezone as tz
    now = datetime.now(tz(timedelta(hours=-3)))  # BRT

    if preferred_slots:
        # Build concrete proposals from preferred slots
        proposals = []
        day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4}
        for slot in preferred_slots[:5]:
            day_name = slot.get("day", "")
            hour = slot.get("hour", 14)
            day_num = day_map.get(day_name.lower()[:3], -1)
            if day_num < 0:
                continue
            # Find next occurrence of this weekday
            days_ahead = day_num - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)
            target = target.replace(hour=hour, minute=0, second=0, microsecond=0)
            if target > now + timedelta(hours=2):  # At least 2h from now
                proposals.append(target)

        if proposals:
            proposals.sort()
            msg = f"🎯 *Entrevistas — {job_name}*\n\n"
            msg += f"{len(candidates)} candidato(s) prontos. "
            msg += "Com base nos seus horários preferidos, sugiro:\n\n"

            for i, (cand, prop) in enumerate(zip(candidates[:len(proposals)], proposals)):
                talent = cand.get("talent", {}) or {}
                name = talent.get("name", "?")
                day_br = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"][prop.weekday()]
                msg += f"  {i+1}. *{name}* — {day_br} {prop.strftime('%d/%m')} às {prop.strftime('%Hh')}\n"

            remaining = len(candidates) - len(proposals)
            if remaining > 0:
                msg += f"\n  (+{remaining} candidato(s) sem horário sugerido)\n"

            msg += "\nQuer que eu agende assim, ou prefere outros horários?"
            await _send(conv, slack, channel_id, msg)

            # Save proposals in context for quick confirmation
            conv.set_context("pending_interview_proposals", [
                {"candidate_id": c.get("id"), "candidate_name": (c.get("talent") or {}).get("name", "?"),
                 "proposed_time": p.isoformat()}
                for c, p in zip(candidates[:len(proposals)], proposals)
            ])
            return

    # No preferred slots — ask the recruiter
    names = [((c.get("talent") or {}).get("name", "?")) for c in candidates[:5]]
    names_text = ", ".join(names[:3])
    if len(names) > 3:
        names_text += f" e mais {len(names) - 3}"

    msg = (
        f"🎯 *{names_text}* estão prontos pra entrevista na vaga *{job_name}*!\n\n"
        f"Quais são seus melhores horários essa semana?\n"
        f"(Ex: \"terça e quinta às 14h\", \"amanhã 10h\")\n\n"
        f"💡 Se me disser seus horários preferidos, da próxima vez eu já sugiro direto."
    )
    await _send(conv, slack, channel_id, msg)


async def _send_micro_feedback(conv, app, channel_id: str, candidate_name: str,
                                job_talent_id: str, job_name: str):
    """Send micro-feedback buttons after an interview is expected to have ended."""
    slack = app.state.slack

    msg = (
        f"Como foi a entrevista com *{candidate_name}*? 🎯\n\n"
        f"Reação rápida (posso detalhar depois):"
    )

    # Send as Slack blocks with action buttons
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": msg}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "👍 Avançar"},
                    "style": "primary",
                    "value": f"micro_feedback_advance:{job_talent_id}",
                    "action_id": "approve",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🤷 Talvez"},
                    "value": f"micro_feedback_maybe:{job_talent_id}",
                    "action_id": "adjust",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "👎 Não avançar"},
                    "style": "danger",
                    "value": f"micro_feedback_reject:{job_talent_id}",
                    "action_id": "reject",
                },
            ],
        },
    ]

    conv.add_message("assistant", msg)
    conv.set_context("micro_feedback_candidate", {
        "job_talent_id": job_talent_id,
        "candidate_name": candidate_name,
        "job_name": job_name,
    })
    await slack.send_message(channel_id, msg, blocks=blocks)
```

- [ ] **Step 3: Wire interview proposals into shortlist approval**

In `app/routers/slack.py`, inside the `shortlist_approval` handler (line ~1414), after `_move_approved_candidates` succeeds, add:

```python
            if action_id == "approve":
                await _move_approved_candidates(conv, app, channel_id)
                # Proactively propose interviews for moved candidates
                moved = conv.get_context("shortlist_candidates", [])
                if moved:
                    from routers.handlers.interviews import _propose_interview_times
                    await _propose_interview_times(conv, app, channel_id, moved)
```

- [ ] **Step 4: Learn preferred slots when recruiter provides them**

In `app/routers/handlers/interviews.py`, inside `_handle_scheduling_input`, after a successful scheduling, add slot learning:

```python
        # Learn preferred slot if not already known
        user = app.state.user_mapping.get_user(conv.user_id) or {}
        if not user.get("preferred_interview_slots"):
            # Extract day/hour from scheduled appointment
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(appointment_payload["startDateTime"].replace("Z", ""))
                day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
                learned_slot = {"day": day_names[dt.weekday()], "hour": dt.hour}
                app.state.user_mapping.update_settings(
                    conv.user_id,
                    preferred_interview_slots=[learned_slot],
                )
                logger.info("Learned interview slot for %s: %s", conv.user_id, learned_slot)
            except Exception:
                pass
```

- [ ] **Step 5: Verify compilation**

Run: `cd app && python -m py_compile routers/handlers/interviews.py && python -m py_compile routers/slack.py && echo OK`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add app/services/user_mapping.py app/routers/handlers/interviews.py app/routers/slack.py
git commit -m "feat: smart interview scheduling (preferred slots, proposals, micro-feedback)"
```

---

### Task 10: Enhanced Daily Briefing with Audit Log (was Task 9)

**Files:**
- Modify: `app/services/proactive_monitor.py` (method `_send_user_briefing`)
- Modify: `app/main.py` (initialize AuditLog)

- [ ] **Step 1: Initialize AuditLog in main.py**

In `app/main.py`, where other services are initialized during lifespan, add:

```python
from services.audit_log import AuditLog
# ... inside lifespan:
app.state.audit_log = AuditLog()
```

- [ ] **Step 2: Expand `_send_user_briefing` to include audit log**

In the existing `_send_user_briefing` method, add an audit log section after the job summaries. Look for where the briefing message is assembled and add:

```python
        # Add audit log section (what Eli did automatically)
        if hasattr(self, 'audit_log') or hasattr(app, 'state'):
            try:
                from services.audit_log import AuditLog
                audit = AuditLog()
                audit_text = audit.format_for_briefing(user.get("slack_user_id", ""))
                if audit_text:
                    msg += f"\n🤖 *O que eu fiz ontem:*\n{audit_text}\n"
            except Exception:
                pass
```

- [ ] **Step 3: Verify compilation**

Run: `cd app && python -m py_compile main.py && python -m py_compile services/proactive_monitor.py && echo OK`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add app/main.py app/services/proactive_monitor.py
git commit -m "feat: enhanced daily briefing with audit log (what Eli did autonomously)"
```

---

### Task 11: Update SYSTEM_PROMPT with Autonomy Awareness

**Files:**
- Modify: `app/services/claude_client.py`

- [ ] **Step 1: Add autonomy context to SYSTEM_PROMPT_STATIC**

In `SYSTEM_PROMPT_STATIC`, after the `PONTOS DE PAUSA` section, add:

```python
MODOS DE OPERAÇÃO:
O recrutador pode operar em dois modos:
- *Copiloto* (padrão): Você faz tudo automaticamente (config, busca, screening, shortlist) e pede aprovação para: divulgar vaga, mover candidatos, reprovar, comunicar candidato, enviar oferta.
- *Piloto Automático*: Máxima autonomia. Divulga vagas, move candidatos, comunica candidatos (WhatsApp/email) — tudo sozinho. Só pede aprovação para: reprovar candidatos e enviar carta oferta.

O recrutador troca de modo dizendo "modo piloto automático" ou "modo copiloto".

COMPORTAMENTO EM ENTREVISTAS:
- Após shortlist aprovado, proponha horários de entrevista concretos baseados nos slots preferidos do recrutador
- Se não sabe os slots, pergunte uma vez e salve pra próximas vezes
- Após entrevista, peça micro-feedback com opções rápidas (Avançar / Talvez / Não)
- No piloto automático, "Avançar" auto-move o candidato sem perguntar de novo

Nos dois modos, NUNCA aja como se não soubesse o que fazer. Faça primeiro, avise depois. Seja proativo e competente — não pergunte "quer que eu faça X?" para coisas que você pode simplesmente fazer e reportar.
```

- [ ] **Step 2: Add mode to dynamic context**

In `app/routers/handlers/helpers.py`, in `_build_dynamic_context`, add after the profile injection:

```python
        # Autonomy mode
        try:
            user = app_or_conv_user_mapping  # need to access user_mapping
        except Exception:
            pass
```

Actually, simpler approach — add to the dynamic context in `_handle_idle` where `_build_dynamic_context` is called. The mode is already in user_mapping. Add to `_build_dynamic_context`:

After the `ESTILO DO RECRUTADOR` injection (around line 86), add:

```python
        # Autonomy mode context
        try:
            user_data = r.get(f"inhire:user:{conv.user_id}")
            if user_data:
                import json as _json2
                u = _json2.loads(user_data)
                mode = u.get("autonomy_mode", "copilot")
                threshold = u.get("auto_advance_threshold", 4.0)
                mode_label = "Piloto Automático" if mode == "autopilot" else "Copiloto"
                parts.append(f"MODO DE AUTONOMIA: {mode_label} (threshold auto-advance: {threshold})")
        except Exception:
            pass
```

- [ ] **Step 3: Verify compilation**

Run: `cd app && python -m py_compile services/claude_client.py && python -m py_compile routers/handlers/helpers.py && echo OK`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add app/services/claude_client.py app/routers/handlers/helpers.py
git commit -m "feat: autonomy-aware system prompt and dynamic context injection"
```

---

### Task 12: Run Full Test Suite and Final Verification

**Files:**
- All modified files

- [ ] **Step 1: Run all tests**

Run: `cd app && python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 2: Compile all modified files**

```bash
cd app && python -m py_compile services/user_mapping.py && \
python -m py_compile services/learning.py && \
python -m py_compile services/audit_log.py && \
python -m py_compile services/claude_client.py && \
python -m py_compile services/proactive_monitor.py && \
python -m py_compile routers/handlers/helpers.py && \
python -m py_compile routers/handlers/job_creation.py && \
python -m py_compile routers/slack.py && \
python -m py_compile routers/webhooks.py && \
python -m py_compile main.py && \
echo "ALL OK"
```

- [ ] **Step 3: Update CLAUDE.md with new capabilities**

Add to the melhorias table:
```
| 76 | **Autonomia v2 — dois modos** — copiloto (5 aprovações) e piloto automático (2 aprovações) | ✅ | 44 |
| 77 | **Cadeia pós-vaga** — screening + scorecard + form + smart match + linkedin automáticos | ✅ | 44 |
| 78 | **Motor de confiança** — threshold de auto-advance aprendido + calibração semanal | ✅ | 44 |
| 79 | **Follow-up por etapa** — cobrança progressiva pós-entrevista, offer, candidato excepcional | ✅ | 44 |
| 80 | **Audit log** — registro de ações autônomas, exibido no briefing matinal | ✅ | 44 |
| 81 | **Briefing expandido** — seções "fez / precisa de você / métricas" + audit log | ✅ | 44 |
| 82 | **Auto-screening webhook** — hunting candidates triados automaticamente no JOB_TALENT_ADDED | ✅ | 44 |
| 83 | **Smart scheduling** — proposta de horários baseada em slots preferidos + micro-feedback pós-entrevista | ✅ | 44 |
```

- [ ] **Step 4: Update DIARIO_DO_PROJETO.md with session 44**

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: Eli Autonomia v2 — copiloto + piloto automático (spec → implementation)"
```
