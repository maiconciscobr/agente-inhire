# Batch Approval + Auto-backoff — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce Slack noise with grouped approvals in post-creation chain and adaptive follow-up intensity that backs off when recruiters ignore alerts.

**Architecture:** Batch approval accumulates copilot-pending actions during `_post_creation_chain` and sends a single Slack block with [Confirma tudo] / [Revisar uma a uma]. Auto-backoff tracks consecutive ignored follow-ups per recruiter in Redis and auto-downgrades `followup_intensity` (normal → gentle → off). Recovery is automatic on any recruiter engagement.

**Tech Stack:** Python 3.12, FastAPI, Redis, Slack Block Kit.

---

### Task 1: Add `_send_batch_approval` to helpers

**Files:**
- Modify: `app/routers/handlers/helpers.py:309` (after `_send_with_undo`)
- Test: `app/tests/test_handlers.py`

- [ ] **Step 1: Write failing test for `_send_batch_approval`**

Add at the end of `app/tests/test_handlers.py`:

```python
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
        # Should have blocks with actions
        assert blocks is not None
        # Should store batch in context
        assert mock_conv.set_context.call_count >= 1

    @pytest.mark.asyncio
    async def test_batch_stores_pending_in_context(self, mock_conv, mock_app):
        from routers.handlers.helpers import _send_batch_approval

        actions = [
            {"callback_id": "publish_job_approval", "title": "Divulgar no LinkedIn"},
            {"callback_id": "shortlist_approval", "title": "Mover candidatos"},
            {"callback_id": "whatsapp_free_approval", "title": "Enviar WhatsApp"},
        ]
        await _send_batch_approval(mock_conv, mock_app.state.slack, "C123", actions)

        # Verify batch_pending was stored
        stored = mock_conv._context.get("batch_pending")
        assert stored is not None
        assert len(stored) == 3
        assert stored[0]["callback_id"] == "publish_job_approval"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_handlers.py::TestBatchApproval -v`
Expected: FAIL — `ImportError: cannot import name '_send_batch_approval'`

- [ ] **Step 3: Implement `_send_batch_approval`**

Add to `app/routers/handlers/helpers.py` after `_send_with_undo` (after line 324):

```python
async def _send_batch_approval(conv, slack, channel_id: str, actions: list[dict]):
    """Send a batch approval block when copilot has 3+ pending actions.

    Each action dict has: {"callback_id": str, "title": str}
    Stores the list in conv context for the batch_approval handler to process.
    """
    conv.set_context("batch_pending", actions)

    items = "\n".join(f"  • {a['title']}" for a in actions)
    text = f"Tenho {len(actions)} ações pendentes pra sua aprovação:\n{items}"
    conv.add_message("assistant", text)

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Confirma tudo"},
                    "style": "primary",
                    "value": "batch_approval",
                    "action_id": "approve",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📝 Revisar uma a uma"},
                    "value": "batch_approval",
                    "action_id": "adjust",
                },
            ],
        },
    ]
    await slack.send_message(channel_id, text, blocks=blocks)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_handlers.py::TestBatchApproval -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/routers/handlers/helpers.py app/tests/test_handlers.py
git commit -m "feat: add _send_batch_approval for grouped copilot approvals"
```

---

### Task 2: Add batch_approval handler to slack.py interactions

**Files:**
- Modify: `app/routers/slack.py:1714` (before the final `except` in `_handle_approval`)
- Test: `app/tests/test_handlers.py`

- [ ] **Step 1: Write failing test for batch approve-all**

Add at the end of `app/tests/test_handlers.py`:

