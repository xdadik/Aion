"""
aion_core.cron — Hermes Agent-inspired cron scheduler for automated tasks.

Provides a lightweight, asyncio-native scheduler that parses standard 5-field
cron expressions and executes recurring agent tasks on a per-minute loop.

Quick start::

    from aion_core.cron import CronScheduler, ScheduledTask

    scheduler = CronScheduler(agent, timezone="UTC")
    await scheduler.initialize()

    task_id = await scheduler.add_task(
        task="Summarize the day's news",
        schedule="0 9 * * *",         # daily at 9:00 AM
        platforms=["telegram", "discord"],
    )

    tasks = await scheduler.list_tasks()
    await scheduler.shutdown()
"""

from .scheduler import CronScheduler, ScheduledTask

__all__ = [
    "CronScheduler",
    "ScheduledTask",
]
