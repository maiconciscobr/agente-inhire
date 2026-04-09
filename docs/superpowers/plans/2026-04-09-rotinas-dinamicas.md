# Rotinas Dinamicas do Eli — Plano de Implementacao

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que recrutadores criem rotinas personalizadas (somente leitura) via linguagem natural no Slack, com persistencia Redis e execucao via APScheduler.

**Architecture:** Novo servico `RoutineService` gerencia CRUD de rotinas em Redis e registro/remocao de jobs no APScheduler em runtime. Claude classifica pedidos via `parse_routine_request()`. Handler `_handle_routine()` no slack.py orquestra o fluxo.

**Tech Stack:** Python 3.12, APScheduler (AsyncIOScheduler + CronTrigger), Redis, Anthropic SDK, FastAPI

---

### Task 1: Criar `services/routines.py` — modelo Routine + RoutineService (CRUD Redis)

**Files:**
- Create: `app/services/routines.py`
- Create: `app/tests/test_routines.py`

- [ ] **Step 1: Criar arquivo `app/services/routines.py` com dataclass Routine e RoutineService**

```python
import json
import logging
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("agente-inhire.routines")

REDIS_ROUTINES_PREFIX = "eli:routines:"
REDIS_ROUTINES_INDEX = "eli:routines:all_users"
MAX_ROUTINES_PER_USER = 5
BRT = timezone(timedelta(hours=-3))


@dataclass
class Routine:
    id: str
    user_id: str
    channel_id: str
    routine_type: str  # novos_candidatos | status_vagas | shortlist_update | resumo_semanal
    description: str
    job_id: str | None
    job_name: str | None
    hour: int      # UTC
    minute: int
    days: str      # "mon-fri" | "mon,wed,fri" | "fri" | "*"
    created_at: str
    last_run: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Routine":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @property
    def scheduler_job_id(self) -> str:
        return f"routine:{self.id}"

    def human_schedule(self) -> str:
        hour_brt = (self.hour - 3) % 24  # UTC to BRT naive
        days_label = {
            "mon-fri": "seg-sex",
            "*": "todo dia",
            "mon": "seg", "tue": "ter", "wed": "qua",
            "thu": "qui", "fri": "sex", "sat": "sab", "sun": "dom",
        }
        d = days_label.get(self.days, self.days)
        return f"{hour_brt}h{self.minute:02d} ({d})"


class RoutineService:
    """Manages custom routines: CRUD in Redis + APScheduler registration."""

    def __init__(self, redis_client, scheduler, slack, inhire, claude):
        self._redis = redis_client
        self._scheduler = scheduler
        self.slack = slack
        self.inhire = inhire
        self.claude = claude

    def _user_key(self, user_id: str) -> str:
        return f"{REDIS_ROUTINES_PREFIX}{user_id}"

    def _load_user_routines(self, user_id: str) -> list[Routine]:
        if not self._redis:
            return []
        data = self._redis.get(self._user_key(user_id))
        if not data:
            return []
        return [Routine.from_dict(r) for r in json.loads(data)]

    def _save_user_routines(self, user_id: str, routines: list[Routine]):
        if not self._redis:
            return
        self._redis.set(self._user_key(user_id), json.dumps([r.to_dict() for r in routines]))
        if routines:
            self._redis.sadd(REDIS_ROUTINES_INDEX, user_id)
        else:
            self._redis.srem(REDIS_ROUTINES_INDEX, user_id)

    def create(self, user_id: str, channel_id: str, routine_type: str,
               description: str, hour_utc: int, minute: int, days: str,
               job_id: str | None = None, job_name: str | None = None) -> Routine | str:
        """Create a routine. Returns Routine on success, error string on failure."""
        routines = self._load_user_routines(user_id)

        if len(routines) >= MAX_ROUTINES_PER_USER:
            return f"Você já tem {MAX_ROUTINES_PER_USER} rotinas ativas. Cancele uma antes de criar outra."

        routine = Routine(
            id=str(uuid.uuid4())[:8],
            user_id=user_id,
            channel_id=channel_id,
            routine_type=routine_type,
            description=description,
            job_id=job_id,
            job_name=job_name,
            hour=hour_utc,
            minute=minute,
            days=days,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        routines.append(routine)
        self._save_user_routines(user_id, routines)
        self._register_job(routine)
        logger.info("Rotina criada: %s para user %s (%s)", routine.id, user_id, description)
        return routine

    def list(self, user_id: str) -> list[Routine]:
        return self._load_user_routines(user_id)

    def cancel(self, user_id: str, routine_id: str) -> Routine | None:
        """Cancel a routine by ID or index (1-based). Returns cancelled Routine or None."""
        routines = self._load_user_routines(user_id)

        # Try by index (1-based) if routine_id is a digit
        target = None
        if routine_id.isdigit():
            idx = int(routine_id) - 1
            if 0 <= idx < len(routines):
                target = routines[idx]
        else:
            target = next((r for r in routines if r.id == routine_id), None)

        if not target:
            return None

        self._unregister_job(target)
        routines = [r for r in routines if r.id != target.id]
        self._save_user_routines(user_id, routines)
        logger.info("Rotina cancelada: %s para user %s", target.id, user_id)
        return target

    def _register_job(self, routine: Routine):
        """Register a routine as a cron job in APScheduler."""
        from apscheduler.triggers.cron import CronTrigger

        # Parse days
        if routine.days == "mon-fri":
            day_of_week = "mon-fri"
        elif routine.days == "*":
            day_of_week = "*"
        else:
            day_of_week = routine.days

        trigger = CronTrigger(
            hour=routine.hour,
            minute=routine.minute,
            day_of_week=day_of_week,
        )

        self._scheduler.add_job(
            self.execute,
            trigger,
            args=[routine],
            id=routine.scheduler_job_id,
            replace_existing=True,
        )

    def _unregister_job(self, routine: Routine):
        try:
            self._scheduler.remove_job(routine.scheduler_job_id)
        except Exception:
            pass  # Job may not exist if scheduler restarted

    async def load_all(self):
        """Load all routines from Redis and register in scheduler. Called on startup."""
        if not self._redis:
            return
        user_ids = self._redis.smembers(REDIS_ROUTINES_INDEX)
        count = 0
        for user_id in user_ids:
            routines = self._load_user_routines(user_id)
            for routine in routines:
                self._register_job(routine)
                count += 1
        if count:
            logger.info("Carregadas %d rotinas de %d recrutadores.", count, len(user_ids))

    async def execute(self, routine: Routine):
        """Execute a routine and send result via Slack."""
        try:
            msg = await self._run_routine_action(routine)
            if msg:
                await self.slack.send_message(routine.channel_id, msg)
                # Update last_run
                routines = self._load_user_routines(routine.user_id)
                for r in routines:
                    if r.id == routine.id:
                        r.last_run = datetime.now(timezone.utc).isoformat()
                        break
                self._save_user_routines(routine.user_id, routines)
        except Exception as e:
            logger.exception("Erro ao executar rotina %s: %s", routine.id, e)

    async def _run_routine_action(self, routine: Routine) -> str | None:
        """Run the action for a routine type and return formatted message."""

        if routine.routine_type == "novos_candidatos":
            return await self._action_novos_candidatos(routine)
        elif routine.routine_type == "status_vagas":
            return await self._action_status_vagas(routine)
        elif routine.routine_type == "shortlist_update":
            return await self._action_shortlist_update(routine)
        elif routine.routine_type == "resumo_semanal":
            return await self._action_resumo_semanal(routine)
        return None

    async def _action_novos_candidatos(self, routine: Routine) -> str | None:
        if not routine.job_id:
            return None
        try:
            talents = await self.inhire.list_job_talents(routine.job_id)
        except Exception:
            return f"Nao consegui acessar a vaga *{routine.job_name or 'sem nome'}*. Ela ainda esta aberta?"

        # Filter talents added since last_run (or last 24h)
        cutoff = routine.last_run or (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        new_talents = []
        for t in talents:
            created = t.get("createdAt", "")
            if created > cutoff:
                name = (t.get("talent", {}) or {}).get("name") or t.get("talentName", "Sem nome")
                new_talents.append(name)

        if not new_talents:
            return None  # Silencioso se nao tem novidade

        msg = f"📋 *Novos candidatos — {routine.job_name}*\n\n"
        for i, name in enumerate(new_talents, 1):
            msg += f"{i}. {name}\n"
        msg += f"\n_{len(new_talents)} novo(s) desde a ultima verificacao._"
        return msg

    async def _action_status_vagas(self, routine: Routine) -> str | None:
        try:
            jobs = await self.inhire._request("POST", "/jobs/paginated/lean", json={"limit": 50})
            results = jobs.get("results", [])
        except Exception:
            return "Nao consegui acessar suas vagas no momento."

        active = [j for j in results if j.get("status") == "published"]
        if not active:
            return "Nenhuma vaga ativa no momento."

        msg = "📊 *Status das vagas ativas*\n\n"
        for j in active[:10]:
            name = j.get("name", "Sem nome")
            talents_count = j.get("talentsCount", 0)
            msg += f"• *{name}* — {talents_count} candidato(s)\n"
        return msg

    async def _action_shortlist_update(self, routine: Routine) -> str | None:
        if not routine.job_id:
            return None
        try:
            talents = await self.inhire.list_job_talents(routine.job_id)
        except Exception:
            return f"Nao consegui acessar a vaga *{routine.job_name or 'sem nome'}*."

        high_fit = []
        for t in talents:
            score = t.get("screeningScore") or t.get("score") or 0
            if isinstance(score, str):
                try:
                    score = float(score)
                except ValueError:
                    score = 0
            if score >= 4.0:
                name = (t.get("talent", {}) or {}).get("name") or t.get("talentName", "Sem nome")
                high_fit.append((name, score))

        if not high_fit:
            return None

        high_fit.sort(key=lambda x: x[1], reverse=True)
        msg = f"🎯 *Top candidatos — {routine.job_name}*\n\n"
        for i, (name, score) in enumerate(high_fit[:5], 1):
            msg += f"{i}. *{name}* — score {score:.1f}\n"
        return msg

    async def _action_resumo_semanal(self, routine: Routine) -> str | None:
        try:
            jobs = await self.inhire._request("POST", "/jobs/paginated/lean", json={"limit": 50})
            results = jobs.get("results", [])
        except Exception:
            return "Nao consegui gerar o resumo semanal."

        active = [j for j in results if j.get("status") == "published"]
        total_talents = sum(j.get("talentsCount", 0) for j in active)

        msg = (
            f"📅 *Resumo semanal*\n\n"
            f"• *{len(active)}* vagas ativas\n"
            f"• *{total_talents}* candidatos no total\n"
        )

        # Top vagas com mais candidatos
        top = sorted(active, key=lambda j: j.get("talentsCount", 0), reverse=True)[:3]
        if top:
            msg += "\n*Mais movimentadas:*\n"
            for j in top:
                msg += f"  • {j.get('name', '?')} — {j.get('talentsCount', 0)} candidato(s)\n"

        return msg
```