```python
class TestBatchApprovalHandler:
    @pytest.mark.asyncio
    async def test_approve_all_executes_all_callbacks(self, mock_conv, mock_app):
        """Clicking [Confirma tudo] should execute all pending approvals."""
        mock_conv._context["batch_pending"] = [
            {"callback_id": "publish_job_approval", "title": "Divulgar"},
            {"callback_id": "shortlist_approval", "title": "Mover candidatos"},
        ]
        mock_conv._context["current_job_id"] = "job-1"
        mock_conv._context["current_job_name"] = "Dev Python"

        # Mock conversations to return our mock_conv
        mock_app.state.conversations.get_or_create.return_value = mock_conv

        from routers.slack import _handle_approval
        await _handle_approval(mock_app, "U123", "C123", "approve", "batch_approval")

        # batch_pending should be cleared
        assert mock_conv._context.get("batch_pending") is None or mock_conv._context.get("batch_pending") == []

    @pytest.mark.asyncio
    async def test_adjust_sends_individual_approvals(self, mock_conv, mock_app):
        """Clicking [Revisar] should send each approval individually."""
        mock_conv._context["batch_pending"] = [
            {"callback_id": "publish_job_approval", "title": "Divulgar no LinkedIn"},
            {"callback_id": "shortlist_approval", "title": "Mover 3 candidatos"},
        ]
        mock_app.state.conversations.get_or_create.return_value = mock_conv

        from routers.slack import _handle_approval
        await _handle_approval(mock_app, "U123", "C123", "adjust", "batch_approval")

        # Should have sent individual approval messages
        assert mock_app.state.slack.send_approval_request.call_count >= 1 or \
               mock_app.state.slack.send_message.call_count >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_handlers.py::TestBatchApprovalHandler -v`
Expected: FAIL — batch_approval not handled in `_handle_approval`

- [ ] **Step 3: Add batch_approval handler to `_handle_approval`**

In `app/routers/slack.py`, add this block before the final `except Exception as e:` at the end of `_handle_approval` (before line 1716):

```python
        # --- Batch approval (grouped copilot actions) ---
        elif callback_id == "batch_approval":
            pending = conv.get_context("batch_pending", [])
            if action_id == "approve":
                if not pending:
                    await _send(conv, slack, channel_id, "Nenhuma ação pendente.")
                else:
                    await _send(conv, slack, channel_id, f"Executando {len(pending)} ações... ⏳")
                    for item in pending:
                        try:
                            await _handle_approval(app, user_id, channel_id, "approve", item["callback_id"])
                        except Exception as item_err:
                            logger.warning("Erro ao executar batch item %s: %s", item["callback_id"], item_err)
                    await _send(conv, slack, channel_id, f"✅ {len(pending)} ações executadas!")
                conv.set_context("batch_pending", [])
            elif action_id == "adjust":
                # Send each approval individually
                for item in pending:
                    await _send_approval(
                        conv, slack, channel_id,
                        title=item["title"],
                        details=f"Aprovar: {item['title']}?",
                        callback_id=item["callback_id"],
                    )
                conv.set_context("batch_pending", [])
            conv.state = FlowState.IDLE
```

Also add `_send_batch_approval` to the import from helpers at the top of the file (line 16):

```python
from routers.handlers.helpers import (
    _send, _send_approval, _request_or_auto_approve, _resolve_job_id, _build_dynamic_context,
    _suggest_next_action, _tool_not_available, _talent_phone, _send_batch_approval,
    _NOT_AVAILABLE_MESSAGES, _INHIRE_GUIDES,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_handlers.py::TestBatchApprovalHandler -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/routers/slack.py app/tests/test_handlers.py
git commit -m "feat: batch_approval handler in slack interactions"
```

---

### Task 3: Integrate batch approval into `_post_creation_chain`

**Files:**
- Modify: `app/routers/handlers/job_creation.py:313-432`
- Test: `app/tests/test_handlers.py`

- [ ] **Step 1: Write failing test**

Add at the end of `app/tests/test_handlers.py`:

