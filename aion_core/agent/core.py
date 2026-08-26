# Aion Hand - Core Agent Framework

import sys
import json
import time
import signal
import logging
import asyncio
from pathlib import Path
from typing import Any
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("aion_hand.log"),
    ],
)
logger = logging.getLogger("aion_hand")


class AgentState(Enum):
    """Agent lifecycle states - inspired by Hermes Agent and OpenClaw state machines."""
    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING = "executing"
    WAITING = "waiting"
    RESPONDING = "responding"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"
    SHUTDOWN = "shutdown"


@dataclass
class AgentConfig:
    """Central configuration for Aion Hand - combines OpenClaw's config structure 
    with NullClaw's provider agnosticism and Hermes's portal system."""

    # Identity
    name: str = "Aion Hand"
    version: str = "0.4.0"

    # Paths
    home_dir: Path = field(default_factory=lambda: Path.home() / ".aion-hand")
    data_dir: Path = field(default_factory=lambda: Path.home() / ".aion-hand" / "data")
    memory_dir: Path = field(default_factory=lambda: Path.home() / ".aion-hand" / "memory")
    skills_dir: Path = field(default_factory=lambda: Path.home() / ".aion-hand" / "skills")
    tools_dir: Path = field(default_factory=lambda: Path.home() / ".aion-hand" / "tools")
    logs_dir: Path = field(default_factory=lambda: Path.home() / ".aion-hand" / "logs")
    config_file: Path = field(default_factory=lambda: Path.home() / ".aion-hand" / "config.json")

    # Provider Settings (OpenClaw compatible snake_case)
    default_provider: str = "openai"
    default_model: str = "gpt-4o"
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Agent Settings
    max_turns: int = 50
    max_tokens: int = 4096
    temperature: float = 0.7
    context_window: int = 128000

    # Memory Settings (Hermes-inspired FTS5 + OpenClaw MEMORY.md)
    memory_enabled: bool = True
    memory_persist: bool = True
    memory_nudge_interval: int = 300  # seconds between memory nudges
    memory_max_entries: int = 10000

    # Skills Settings (Hermes-compatible agentskills.io)
    skills_enabled: bool = True
    skills_auto_create: bool = True
    skills_auto_improve: bool = True
    skills_hub_url: str = "https://agentskills.io"

    # Tool Settings (MCP compatible)
    tools_enabled: bool = True
    mcp_enabled: bool = True
    tool_approval_mode: str = "auto"  # auto, ask, deny

    # Orchestration Settings (NullBoiler + Hermes subagents)
    max_subagents: int = 5
    subagent_timeout: int = 300
    workflow_enabled: bool = True

    # Cron Settings (Hermes-inspired)
    cron_enabled: bool = True
    cron_timezone: str = "UTC"

    # Messaging Settings (OpenClaw gateway)
    messaging_enabled: bool = False
    platforms: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Security Settings
    sandbox_enabled: bool = True
    command_whitelist: list[str] = field(default_factory=list)
    allowed_users: list[str] = field(default_factory=list)

    # Pipeline & Subsystem Settings
    pipeline_enabled: bool = True
    knowledge_enabled: bool = True
    benchmark_enabled: bool = True
    dynamic_enabled: bool = True
    routing_enabled: bool = True

    # Performance (NullClaw-inspired lightweight mode)
    lightweight_mode: bool = False
    streaming_enabled: bool = True

    def save(self) -> None:
        """Save configuration to disk."""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        config_dict = {
            k: str(v) if isinstance(v, Path) else v
            for k, v in self.__dict__.items()
        }
        with open(self.config_file, "w") as f:
            json.dump(config_dict, f, indent=2, default=str)
        logger.info(f"Configuration saved to {self.config_file}")

    @classmethod
    def load(cls, path: Path | None = None) -> "AgentConfig":
        """Load configuration from disk."""
        config = cls()
        if path:
            config.config_file = path
        if config.config_file.exists():
            with open(config.config_file) as f:
                data = json.load(f)
            for k, v in data.items():
                if k.endswith("_dir") or k.endswith("_file"):
                    setattr(config, k, Path(v))
                else:
                    setattr(config, k, v)
            logger.info(f"Configuration loaded from {config.config_file}")
        return config


