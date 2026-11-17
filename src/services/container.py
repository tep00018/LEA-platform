"""Builds every LEA service once per process and wires them together.

    services = build_services()
    services.quiz.start("alice", "AIML101", 1)

Streamlit caches the result with ``st.cache_resource``; the API (Phase 3) will build it
at startup. Every service is safe to call from several threads at once: per-learner state
lives in Redis, guarded by locks where it is read, changed and written back.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Optional

from openai import OpenAI

from src.auth.auth_service import AuthService
from src.core.redact import install_log_redaction
from src.auth.rate_limit import RateLimiter
from src.core.agent_orchestrator_mcp import LEAOrchestratorMCP
from src.core.course_registry import CourseRegistry, default_registry
from src.core.kc_model_loader import KCModelLoader
from src.core.progress_integration import ProgressIntegrationBridge
from src.core.research_logs import DecisionLogger
from src.core.scaffolding_engine import ScaffoldingEngine
from src.mcp.mcp_server import LEAMCPServer
from src.quiz.simple_quiz_system import SimpleQuizSystem
from src.services.accounts import AccountService
from src.services.analytics import AnalyticsService
from src.services.audit import AuditService
from src.services.videos import VideoService
from src.services.chat import ChatService
from src.services.courses import CourseService
from src.services.events import EventRecorder
from src.services.learning import LearningService
from src.services.preview import PreviewService
from src.services.progress import ProgressService
from src.services.quiz import QuizService
from src.services.session_store import SessionStore
from src.services.course_setup import CourseSetupService
from src.services.jobs import JobService
from src.services.kc_versions import KCVersionService
from src.services.staff import StaffService
from src.services.tutor import TutorService
from src.storage.consolidation_worker import MemoryConsolidationWorker
from src.storage.event_log import EventLog
from src.tutor.simple_tutor_system import SimpleTutorSystem

logger = logging.getLogger(__name__)


@dataclass
class Services:
    accounts: AccountService
    courses: CourseService
    progress: ProgressService
    learning: LearningService
    chat: ChatService
    quiz: QuizService
    tutor: TutorService
    # Lower-level pieces, for tests and tools
    redis_client: object = None
    orchestrator: Optional[LEAOrchestratorMCP] = None
    registry: Optional[CourseRegistry] = None
    rate_limiter: Optional[RateLimiter] = None
    events: Optional[EventRecorder] = None
    staff: Optional[StaffService] = None
    setup: Optional[CourseSetupService] = None
    jobs: Optional[JobService] = None
    kc: Optional[KCVersionService] = None
    preview: Optional[PreviewService] = None
    audit: Optional[AuditService] = None
    videos: Optional[VideoService] = None
    analytics: Optional[AnalyticsService] = None
    _worker: Optional[MemoryConsolidationWorker] = field(default=None, repr=False)
    _worker_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def start_background_work(self, jobs: bool = False) -> None:
        """Start the memory-consolidation worker (once per process), and with ``jobs`` the
        onboarding-job worker. Only the API runs jobs (the Teacher area is API-only), so
        Streamlit's process never competes for them."""
        if jobs and self.jobs is not None:
            self.jobs.start_worker()
        with self._worker_lock:
            if self._worker is None and self.redis_client is not None:
                self._worker = MemoryConsolidationWorker(self.redis_client, os.getenv("OPENAI_API_KEY"))
                self._worker.start_in_background()
                logger.info("Memory consolidation worker started")


def event_log_path(registry: CourseRegistry) -> str:
    """``LEA_EVENTS_DB``, or ``lea_events.db`` in the data folder."""
    return os.getenv("LEA_EVENTS_DB") or str(registry.data_dir / "lea_events.db")


def build_services(redis_url: Optional[str] = None, openai_client=None,
                   registry: Optional[CourseRegistry] = None) -> Services:
    install_log_redaction()  # API keys, tokens and URL passwords never reach a log, whatever logs them
    redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
    registry = registry or default_registry()
    # A bounded timeout: a stalled request fails with a message instead of hanging.
    openai_client = openai_client or OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=60, max_retries=2)

    auth = AuthService(redis_url)
    redis_client = auth.redis_client  # one LEARedisClient (connection pool) for everything

    try:
        event_log = EventLog(event_log_path(registry))
    except Exception as e:  # LEA still runs; the failure is loud in the log
        logger.error(f"The event log couldn't be opened: {e}")
        event_log = None
    events = EventRecorder(event_log, os.getenv("LEA_EVENT_SALT"), redis_client,
                           kc_model=registry.kc_model, kc_version=registry.kc_version)

    mcp_server = LEAMCPServer(redis_client)
    registry_tools = mcp_server.tool_registry
    orchestrator = LEAOrchestratorMCP(
        mcp_server, redis_client, openai_client=openai_client,
        scaffolding_engine=ScaffoldingEngine(redis_client),
        decision_logger=DecisionLogger(registry.data_dir, events=events),
    )
    progress_bridge = ProgressIntegrationBridge(redis_client, registry_tools.mastery_tracker,
                                                kc_model_provider=registry.kc_model)

    def kc_loader_factory(course: str) -> KCModelLoader:
        return KCModelLoader(redis_client, module=course)

    courses = CourseService(registry, kc_loader_factory)
    rate_limiter = RateLimiter(redis_client)
    store = SessionStore(redis_client)
    learning = LearningService(orchestrator, progress_bridge, data_dir=registry.data_dir, events=events)

    quiz_system = SimpleQuizSystem(
        rag_tool=registry_tools.rag_tool, openai_client=openai_client, redis_client=redis_client,
        kc_loader_factory=courses.kc_loader,
    )
    videos = VideoService(registry, events, redis_client)
    tutor_system = SimpleTutorSystem(openai_client, redis_client, orchestrator.mcp_client,
                                     curated_videos=videos.curated)

    staff = StaffService(auth, events, courses.available)
    setup = CourseSetupService(redis_client, registry, staff, events)
    preview = PreviewService(auth, registry, events)
    learning.preview = preview
    chat = ChatService(orchestrator, store, redis_client, events=events)
    chat.preview = preview

    return Services(
        accounts=AccountService(auth, courses.available, rate_limiter, events),
        courses=courses,
        progress=ProgressService(progress_bridge),
        learning=learning,
        chat=chat,
        quiz=QuizService(quiz_system, learning, store),
        tutor=TutorService(tutor_system, learning, courses, store),
        redis_client=redis_client,
        orchestrator=orchestrator,
        registry=registry,
        rate_limiter=rate_limiter,
        events=events,
        staff=staff,
        setup=setup,
        jobs=JobService(redis_client, setup, events=events),
        kc=KCVersionService(registry, redis_client, setup, events),
        preview=preview,
        audit=AuditService(registry, events),
        videos=videos,
        analytics=AnalyticsService(registry, events, openai_client, course_content=learning.course_content),
    )