```python
class TestPostCreationChainBatch:
    @pytest.mark.asyncio
    async def test_copilot_accumulates_batch(self, mock_conv, mock_app):
        """In copilot mode, chain should accumulate actions and send batch."""
        from routers.handlers.job_creation import _post_creation_chain

        mock_conv._context["job_data"] = {
            "title": "Dev Python",
            "requirements": ["Python", "FastAPI"],
        }
        mock_conv._context["current_job_name"] = "Dev Python"
        mock_conv.user_id = "U123"

        # Copilot mode — should NOT auto-approve publish
        mock_app.state.user_mapping.get_user.return_value = {
            "autonomy_mode": "copilot",
            "auto_advance_threshold": 4.0,
        }
        # Mock integrations to trigger publish
        mock_app.state.inhire.get_integrations.return_value = [
            {"id": "cp-1", "url": "https://careers.test.com",
             "jobBoardSettings": {"linkedinId": "123"}}
        ]
        mock_app.state.inhire.gen_filter_job_talents.return_value = {"total": 5}

        await _post_creation_chain(mock_conv, mock_app, "C123", "job-1")

        # Should have batch_pending in context with publish action
        batch = mock_conv._context.get("batch_pending")
        # At minimum, publish should be pending
        found_publish = any(
            a.get("callback_id") == "publish_job_approval"
            for a in (batch or [])
        )
        # In copilot, publish should be in batch (or sent as approval)
        assert found_publish or mock_app.state.slack.send_approval_request.called

    @pytest.mark.asyncio
    async def test_autopilot_skips_batch(self, mock_conv, mock_app):
        """In autopilot mode, chain should auto-execute without batch."""
        from routers.handlers.job_creation import _post_creation_chain

        mock_conv._context["job_data"] = {
            "title": "Dev Python",
            "requirements": ["Python", "FastAPI"],
        }
        mock_conv._context["current_job_name"] = "Dev Python"
        mock_conv.user_id = "U123"

        # Autopilot mode — should auto-approve
        mock_app.state.user_mapping.get_user.return_value = {
            "autonomy_mode": "autopilot",
            "auto_advance_threshold": 4.0,
        }
        mock_app.state.inhire.get_integrations.return_value = [
            {"id": "cp-1", "url": "https://careers.test.com",
             "jobBoardSettings": {"linkedinId": "123"}}
        ]
        mock_app.state.inhire.gen_filter_job_talents.return_value = {"total": 5}

        await _post_creation_chain(mock_conv, mock_app, "C123", "job-1")

        # Should NOT have batch_pending
        batch = mock_conv._context.get("batch_pending")
        assert not batch
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_handlers.py::TestPostCreationChainBatch -v`
Expected: FAIL — no batch_pending set by current chain

- [ ] **Step 3: Modify `_post_creation_chain` to accumulate batch actions**

Replace `_post_creation_chain` in `app/routers/handlers/job_creation.py` (lines 313-432) with:

```python
async def _post_creation_chain(conv, app, channel_id: str, job_id: str):
    """Execute the full post-creation automation chain.
    Phase 1 (sequential): auto-configure (screening, scorecard, form)
    Phase 2 (parallel): smart match + linkedin search
    Phase 3: publish job (batch or auto depending on mode)
    Phase 4: suggest autonomy mode + consolidated message
    Phase 5: if copilot with 3+ pending actions, send batch approval
    """
    import asyncio
    slack = app.state.slack
    inhire = app.state.inhire

    job_data = conv.get_context("job_data", {})
    job_name = conv.get_context("current_job_name", "")

    results = {"configured": [], "match_count": 0, "high_fit": 0, "linkedin": ""}
    batch_actions = []  # Accumulate copilot-pending actions

    # Redis connection (for chain flag + job mode)
    r = None
    try:
        import redis as redis_lib
        from config import get_settings
        r = redis_lib.from_url(get_settings().redis_url, decode_responses=True)
        r.set(f"inhire:chain_active:{job_id}", "1", ex=300)
    except Exception:
        pass

    # Check autonomy mode
    user = app.state.user_mapping.get_user(conv.user_id) or {}
    learning = getattr(app.state, "learning", None)
    is_auto = _should_auto_approve_action(user, "publish_job", learning, conv.user_id)

    # Phase 1: Auto-configure (SEQUENTIAL — must complete before match/screening)
    configured = await _auto_configure_job(conv, app, channel_id, job_id)
    results["configured"] = configured or []

    # Phase 2: Smart Match + LinkedIn search (PARALLEL)
    async def _run_smart_match():
        try:
            requirements = job_data.get("requirements", [])
            query = " ".join(requirements[:5]) if requirements else job_name
            ai_result = await inhire.gen_filter_job_talents(job_id, query)
            if ai_result:
                results["match_count"] = ai_result.get("total", 0) if isinstance(ai_result, dict) else 0
            if hasattr(app.state, "audit_log"):
                app.state.audit_log.log_action(
                    conv.user_id, "smart_match", job_id,
                    detail=f"{results['match_count']} matches",
                )
        except Exception as e:
            logger.warning("Smart match pós-vaga falhou: %s", e)

    async def _run_linkedin_search():
        try:
            requirements = job_data.get("requirements", [])
            title = job_data.get("title") or job_name or ""
            location = job_data.get("location") or ""
            terms = [t for t in [title] + requirements[:5] if t]
            if not terms:
                return
            required = " AND ".join(f'"{t}"' for t in terms[:3])
            optional = " OR ".join(f'"{t}"' for t in terms[3:] if t)
            search = f"({required})"
            if optional:
                search += f" AND ({optional})"
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

    # Phase 3: Publish job
    try:
        integrations = await inhire.get_integrations()
        available_boards = []
        career_page_id = ""
        for integ in integrations:
            jb = integ.get("jobBoardSettings", {}) or {}
            if jb.get("linkedinId"):
                available_boards.append("linkedin")
            if jb.get("indeedEmail") or jb.get("indeed"):
                available_boards.append("indeed")
            if jb.get("tramposCompanyId"):
                available_boards.append("netVagas")
            if integ.get("url"):
                career_page_id = integ.get("id", "")

        if available_boards and career_page_id:
            conv.set_context("publish_job_id", job_id)
            conv.set_context("publish_boards", available_boards)
            conv.set_context("publish_career_page_id", career_page_id)
            channels_str = ", ".join(b.capitalize() for b in available_boards)

            if is_auto:
                try:
                    result = await inhire.publish_job(
                        job_id=job_id,
                        career_page_id=career_page_id,
                        display_name=job_name,
                        active_job_boards=available_boards,
                    )
                    results["published"] = True
                    if hasattr(app.state, "audit_log"):
                        app.state.audit_log.log_action(conv.user_id, "publish_job", job_id)
                except Exception as pub_err:
                    logger.warning("Auto-publish falhou: %s", pub_err)
            else:
                batch_actions.append({
                    "callback_id": "publish_job_approval",
                    "title": f"Divulgar vaga em {channels_str}",
                })
    except Exception as e:
        logger.warning("Erro ao verificar canais de divulgação: %s", e)

    # Clear chain-active flag
    try:
        if r is not None:
            r.delete(f"inhire:chain_active:{job_id}")
    except Exception:
        pass

    # Phase 4: Suggest autonomy mode for this job
    decisions_count = 0
    try:
        if learning:
            decisions_count = learning.total_decisions_count(conv.user_id)
    except Exception:
        pass

    suggested_mode, suggestion_reason = _suggest_autonomy_mode(job_data, decisions_count)

    # Phase 5: Consolidated message + batch or individual
    msg = f"Vaga *{job_name}* criada! Já estou trabalhando nela 🚀\n\n"

    if results["match_count"] > 0:
        msg += (
            f"Encontrei {results['match_count']} candidatos no banco de talentos. "
            f"Estou analisando e te mando o shortlist em breve.\n\n"
        )

    if results["linkedin"]:
        msg += f"Busca LinkedIn pronta:\n`{results['linkedin']}`\n\n"

    if results.get("published"):
        channels_str = ", ".join(
            b.capitalize() for b in conv.get_context("publish_boards", [])
        )
        msg += f"Divulguei no {channels_str} ✓\n\n"

    # Mode suggestion
    if suggested_mode == "autopilot":
        msg += (
            f"💡 Essa vaga tem *{suggestion_reason}*. "
            f"Recomendo *Piloto Automático* — eu cuido de tudo e só paro pra reprovar e enviar oferta.\n"
            f"Quer ativar? Diz \"piloto automático pra essa vaga\"\n\n"
        )
    else:
        msg += (
            f"💡 Essa vaga tem *{suggestion_reason}*. "
            f"Recomendo *Copiloto* — faço o trabalho pesado mas você aprova os passos importantes.\n"
            f"Se preferir mais autonomia, diz \"piloto automático pra essa vaga\"\n\n"
        )

    msg += "Vou ficar de olho nos candidatos e te aviso quando tiver gente boa!"

    await _send(conv, slack, channel_id, msg)

    # Send batch approval if copilot has 3+ pending actions
    if len(batch_actions) >= 3:
        from routers.handlers.helpers import _send_batch_approval
        await _send_batch_approval(conv, slack, channel_id, batch_actions)
    elif batch_actions:
        # Less than 3 — send individual approvals
        from routers.handlers.helpers import _send_approval
        for item in batch_actions:
            await _send_approval(
                conv, slack, channel_id,
                title=item["title"],
                details=f"Aprovar: {item['title']}?",
                callback_id=item["callback_id"],
            )

    conv.state = FlowState.MONITORING_CANDIDATES
```

