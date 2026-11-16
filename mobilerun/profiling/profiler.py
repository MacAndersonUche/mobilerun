"""Performance profiler for agent loop operations."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("mobilerun.profiling")


class ProfileCategory(str, Enum):
    """Categories of operations to profile."""

    SCREENSHOT = "screenshot"
    UI_TREE = "ui_tree"
    LLM_CALL = "llm_call"
    ACTION_EXECUTION = "action_execution"
    ADB_COMMAND = "adb_command"
    STATE_FETCH = "state_fetch"
    TOOL_CALL = "tool_call"
    TOTAL_STEP = "total_step"


@dataclass
class ProfileMetrics:
    """Metrics for a single profiled operation."""

    category: ProfileCategory
    duration_ms: float
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None


@dataclass
class ProfileReport:
    """Aggregated profiling report."""

    metrics: list[ProfileMetrics]
    total_duration_ms: float
    start_time: float
    end_time: float

    def get_category_stats(self, category: ProfileCategory) -> dict[str, float]:
        """Get aggregated statistics for a specific category."""
        category_metrics = [m for m in self.metrics if m.category == category]
        if not category_metrics:
            return {
                "count": 0,
                "total_ms": 0.0,
                "avg_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
            }

        durations = [m.duration_ms for m in category_metrics]
        return {
            "count": len(durations),
            "total_ms": sum(durations),
            "avg_ms": sum(durations) / len(durations),
            "min_ms": min(durations),
            "max_ms": max(durations),
        }

    def format_summary(self) -> str:
        """Format a human-readable summary of the profiling report."""
        lines = [
            "Performance Profile Summary",
            "=" * 60,
            f"Total Duration: {self.total_duration_ms:.2f} ms",
            f"Operations: {len(self.metrics)}",
            "",
            "By Category:",
            "-" * 60,
        ]

        for category in ProfileCategory:
            stats = self.get_category_stats(category)
            if stats["count"] > 0:
                lines.append(
                    f"  {category.value:20s}: "
                    f"{stats['count']:3d} calls, "
                    f"avg {stats['avg_ms']:7.2f} ms, "
                    f"total {stats['total_ms']:8.2f} ms"
                )

        return "\n".join(lines)


class ProfilerContext:
    """Context for a single profiled operation."""

    def __init__(
        self,
        profiler: "AgentProfiler",
        category: ProfileCategory,
        metadata: Optional[dict[str, Any]] = None,
    ):
        self.profiler = profiler
        self.category = category
        self.metadata = metadata or {}
        self.start_time: Optional[float] = None
        self.metric: Optional[ProfileMetrics] = None

    async def __aenter__(self):
        self.start_time = time.perf_counter()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is None:
            return

        duration_ms = (time.perf_counter() - self.start_time) * 1000
        self.metric = ProfileMetrics(
            category=self.category,
            duration_ms=duration_ms,
            timestamp=self.start_time,
            metadata=self.metadata,
            success=exc_type is None,
            error=str(exc_val) if exc_val else None,
        )
        self.profiler.record(self.metric)


class AgentProfiler:
    """Performance profiler for agent operations."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.metrics: list[ProfileMetrics] = []
        self.start_time: Optional[float] = None
        self._lock = asyncio.Lock()

    def start(self):
        """Start profiling session."""
        self.start_time = time.perf_counter()
        self.metrics.clear()

    def stop(self) -> ProfileReport:
        """Stop profiling and return report."""
        if self.start_time is None:
            raise ValueError("Profiler not started")

        end_time = time.perf_counter()
        total_duration_ms = (end_time - self.start_time) * 1000

        return ProfileReport(
            metrics=self.metrics.copy(),
            total_duration_ms=total_duration_ms,
            start_time=self.start_time,
            end_time=end_time,
        )

    def record(self, metric: ProfileMetrics):
        """Record a metric."""
        if not self.enabled:
            return
        self.metrics.append(metric)

    @asynccontextmanager
    async def profile(
        self, category: ProfileCategory, metadata: Optional[dict[str, Any]] = None
    ):
        """Context manager for profiling an operation."""
        if not self.enabled:
            yield None
            return

        ctx = ProfilerContext(self, category, metadata)
        async with ctx:
            yield ctx

    def profile_sync(
        self, category: ProfileCategory, metadata: Optional[dict[str, Any]] = None
    ):
        """Synchronous context manager for profiling."""
        return _SyncProfilerContext(self, category, metadata)


class _SyncProfilerContext:
    """Synchronous version of ProfilerContext."""

    def __init__(
        self,
        profiler: AgentProfiler,
        category: ProfileCategory,
        metadata: Optional[dict[str, Any]] = None,
    ):
        self.profiler = profiler
        self.category = category
        self.metadata = metadata or {}
        self.start_time: Optional[float] = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is None:
            return

        duration_ms = (time.perf_counter() - self.start_time) * 1000
        metric = ProfileMetrics(
            category=self.category,
            duration_ms=duration_ms,
            timestamp=self.start_time,
            metadata=self.metadata,
            success=exc_type is None,
            error=str(exc_val) if exc_val else None,
        )
        self.profiler.record(metric)