- [ ] **Step 2: Verificar que o arquivo foi criado corretamente**

Run: `python -c "from services.routines import RoutineService, Routine; print('OK')"`
(executar de dentro de `app/`)

- [ ] **Step 3: Commit**

```bash
git add app/services/routines.py
git commit -m "feat: RoutineService — CRUD de rotinas + execucao (sessao 36)"
```

---

### Task 2: Adicionar `parse_routine_request()` e tool `gerenciar_rotina` no claude_client.py

**Files:**
- Modify: `app/services/claude_client.py` (ELI_TOOLS + novo metodo)

- [ ] **Step 1: Adicionar tool `gerenciar_rotina` ao ELI_TOOLS (antes de `conversa_livre`)**

Inserir antes da tool `conversa_livre` no array ELI_TOOLS:

```python
    {
        "name": "gerenciar_rotina",
        "description": (
            "Cria, lista ou cancela rotinas automaticas do recrutador. "
            "Use quando o recrutador pedir algo recorrente "
            "(todo dia, toda semana, me avisa quando, de tempos em tempos, "
            "me manda X no horario Y, quero receber, rotina, agendar alerta, etc.) "
            "ou quiser ver/cancelar suas rotinas ativas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "O pedido completo do recrutador sobre rotinas",
                },
            },
            "required": ["request"],
        },
    },
```