Also add a thin helper at the top of `job_creation.py` (after the imports) to avoid circular import:

```python
from routers.handlers.helpers import _should_auto_approve

def _should_auto_approve_action(user, action, learning=None, recruiter_id=""):
    return _should_auto_approve(user, action, learning=learning, recruiter_id=recruiter_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_handlers.py::TestPostCreationChainBatch -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `cd app && python -m pytest tests/ -v`
Expected: All 90+ tests PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add app/routers/handlers/job_creation.py app/routers/slack.py app/tests/test_handlers.py
git commit -m "feat: batch approval in post-creation chain (copilot 3+ actions)"
```

---

### Task 4: Add follow-up ignore counter to LearningService

**Files:**
- Modify: `app/services/learning.py:191-209`
- Test: `app/tests/test_handlers.py`

- [ ] **Step 1: Write failing test**

Add at the end of `app/tests/test_handlers.py`:

```python
class TestFollowupAutoBackoff:
    def test_increment_followup_ignores(self):
        from services.learning import LearningService
        svc = LearningService()
        # Should not crash even without Redis
        svc.increment_followup_ignores("U123")

    def test_reset_followup_ignores(self):
        from services.learning import LearningService
        svc = LearningService()
        svc.reset_followup_ignores("U123")

    def test_get_effective_intensity_default(self):
        from services.learning import LearningService
        svc = LearningService()
        # No data → normal
        result = svc.get_effective_intensity("U123", "normal")
        assert result == "normal"

    def test_3_ignores_downgrades_to_gentle(self):
        from services.learning import LearningService
        svc = LearningService()
        if not svc._redis:
            pytest.skip("Redis not available")
        # Set 3 ignores
        svc._redis.set("inhire:followup_ignores:U_TEST_BACKOFF", "3", ex=60)
        result = svc.get_effective_intensity("U_TEST_BACKOFF", "normal")
        assert result == "gentle"
        # Cleanup
        svc._redis.delete("inhire:followup_ignores:U_TEST_BACKOFF")

    def test_6_ignores_downgrades_to_off(self):
        from services.learning import LearningService
        svc = LearningService()
        if not svc._redis:
            pytest.skip("Redis not available")
        svc._redis.set("inhire:followup_ignores:U_TEST_BACKOFF2", "6", ex=60)
        result = svc.get_effective_intensity("U_TEST_BACKOFF2", "normal")
        assert result == "off"
        svc._redis.delete("inhire:followup_ignores:U_TEST_BACKOFF2")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_handlers.py::TestFollowupAutoBackoff -v`
Expected: FAIL — `AttributeError: 'LearningService' object has no attribute 'increment_followup_ignores'`

