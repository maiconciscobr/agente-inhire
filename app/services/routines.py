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
    routine_type: str
    description: str
    job_id: str | None
    job_name: str | None
    hour: int
    minute: int
    days: str
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
        hour_brt = (self.hour - 3) % 24
        days_label = {
            "mon-fri": "seg-sex",
            "*": "todo dia",
            "mon": "seg", "tue": "ter", "wed": "qua",
            "thu": "qui", "fri": "sex", "sat": "sab", "sun": "dom",
        }
        d = days_label.get(self.days, self.days)
        return f"{hour_brt}h{self.minute:02d} ({d})"


class RoutineService:
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
        routines = self._load_user_routines(user_id)
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
        from apscheduler.triggers.cron import CronTrigger
        if routine.days == "mon-fri":
            day_of_week = "mon-fri"
        elif routine.days == "*":
            day_of_week = "*"
        else:
            day_of_week = routine.days
        trigger = CronTrigger(hour=routine.hour, minute=routine.minute, day_of_week=day_of_week)
        self._scheduler.add_job(
            self.execute, trigger, args=[routine],
            id=routine.scheduler_job_id, replace_existing=True,
        )

    def _unregister_job(self, routine: Routine):
        try:
            self._scheduler.remove_job(routine.scheduler_job_id)
        except Exception:
            pass

    async def load_all(self):
        if not self._redis:
            return
        user_ids = self._redis.smembers(REDIS_ROUTINES_INDEX)
        count = 0
        for user_id in user_ids:
            for routine in self._load_user_routines(user_id):
                self._register_job(routine)
                count += 1
        if count:
            logger.info("Carregadas %d rotinas customizadas.", count)

    async def execute(self, routine: Routine):
        try:
            msg = await self._run_routine_action(routine)
            if msg:
                await self.slack.send_message(routine.channel_id, msg)
                routines = self._load_user_routines(routine.user_id)
                for r in routines:
                    if r.id == routine.id:
                        r.last_run = datetime.now(timezone.utc).isoformat()
                        break
                self._save_user_routines(routine.user_id, routines)
        except Exception as e:
            logger.exception("Erro ao executar rotina %s: %s", routine.id, e)

    async def _run_routine_action(self, routine: Routine) -> str | None:
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
            return f"Não consegui acessar a vaga *{routine.job_name or 'sem nome'}*. Ela ainda está aberta?"
        cutoff = routine.last_run or (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        new_talents = []
        for t in talents:
            created = t.get("createdAt", "")
            if created > cutoff:
                name = (t.get("talent", {}) or {}).get("name") or t.get("talentName", "Sem nome")
                new_talents.append(name)
        if not new_talents:
            return None
        msg = f"📋 *Novos candidatos — {routine.job_name}*\n\n"
        for i, name in enumerate(new_talents, 1):
            msg += f"{i}. {name}\n"
        msg += f"\n_{len(new_talents)} novo(s) desde a última verificação._"
        return msg

    async def _action_status_vagas(self, routine: Routine) -> str | None:
        try:
            jobs = await self.inhire._request("POST", "/jobs/paginated/lean", json={"limit": 50})
            results = jobs.get("results", [])
        except Exception:
            return "Não consegui acessar suas vagas no momento."
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
            return f"Não consegui acessar a vaga *{routine.job_name or 'sem nome'}*."
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
            return "Não consegui gerar o resumo semanal."
        active = [j for j in results if j.get("status") == "published"]
        total_talents = sum(j.get("talentsCount", 0) for j in active)
        msg = (
            f"📅 *Resumo semanal*\n\n"
            f"• *{len(active)}* vagas ativas\n"
            f"• *{total_talents}* candidatos no total\n"
        )
        top = sorted(active, key=lambda j: j.get("talentsCount", 0), reverse=True)[:3]
        if top:
            msg += "\n*Mais movimentadas:*\n"
            for j in top:
                msg += f"  • {j.get('name', '?')} — {j.get('talentsCount', 0)} candidato(s)\n"
        return msg