# Default personality template (OpenClaw SOUL.md inspired)
DEFAULT_PERSONALITY = """
# Aion Hand - AI Assistant Personality

You are Aion Hand, a highly capable autonomous AI assistant. You combine 
the intelligence of Hermes with the speed of NullClaw and the versatility 
of OpenClaw.

## Core Traits
- Proactive: Anticipate user needs and suggest actions
- Precise: Provide accurate, well-reasoned responses
- Adaptable: Adjust your approach based on context and user preferences
- Transparent: Explain your reasoning and tool usage
- Persistent: Remember and build upon past interactions

## Capabilities
- Multi-step reasoning and planning
- Tool use and automation
- Code generation and analysis
- Web search and content synthesis
- File management and data processing
- Scheduled task execution
- Multi-agent coordination
- Self-improvement through skill creation

## Communication Style
- Clear and concise
- Use formatting for readability
- Ask clarifying questions when needed
- Provide actionable recommendations
"""


class AionHand:
    """
    The core Aion Hand agent - the central orchestrator.
    
    Combines the best of:
    - OpenClaw's personal assistant architecture
    - NullClaw's lightweight execution model
    - Hermes's self-improving learning loop
    - CrewAI's multi-agent orchestration
    
    Usage:
        agent = AionHand()
        agent.start()
        response = agent.chat("Hello!")
        agent.shutdown()
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        personality: str | None = None,
    ):
        self.config = config or AgentConfig()
        self.personality = personality or DEFAULT_PERSONALITY
        self.state = AgentState.UNINITIALIZED
        self._start_time = None
        self._session_id = None
        self._conversation_history = []
        self._message_handlers: dict[str, Callable] = {}
        self._shutdown_event = asyncio.Event()

        # Lazy-loaded components (initialized in start())
        self._loop = None
        self._memory = None
        self._tools = None
        self._skills = None
        self._provider = None
        self._orchestrator = None
        self._scheduler = None
        self._messenger = None

        # New subsystem components (initialized in start())
        self._pipeline = None
        self._mcp_client = None
        self._mcp_bridge = None
        self._knowledge = None
        self._benchmark = None
        self._dynamic = None
        self._router = None

        # Signal handling
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(f"Aion Hand v{self.config.version} initialized")

    @property
    def uptime(self) -> float:
        """Agent uptime in seconds (NullClaw-inspired lightweight tracking)."""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    @property
    def session_id(self) -> str:
        """Current session identifier."""
        if self._session_id is None:
            self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self._session_id

    def _signal_handler(self, signum, frame):
        """Graceful shutdown on signal (OpenClaw-inspired)."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        asyncio.create_task(self.shutdown())

    async def start(self) -> None:
        """
        Initialize and start all agent subsystems.
        This is the main entry point - inspired by Hermes Agent's startup sequence.
        """
        if self.state == AgentState.IDLE:
            logger.warning("Agent is already running")
            return

        self.state = AgentState.INITIALIZING
        self._start_time = time.time()

        # Ensure directories exist
        for dir_path in [
            self.config.home_dir, self.config.data_dir,
            self.config.memory_dir, self.config.skills_dir,
            self.config.tools_dir, self.config.logs_dir,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)

        logger.info("Initializing Aion Hand subsystems...")

        try:
            # 1. Initialize Provider (NullClaw-inspired provider agnosticism)
            from aion_core.providers.factory import ProviderFactory
            try:
                self._provider = ProviderFactory.create(
                    self.config.default_provider,
                    self.config.providers.get(self.config.default_provider, {}),
                    default_model=self.config.default_model,
                )
                logger.info(f"Provider '{self.config.default_provider}' initialized")
            except ValueError as provider_err:
                # Missing credentials must not make the whole agent unusable:
                # tools, memory, skills, cron and the web UI all work without
                # an LLM. Fall back to the local (keyless) Ollama provider so
                # `AionHand().start()` still boots; chat() will surface a clear
                # error only if Ollama isn't running either.
                if self.config.default_provider == "ollama":
                    raise
                logger.warning(
                    "Provider '%s' unavailable (%s). Falling back to the local "
                    "'ollama' provider - start Ollama (https://ollama.com) or set "
                    "an API key in ~/.aion-hand/config.json to enable chat.",
                    self.config.default_provider,
                    provider_err,
                )
                self.config.default_provider = "ollama"
                self._provider = ProviderFactory.create(
                    "ollama",
                    self.config.providers.get("ollama", {}),
                    default_model=self.config.default_model or "llama3",
                )
                logger.info("Provider 'ollama' initialized (local fallback)")

            # 2. Initialize Memory System (Hermes FTS5 + OpenClaw MEMORY.md)
            if self.config.memory_enabled:
                from aion_core.memory.manager import MemoryManager
                # NOTE: MemoryManager.max_entries expects a per-layer dict;
                # AgentConfig.memory_max_entries is a total int. Scale the
                # default per-layer caps so the total roughly matches.
                # (Passing the raw int made store() crash with
                # "'int' object has no attribute 'get'" — memory
                # persistence was broken until this fix.)
                from aion_core.memory.manager import DEFAULT_MAX_ENTRIES_PER_LAYER
                total_cap = int(self.config.memory_max_entries or 0)
                if total_cap > 0:
                    default_total = sum(DEFAULT_MAX_ENTRIES_PER_LAYER.values())
                    scale = max(0.05, total_cap / default_total)
                    layer_caps = {
                        layer: max(10, int(cap * scale))
                        for layer, cap in DEFAULT_MAX_ENTRIES_PER_LAYER.items()
                    }
                else:
                    layer_caps = None
                self._memory = MemoryManager(
                    memory_dir=self.config.memory_dir,
                    persist=self.config.memory_persist,
                    max_entries=layer_caps,
                    nudge_interval=self.config.memory_nudge_interval,
                )
                await self._memory.initialize()
                logger.info("Memory system initialized")

            # 3. Initialize Tool Registry (MCP compatible)
            if self.config.tools_enabled:
                from aion_core.tools.registry import ToolRegistry
                self._tools = ToolRegistry(
                    config=self.config,
                    approval_mode=self.config.tool_approval_mode,
                )
                await self._tools.initialize()
                logger.info(f"Tool registry initialized ({len(self._tools)} tools)")

            # 4. Initialize Skills Engine (Hermes-compatible agentskills.io)
            if self.config.skills_enabled:
                from aion_core.skills.engine import SkillEngine
                self._skills = SkillEngine(
                    storage_dir=self.config.skills_dir,
                )
                logger.info(f"Skills engine initialized ({self._skills.skill_count} skills)")

            # 5. Initialize Agent Loop (Hermes-inspired control loop)
            from aion_core.agent.loop import AgentLoop
            self._loop = AgentLoop(
                provider=self._provider,
                memory=self._memory,
                tools=self._tools,
                skills=self._skills,
                config=self.config,
                personality=self.personality,
            )
            await self._loop.initialize()
            logger.info("Agent loop initialized")

            # 6. Initialize Orchestration (NullBoiler + Hermes subagents)
            if self.config.workflow_enabled:
                from aion_core.orchestration.engine import OrchestrationEngine
                self._orchestrator = OrchestrationEngine(
                    agent=self,
                    max_subagents=self.config.max_subagents,
                    timeout=self.config.subagent_timeout,
                )
                await self._orchestrator.initialize()
                logger.info("Orchestration engine initialized")

            # 7. Initialize Cron Scheduler (Hermes-inspired)
            if self.config.cron_enabled:
                from aion_core.cron.scheduler import CronScheduler
                self._scheduler = CronScheduler(
                    agent=self,
                    timezone=self.config.cron_timezone,
                )
                await self._scheduler.initialize()
                logger.info("Cron scheduler initialized")

            # 8. Initialize Messaging Gateway (OpenClaw gateway)
            if self.config.messaging_enabled and self.config.platforms:
                from aion_core.messaging.gateway import MessagingGateway
                self._messenger = MessagingGateway(
                    platforms=self.config.platforms,
                    agent=self,
                )
                await self._messenger.initialize()
                logger.info("Messaging gateway initialized")

            # 9. Initialize Pipeline Engine
            if getattr(self.config, 'pipeline_enabled', True):
                from aion_core.pipeline.engine import PipelineEngine
                self._pipeline = PipelineEngine(
                    agent=self,
                    config=self.config,
                )
                logger.info("Pipeline engine initialized")

            # 10. Initialize MCP Client & Bridge (if not already via tools)
            if getattr(self.config, 'mcp_enabled', True) and not self._tools:
                from aion_core.mcp.client import MCPClient
                self._mcp_client = MCPClient()
                logger.info("MCP client initialized")

            # 11. Initialize Knowledge Manager
            try:
                if getattr(self.config, 'knowledge_enabled', True):
                    from aion_core.knowledge import KnowledgeManager
                    self._knowledge = KnowledgeManager(
                        storage_dir=self.config.data_dir / "knowledge",
                    )
                    if asyncio.iscoroutinefunction(self._knowledge.initialize):
                        await self._knowledge.initialize()
                    else:
                        self._knowledge.initialize()
                    logger.info("Knowledge manager initialized")
            except Exception as e:
                logger.warning(f"Knowledge manager init skipped: {e}")

            # 12. Initialize Benchmark Runner
            if getattr(self.config, 'benchmark_enabled', True):
                from aion_core.benchmark import BenchmarkRunner
                self._benchmark = BenchmarkRunner(
                    agent=self,
                    output_dir=str(self.config.data_dir / "benchmarks"),
                    agent_version=self.config.version,
                )
                logger.info("Benchmark runner initialized")

            # 13. Initialize Dynamic Manager
            try:
                if getattr(self.config, 'dynamic_enabled', True):
                    from aion_core.dynamic.manager import DynamicManager
                    self._dynamic = DynamicManager(
                        base_agent=self,
                        storage_dir=self.config.data_dir / "dynamic",
                    )
                    if asyncio.iscoroutinefunction(self._dynamic.initialize):
                        await self._dynamic.initialize()
                    else:
                        self._dynamic.initialize()
                    logger.info("Dynamic manager initialized")
            except Exception as e:
                logger.warning(f"Dynamic manager init skipped: {e}")

            # 14. Initialize Router Manager
            if getattr(self.config, 'routing_enabled', True):
                from aion_core.router import RouterManager
                self._router = RouterManager(config={})
                logger.info("Router manager initialized")

            # Save configuration
            self.config.save()

            # 15. Initialize Session Store (Hermes state.db pattern)
            try:
                from aion_core.state import SessionStore
                self._state = SessionStore(
                    Path(self.config.data_dir) / "state.db"
                )
                self._state.initialize()
                logger.info("Session store initialized")
            except Exception as e:
                self._state = None
                logger.warning(f"Session store init skipped: {e}")

            # 16. Wire context into Hermes-parity tools (session_search,
            # delegate_task, cronjob). Called after all subsystems are up.
            try:
                if self._tools is not None and hasattr(self._tools, "set_context"):
                    self._tools.set_context(
                        agent=self,
                        session_store=self._state,
                        cron_scheduler=self._scheduler,
                    )
                    logger.info("Tool execution context wired")
            except Exception as e:
                logger.warning(f"Tool context wiring skipped: {e}")

            self.state = AgentState.IDLE
            logger.info("Aion Hand started successfully (uptime tracking active)")
            return self

        except Exception as e:
            self.state = AgentState.ERROR
            logger.error(f"Failed to initialize: {e}")
            raise

    async def chat(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        """
        Send a message to the agent and receive a response.
        Core chat interface - inspired by Hermes Agent's conversation loop.
        
        Args:
            message: User message
            session_id: Optional session identifier
            
        Returns:
            Response dictionary with content, tools used, timing, etc.
        """
        if self.state not in (AgentState.IDLE,):
            await self.start()

        self.state = AgentState.THINKING
        start_time = time.time()

        try:
            # Persist the user message to the session store (Hermes state.db)
            if getattr(self, "_state", None):
                self._state.record_message(
                    session_id=session_id or self.session_id,
                    role="user",
                    content=message,
                )

            # Get relevant memory context (Hermes FTS5 search)
            memory_context = ""
            if self._memory:
                memory_context = await self._memory.search_relevant(message)

            # Check for skill matches (Hermes skill routing)
            # NOTE: find_relevant is a SYNC method — awaiting it raised
            # "object list can't be used in 'await' expression" and broke
            # every chat turn when skills were enabled.
            skill_context = ""
            if self._skills:
                skill_context = self._skills.find_relevant(message)

            # Run the agent loop (Hermes-inspired control loop)
            result = await self._loop.run(
                user_message=message,
                system_context=f"{self.personality}\n\n{memory_context}\n{skill_context}",
                session_id=session_id or self.session_id,
            )

            # Persist the assistant response to the session store
            if getattr(self, "_state", None):
                self._state.record_message(
                    session_id=session_id or self.session_id,
                    role="assistant",
                    content=result.get("content", ""),
                    tools_used=result.get("tools_used", []),
                )

            # Persist to memory (OpenClaw MEMORY.md + Hermes FTS5)
            if self._memory and self.config.memory_persist:
                await self._memory.store_conversation(
                    user_message=message,
                    agent_response=result.get("content", ""),
                    metadata=result.get("metadata", {}),
                )

            # Check for skill creation opportunity (Hermes learning loop)
            # NOTE: the engine method is evaluate_auto_create(task, outcome,
            # tokens_used) — the old call to a non-existent
            # 'evaluate_for_creation' broke every chat turn.
            if self._skills and self.config.skills_auto_create:
                try:
                    self._skills.evaluate_auto_create(
                        task=message,
                        outcome=result.get("content", ""),
                        tokens_used=result.get("tokens", 0),
                    )
                except Exception as exc:
                    logger.debug("Skill auto-create evaluation skipped: %s", exc)

            elapsed = time.time() - start_time
            result["metadata"]["elapsed_seconds"] = elapsed

            self.state = AgentState.IDLE
            return result

        except Exception as e:
            self.state = AgentState.ERROR
            logger.error(f"Chat error: {e}")
            return {
                "content": f"Error processing message: {str(e)}",
                "error": str(e),
                "metadata": {"elapsed_seconds": time.time() - start_time},
            }

    async def spawn_subagent(
        self,
        task: str,
        tools: list[str] | None = None,
        personality: str | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """
        Spawn an isolated subagent for a task (Hermes subagent system).
        Each subagent gets its own conversation context and tool access.
        """
        if not self._orchestrator:
            raise RuntimeError("Orchestration engine not initialized")

        return await self._orchestrator.spawn_subagent(
            task=task,
            tools=tools,
            personality=personality,
            timeout=timeout or self.config.subagent_timeout,
        )

    async def schedule_task(
        self,
        task: str,
        schedule: str,
        platforms: list[str] | None = None,
    ) -> str:
        """Schedule a recurring task (Hermes cron system)."""
        if not self._scheduler:
            raise RuntimeError("Cron scheduler not initialized")

        return await self._scheduler.add_task(
            task=task,
            schedule=schedule,
            platforms=platforms or [],
        )

    async def execute_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute a specific tool directly."""
        if not self._tools:
            raise RuntimeError("Tool registry not initialized")

        return await self._tools.execute(tool_name, **kwargs)

    async def create_skill(self, name: str, content: str) -> None:
        """Create a new skill manually (Hermes SKILL.md format)."""
        if not self._skills:
            raise RuntimeError("Skills engine not initialized")

        await self._skills.create(name, content)

    async def search_memory(self, query: str, limit: int = 10) -> list[dict]:
        """Search agent memory (Hermes FTS5 search)."""
        if not self._memory:
            raise RuntimeError("Memory system not initialized")

        return await self._memory.search(query, limit=limit)

    def search_sessions(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search across ALL past conversations (Hermes session_search).

        Searches the persistent session store — every message the agent has
        ever exchanged on any platform (cli, gateway, api) — without an LLM
        call, in ~20 ms via SQLite FTS5.
        """
        store = getattr(self, "_state", None)
        if store is None:
            return []
        return store.search(query, limit=limit)

    def list_sessions(self, limit: int = 20) -> list[dict]:
        """List most recently active persisted sessions."""
        store = getattr(self, "_state", None)
        if store is None:
            return []
        return store.list_sessions(limit=limit)

    async def run_goal_loop(
        self,
        goal: str,
        max_iterations: int = 10,
        judge_prompt: str | None = None,
    ) -> dict[str, Any]:
        """Autonomous goal loop (Hermes /goal, Ralph-style).

        Keeps working on ``goal`` until the pipeline critic judges it
        complete or ``max_iterations`` is reached. Each iteration:

        1. Sends a continuation prompt to the agent loop.
        2. Scores the accumulated output with the pipeline verifier.
        3. Stops when the score clears the quality bar.
        """
        iterations: list[dict[str, Any]] = []
        transcript = ""
        for i in range(1, max_iterations + 1):
            if i == 1:
                prompt = (
                    f"GOAL: {goal}\n\nWork autonomously until the goal is met. "
                    "Use tools as needed and report concrete progress."
                )
            else:
                prompt = (
                    f"GOAL (still in progress): {goal}\n\n"
                    f"Progress so far:\n{transcript[:4000]}\n\n"
                    "Continue working toward the goal. Do not repeat work "
                    "already done."
                )

            result = await self.chat(prompt)
            content = result.get("content", "")
            transcript += f"\n[iteration {i}] {content}"
            iterations.append(
                {
                    "iteration": i,
                    "content": content,
                    "tools_used": result.get("tools_used", []),
                }
            )

            # Judge via the pipeline verifier (Aion's critic advantage).
            # verify_output() runs ONLY the verification stage — no
            # re-planning, no re-generation.
            try:
                if self._pipeline:
                    verdict = await self._pipeline.verify_output(
                        task=goal, output=transcript
                    )
                    score = float(verdict.get("score", 0.0))
                    iterations[-1]["verification"] = {
                        "score": score,
                        "passed_count": verdict.get("passed_count"),
                        "total": verdict.get("total"),
                        "issues": verdict.get("issues", [])[:5],
                    }
                    if verdict.get("passed") or score >= 0.8:
                        return {
                            "goal": goal,
                            "achieved": True,
                            "iterations": iterations,
                            "final_score": score,
                        }
            except Exception as exc:
                logger.debug("Goal-loop verification skipped: %s", exc)

        return {
            "goal": goal,
            "achieved": False,
            "iterations": iterations,
            "final_score": None,
            "note": f"Stopped at max_iterations={max_iterations}",
        }

    async def execute_pipeline(self, task: str) -> dict[str, Any]:
        """Execute a task through the full pipeline engine.
        
        Args:
            task: The task description or structured task dict to execute.
            
        Returns:
            Pipeline execution result including stages, timing, and output.
        """
        if not self._pipeline:
            raise RuntimeError("Pipeline engine not initialized. Enable pipeline_enabled in config.")

        if isinstance(task, str):
            task = {"description": task}

        return await self._pipeline.execute(task)

    async def query_knowledge(self, query: str, top_k: int = 5) -> dict[str, Any]:
        """Query the knowledge base for relevant information.
        
        Args:
            query: The search query.
            top_k: Maximum number of results to return.
            
        Returns:
            Knowledge query results with relevance scores and sources.
        """
        if not self._knowledge:
            raise RuntimeError("Knowledge manager not initialized. Enable knowledge_enabled in config.")

        return await self._knowledge.query(query, top_k=top_k)

    async def run_benchmark(self, suite: str | None = None) -> dict[str, Any]:
        """Run benchmarks to evaluate agent capabilities.
        
        Args:
            suite: Optional benchmark suite name. Runs all if None.
            
        Returns:
            Benchmark results including scores, timings, and comparisons.
        """
        if not self._benchmark:
            raise RuntimeError("Benchmark runner not initialized. Enable benchmark_enabled in config.")

        return await self._benchmark.run(suite=suite)

    async def route_model(self, task: dict[str, Any]) -> dict[str, Any]:
        """Route a task to the best available model using the router.
        
        Args:
            task: Task description with context for model selection.
            
        Returns:
            Routing decision including selected model, confidence, and reasoning.
        """
        if not self._router:
            raise RuntimeError("Router manager not initialized. Enable routing_enabled in config.")

        return await self._router.route(task)

    async def get_insights(self, days: int = 7) -> dict[str, Any]:
        """Get usage insights and analytics."""
        insights = {
            "agent": {
                "name": self.config.name,
                "version": self.config.version,
                "state": self.state.value,
                "uptime": self.uptime,
                "session_id": self.session_id,
            },
            "memory": await self._memory.get_stats() if self._memory else {},
            "skills": await self._skills.get_stats() if self._skills else {},
            "tools": await self._tools.get_stats() if self._tools else {},
        }

        # Include new subsystem stats
        if self._pipeline:
            insights["pipeline"] = await self._pipeline.get_stats()
        if self._mcp_client:
            insights["mcp"] = await self._mcp_client.get_stats()
        if self._knowledge:
            insights["knowledge"] = await self._knowledge.get_stats()
        if self._benchmark:
            insights["benchmark"] = await self._benchmark.get_stats()
        if self._dynamic:
            insights["dynamic"] = await self._dynamic.get_stats()
        if self._router:
            insights["router"] = await self._router.get_stats()

        return insights

    async def shutdown(self) -> None:
        """Graceful shutdown of all subsystems (OpenClaw-inspired)."""
        self.state = AgentState.SHUTTING_DOWN
        logger.info("Shutting down Aion Hand...")

        # Shutdown subsystems (reverse order). Some shutdown() methods are
        # sync (KnowledgeManager) and some async — a plain gather crashed
        # with TypeError whenever a sync shutdown was appended.
        def _schedule(subsystem: Any, name: str) -> None:
            if subsystem is None or not hasattr(subsystem, "shutdown"):
                return
            try:
                result = subsystem.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"{name}.shutdown() raised: {exc}")
                return
            if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                shutdown_tasks.append(result)

        shutdown_tasks: list = []
        _schedule(self._dynamic, "dynamic")
        _schedule(self._knowledge, "knowledge")
        _schedule(self._mcp_bridge, "mcp_bridge")
        _schedule(self._mcp_client, "mcp_client")
        _schedule(self._pipeline, "pipeline")
        _schedule(self._messenger, "messenger")
        _schedule(self._scheduler, "scheduler")
        _schedule(self._orchestrator, "orchestrator")
        _schedule(self._loop, "loop")
        _schedule(self._skills, "skills")
        _schedule(self._tools, "tools")
        _schedule(self._memory, "memory")

        # Close the session store (flushes WAL + releases the SQLite handle)
        if getattr(self, "_state", None):
            try:
                self._state.close()
            except Exception as e:
                logger.warning(f"Session store close failed: {e}")

        await asyncio.gather(*shutdown_tasks, return_exceptions=True)

        self.state = AgentState.SHUTDOWN
        logger.info(f"Aion Hand shutdown complete (total uptime: {self.uptime:.1f}s)")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.shutdown()