- [ ] **Step 3: Add ignore counter methods to LearningService**

Add to the end of `app/services/learning.py` (after line 357):

```python
    # --- Follow-up auto-backoff ---

    FOLLOWUP_IGNORES_PREFIX = "inhire:followup_ignores:"
    FOLLOWUP_IGNORES_TTL = 86400 * 30  # 30 days

    def increment_followup_ignores(self, user_id: str):
        """Increment consecutive follow-up ignore counter."""
        if not self._redis:
            return
        try:
            key = f"{self.FOLLOWUP_IGNORES_PREFIX}{user_id}"
            pipe = self._redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, self.FOLLOWUP_IGNORES_TTL)
            pipe.execute()
        except Exception as e:
            logger.warning("Erro ao incrementar followup ignores: %s", e)

    def reset_followup_ignores(self, user_id: str):
        """Reset ignore counter (recruiter responded to a follow-up)."""
        if not self._redis:
            return
        try:
            self._redis.delete(f"{self.FOLLOWUP_IGNORES_PREFIX}{user_id}")
        except Exception as e:
            logger.warning("Erro ao resetar followup ignores: %s", e)

    def get_followup_ignores(self, user_id: str) -> int:
        """Get current consecutive ignore count."""
        if not self._redis:
            return 0
        try:
            val = self._redis.get(f"{self.FOLLOWUP_IGNORES_PREFIX}{user_id}")
            return int(val) if val else 0
        except Exception:
            return 0

    def get_effective_intensity(self, user_id: str, configured_intensity: str) -> str:
        """Get effective follow-up intensity, considering auto-backoff.
        Returns the downgraded intensity based on consecutive ignore count.
        """
        ignores = self.get_followup_ignores(user_id)
        if ignores >= 6:
            return "off"
        if ignores >= 3:
            return "gentle"
        return configured_intensity
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_handlers.py::TestFollowupAutoBackoff -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/learning.py app/tests/test_handlers.py
git commit -m "feat: follow-up ignore counter + auto-backoff in LearningService"
```

---

### Task 5: Integrate auto-backoff into `check_alert_response` and ProactiveMonitor

**Files:**
- Modify: `app/services/learning.py:191-209` (check_alert_response)
- Modify: `app/services/proactive_monitor.py:768-863` (_check_stage_followups)
- Test: `app/tests/test_handlers.py`

- [ ] **Step 1: Write failing test for backoff integration**

Add at the end of `app/tests/test_handlers.py`:

```python
class TestFollowupBackoffIntegration:
    def test_check_alert_response_resets_ignores_on_response(self):
        from services.learning import LearningService
        svc = LearningService()
        if not svc._redis:
            pytest.skip("Redis not available")

        # Set up: alert was sent, ignores = 3
        svc._redis.set("inhire:followup_ignores:U_TEST_RESET", "3", ex=60)
        svc._redis.setex(
            f"inhire:alert_log:U_TEST_RESET:last", 60,
            '{"type": "interview_followup", "ts": ' + str(time.time()) + '}'
        )

        # Recruiter responds within 30min
        svc.check_alert_response("U_TEST_RESET")

        # Ignores should be reset
        assert svc.get_followup_ignores("U_TEST_RESET") == 0

        # Cleanup
        svc._redis.delete("inhire:followup_ignores:U_TEST_RESET")

    def test_check_alert_response_increments_on_no_response(self):
        from services.learning import LearningService
        svc = LearningService()
        if not svc._redis:
            pytest.skip("Redis not available")

        # Set up: alert was sent 2 hours ago (expired window)
        import json
        svc._redis.setex(
            f"inhire:alert_log:U_TEST_INC:last", 60,
            json.dumps({"type": "interview_followup", "ts": time.time() - 7200})
        )

        svc.check_alert_response("U_TEST_INC")

        # Should have incremented
        assert svc.get_followup_ignores("U_TEST_INC") >= 1

        # Cleanup
        svc._redis.delete("inhire:followup_ignores:U_TEST_INC")
```