- [ ] **Step 2: Adicionar metodo `parse_routine_request()` na classe ClaudeService**

Inserir apos `classify_briefing_reply()`:

```python
    async def parse_routine_request(self, text: str, available_jobs: list[dict]) -> dict:
        """Parse a routine request from natural language.

        Returns dict with:
            action: create | list | cancel
            routine_type: novos_candidatos | status_vagas | shortlist_update | resumo_semanal
            job_id: str | None
            job_name: str | None
            hour_brt: int
            minute: int
            frequency: weekdays | daily | weekly_<day>
            cancel_id: str (index or id, for cancel action)
            description: str
        """
        jobs_context = "\n".join(
            f"- {j.get('name', '?')} (ID: {j.get('id', '?')})"
            for j in available_jobs[:20]
        )

        system = (
            "Voce interpreta pedidos de rotinas automaticas de um recrutador.\n\n"
            "Vagas ativas disponiveis:\n" + (jobs_context or "(nenhuma)") + "\n\n"
            "Classifique o pedido e retorne JSON puro (sem markdown, sem ```):\n"
            "{\n"
            '  "action": "create" | "list" | "cancel",\n'
            '  "routine_type": "novos_candidatos" | "status_vagas" | "shortlist_update" | "resumo_semanal",\n'
            '  "job_id": "uuid" ou null,\n'
            '  "job_name": "nome da vaga" ou null,\n'
            '  "hour_brt": 8,\n'
            '  "minute": 0,\n'
            '  "frequency": "weekdays" | "daily" | "weekly_mon" | "weekly_fri" etc,\n'
            '  "cancel_id": "1" (numero ou id, so para cancel),\n'
            '  "description": "resumo curto do que a rotina faz"\n'
            "}\n\n"
            "Regras:\n"
            "- Se o recrutador quer listar, action=list (ignore outros campos)\n"
            "- Se quer cancelar, action=cancel + cancel_id\n"
            "- Se quer criar: preencha todos os campos\n"
            "- Horario padrao: 9h BRT se nao especificado\n"
            "- Frequencia padrao: weekdays (seg-sex) se nao especificado\n"
            "- novos_candidatos e shortlist_update precisam de vaga. Se nao mencionou, job_id=null\n"
            "- status_vagas e resumo_semanal nao precisam de vaga\n"
            "- Resolva o nome da vaga para o job_id correto da lista acima\n"
            "- Retorne APENAS o JSON, nada mais"
        )

        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=300,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": text}],
        )

        import json as json_mod
        raw = resp.content[0].text.strip()
        # Clean markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json_mod.loads(raw)
