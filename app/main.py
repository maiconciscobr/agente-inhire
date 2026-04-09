import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from config import get_settings
from routers import slack, webhooks, health, chrome_extension
from services.inhire_auth import InHireAuth
from services.inhire_client import InHireClient
from services.slack_client import SlackService
from services.claude_client import ClaudeService
from services.conversation import ConversationManager
from services.user_mapping import UserMapping
from services.learning import LearningService
from services.proactive_monitor import ProactiveMonitor
from services.talent_search import TalentSearchService
from services.routines import RoutineService

logger = logging.getLogger("agente-inhire")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    logger.info("Iniciando Agente InHire...")

    # Initialize services
    auth = InHireAuth(settings)
    await auth.login()

    app.state.inhire_auth = auth
    app.state.inhire = InHireClient(settings, auth)
    app.state.slack = SlackService(settings)
    app.state.claude = ClaudeService(settings)
    app.state.conversations = ConversationManager()
    app.state.user_mapping = UserMapping()
    app.state.learning = LearningService()
    app.state.talent_search = TalentSearchService(app.state.inhire)
    app.state.monitor = ProactiveMonitor(
        inhire=app.state.inhire,
        slack=app.state.slack,
        user_mapping=app.state.user_mapping,
        learning=app.state.learning,
        conversations=app.state.conversations,
        claude=app.state.claude,
    )

    # Start cron scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        app.state.monitor.check_all_jobs,
        "interval",
        hours=1,
        id="proactive_monitor",
    )
    # Daily briefing at 9h BRT (= 12h UTC)
    scheduler.add_job(
        app.state.monitor.send_daily_briefing,
        "cron",
        hour=12,
        minute=0,
        id="daily_briefing",
    )
    # Weekly pattern consolidation — Monday 9:30 BRT (= 12:30 UTC)
    scheduler.add_job(
        app.state.monitor.weekly_pattern_consolidation,
        "cron",
        day_of_week="mon",
        hour=12,
        minute=30,
        id="weekly_consolidation",
    )
    scheduler.start()
    app.state.scheduler = scheduler

    app.state.routines = RoutineService(
        redis_client=app.state.conversations._redis,
        scheduler=scheduler,
        slack=app.state.slack,
        inhire=app.state.inhire,
        claude=app.state.claude,
    )
    await app.state.routines.load_all()

    logger.info("Agente InHire iniciado. Cron: monitoramento (1h) + briefing (9h BRT) + consolidação semanal (seg 9:30 BRT) + rotinas customizadas.")
    yield

    scheduler.shutdown()
    await auth.close()
    await app.state.inhire.close()
    await app.state.talent_search.close()
    logger.info("Agente InHire encerrado.")


app = FastAPI(
    title="Agente InHire",
    description="Agente de recrutamento IA via Slack + InHire API",
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(slack.router, prefix="/slack")
app.include_router(webhooks.router, prefix="/webhooks")
app.include_router(chrome_extension.router, prefix="/extension")