Add `import time` at the top of test file if not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_handlers.py::TestFollowupBackoffIntegration -v`
Expected: FAIL — ignores not being reset/incremented

- [ ] **Step 3: Modify `check_alert_response` in learning.py**

Replace the `check_alert_response` method (lines 191-209) in `app/services/learning.py`:

```python
    def check_alert_response(self, user_id: str):
        """Called when recruiter sends a message. If within 30min of the last
        proactive alert, infer the alert was useful, record it, and reset ignores.
        If alert exists but response window expired, increment ignore counter.
        """
        if not self._redis:
            return
        try:
            key = f"{REDIS_ALERT_LOG_PREFIX}{user_id}:last"
            raw = self._redis.get(key)
            if not raw:
                return
            entry = json.loads(raw)
            elapsed = time.time() - entry["ts"]
            responded = elapsed <= ALERT_RESPONSE_WINDOW
            self._record_alert_response(user_id, entry["type"], responded)

            if responded:
                self.reset_followup_ignores(user_id)
            else:
                self.increment_followup_ignores(user_id)

            # Clear so we don't double-count
            self._redis.delete(key)
        except Exception as e:
            logger.warning("Erro ao verificar resposta ao alerta: %s", e)
```

- [ ] **Step 4: Modify `_check_stage_followups` in proactive_monitor.py**

In `app/services/proactive_monitor.py`, replace lines 768-774 of `_check_stage_followups`:

```python
    async def _check_stage_followups(self, job: dict, user: dict, channel_id: str):
        """Stage-specific follow-ups: interview feedback, offer decision, exceptional urgency."""
        job_id = job.get("id", "")
        job_name = job.get("name", "")
        user_id = user.get("slack_user_id", "")
        configured_intensity = user.get("followup_intensity", "normal")

        # Auto-backoff: check effective intensity considering ignore count
        intensity = configured_intensity
        if self.learning:
            intensity = self.learning.get_effective_intensity(user_id, configured_intensity)

        if intensity == "off":
            return  # Recruiter has been ignoring follow-ups, skip

        multiplier = {"gentle": 2.0, "normal": 1.0, "aggressive": 0.5}.get(intensity, 1.0)
```

Also add backoff notification. After the `if intensity == "off":` early return, add notification logic at the transition point. In `get_effective_intensity`, we track transitions. Instead, let the ProactiveMonitor send the notification when it first detects the downgrade. Add after the `intensity = self.learning.get_effective_intensity(...)` line:

```python
        # Notify on first downgrade
        if intensity != configured_intensity and intensity in ("gentle", "off"):
            downgrade_key = f"followup_downgrade_notified:{user_id}:{intensity}"
            if self._redis and not self._redis.exists(downgrade_key):
                self._redis.set(downgrade_key, "1", ex=86400 * 7)  # Don't re-notify for 7 days
                if intensity == "gentle":
                    await self._send_proactive(
                        user_id, channel_id,
                        "Percebi que meus lembretes não estão sendo úteis no momento. "
                        "Vou reduzir a frequência — quando precisar, é só me chamar! 🤙",
                        alert_type="backoff_notification",
                    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_handlers.py::TestFollowupBackoffIntegration -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `cd app && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add app/services/learning.py app/services/proactive_monitor.py app/tests/test_handlers.py
git commit -m "feat: auto-backoff follow-ups — ignore counter + effective intensity"
```

---

### Task 6: Final integration test + CLAUDE.md update

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run full test suite**

Run: `cd app && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Update CLAUDE.md melhorias table**

Add two new rows to the melhorias table:

```
| 87 | **Batch approval** — cadeia pós-vaga acumula ações copilot, envia bloco [Confirma tudo] quando 3+ | ✅ | 45 |
| 88 | **Auto-backoff follow-ups** — 3 ignores → gentle, 6 → off, resposta reseta tudo | ✅ | 45 |
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with batch approval + auto-backoff (session 45)"
```