```

- [ ] **Step 3: Commit**

```bash
git add app/services/claude_client.py
git commit -m "feat: tool gerenciar_rotina + parse_routine_request (sessao 36)"
```

---

### Task 3: Adicionar handler `_handle_routine()` no slack.py

**Files:**
- Modify: `app/routers/slack.py` (import + handler + dispatch)

- [ ] **Step 1: Adicionar import do RoutineService no topo do slack.py**

Junto aos outros imports de handlers (linha ~29):

```python
from services.routines import RoutineService
```

- [ ] **Step 2: Adicionar handler `_handle_routine` antes de `_handle_waiting_approval`**

```python
async def _handle_routine(conv, app, channel_id: str, user_id: str, tool_input: dict):
    """Handle routine management (create, list, cancel)."""
    slack = app.state.slack
    claude = app.state.claude
    routines_svc: RoutineService = app.state.routines

    request_text = tool_input.get("request", "")

    # Get active jobs for context
    try:
        jobs_resp = await app.state.inhire._request("POST", "/jobs/paginated/lean", json={"limit": 50})
        active_jobs = [j for j in jobs_resp.get("results", []) if j.get("status") == "published"]
    except Exception:
        active_jobs = []

    try:
        parsed = await claude.parse_routine_request(request_text, active_jobs)
    except Exception as e:
        logger.warning("Erro ao interpretar pedido de rotina: %s", e)
        await _send(conv, slack, channel_id, "Nao entendi o pedido de rotina. Pode reformular?")
        return

    action = parsed.get("action", "list")

    if action == "list":
        user_routines = routines_svc.list(user_id)
        if not user_routines:
            await _send(conv, slack, channel_id, "Voce nao tem nenhuma rotina ativa. Quer criar uma?")
            return
        msg = "📋 *Suas rotinas ativas:*\n\n"
        for i, r in enumerate(user_routines, 1):
            job_info = f" — {r.job_name}" if r.job_name else ""
            msg += f"*{i}.* {r.description}{job_info} ({r.human_schedule()})\n"
        msg += "\nPra cancelar alguma, me avisa qual."
        await _send(conv, slack, channel_id, msg)
        return

    if action == "cancel":
        cancel_id = str(parsed.get("cancel_id", ""))
        cancelled = routines_svc.cancel(user_id, cancel_id)
        if cancelled:
            await _send(conv, slack, channel_id, f"Pronto, cancelei a rotina *{cancelled.description}*.")
        else:
            await _send(conv, slack, channel_id, "Nao encontrei essa rotina. Me diz o numero dela.")
        return

    # action == "create"
    routine_type = parsed.get("routine_type", "status_vagas")
    job_id = parsed.get("job_id")
    job_name = parsed.get("job_name")
    hour_brt = parsed.get("hour_brt", 9)
    minute = parsed.get("minute", 0)
    frequency = parsed.get("frequency", "weekdays")
    description = parsed.get("description", request_text[:100])

    # Validate: types that need a job
    if routine_type in ("novos_candidatos", "shortlist_update") and not job_id:
        await _send(
            conv, slack, channel_id,
            f"Pra essa rotina preciso saber qual vaga. Pode me dizer?"
        )
        return

    # Convert BRT to UTC
    hour_utc = (hour_brt + 3) % 24

    # Convert frequency to cron days
    freq_to_days = {
        "weekdays": "mon-fri",
        "daily": "*",
        "weekly_mon": "mon",
        "weekly_tue": "tue",
        "weekly_wed": "wed",
        "weekly_thu": "thu",
        "weekly_fri": "fri",
        "weekly_sat": "sat",
        "weekly_sun": "sun",
    }
    days = freq_to_days.get(frequency, "mon-fri")

    result = routines_svc.create(
        user_id=user_id,
        channel_id=channel_id,
        routine_type=routine_type,
        description=description,
        hour_utc=hour_utc,
        minute=minute,
        days=days,
        job_id=job_id,
        job_name=job_name,
    )

    if isinstance(result, str):
        await _send(conv, slack, channel_id, result)
        return

    await _send(
        conv, slack, channel_id,
        f"Rotina criada! Vou te mandar *{result.description}* "
        f"todo(a) {result.human_schedule()}. Quer cancelar, e so me avisar."
    )
```

- [ ] **Step 3: Adicionar dispatch no `_handle_idle`**

Antes do `elif tool == "conversa_livre":` (~linha 856), adicionar:

```python
    elif tool == "gerenciar_rotina":
        await _handle_routine(conv, app, channel_id, conv.user_id, tool_input)
```

- [ ] **Step 4: Commit**

```bash
git add app/routers/slack.py
git commit -m "feat: handler _handle_routine no slack.py (sessao 36)"
```

---

### Task 4: Integrar RoutineService no startup (main.py)

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Adicionar import**

```python
from services.routines import RoutineService
```

- [ ] **Step 2: Inicializar RoutineService no lifespan, DEPOIS de `scheduler.start()`**

Inserir apos `app.state.scheduler = scheduler` (linha 78):

```python
    app.state.routines = RoutineService(
        redis_client=app.state.conversations._redis,
        scheduler=scheduler,
        slack=app.state.slack,
        inhire=app.state.inhire,
        claude=app.state.claude,
    )
    await app.state.routines.load_all()
```

- [ ] **Step 3: Atualizar log de startup**

Alterar a mensagem de log (linha 80) para:

```python
    logger.info("Agente InHire iniciado. Cron: monitoramento (1h) + briefing (9h BRT) + consolidacao semanal (seg 9:30 BRT) + rotinas customizadas.")
```

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat: inicializar RoutineService no startup (sessao 36)"
```

---

### Task 5: Deploy e teste no servidor

**Files:**
- Deploy: `app/services/routines.py`, `app/services/claude_client.py`, `app/routers/slack.py`, `app/main.py`

- [ ] **Step 1: Copiar todos os arquivos modificados para o servidor**

```bash
for f in services/routines.py services/claude_client.py routers/slack.py main.py; do
  cat "app/$f" | ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97 "cat > /var/www/agente-inhire/$f"
done
```

- [ ] **Step 2: Restart do servico**

```bash
ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97 "systemctl restart agente-inhire"
```

- [ ] **Step 3: Verificar logs de startup**

```bash
ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97 "sleep 3 && journalctl -u agente-inhire --since '1 min ago' --no-pager"
```

Esperado: sem erros, log "Agente InHire iniciado" com mencao a rotinas customizadas.

- [ ] **Step 4: Testar no Slack**

Enviar no DM com o Eli:
1. "todo dia as 8h me manda os candidatos novos da vaga de DevOps"
2. "quais rotinas eu tenho?"
3. "cancela a rotina 1"

- [ ] **Step 5: Commit final + push**

```bash
git add -A
git commit -m "feat: rotinas dinamicas do Eli — sessao 36 completa"
git push origin main
```
