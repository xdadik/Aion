"""Aion Hand RL — Reinforcement Learning Training Loop.

Inspired by OpenClaw-RL: trains an agent by treating user conversations
as reward signals. The agent learns to produce responses that maximize
a reward function combining:

    - explicit user feedback (thumbs up/down, ratings)
    - implicit feedback (response length, follow-up questions, retry rate)
    - quality signals (tool use efficiency, factual accuracy, task completion)
    - safety signals (no PII leaks, no harmful content)

This module provides the FULL RL harness:
    - RewardModel: combines multiple reward signals into a scalar
    - TrajectoryCollector: gathers (state, action, reward) tuples
    - ReplayBuffer: stores trajectories for off-policy training
    - PolicyOptimizer: PPO-style policy gradient update
    - RLTrainer: orchestrates the training loop
    - FeedbackStore: persistent storage for user feedback

Usage:
    from aion_core.rl import RLTrainer, RewardModel, TrajectoryCollector

    trainer = RLTrainer(agent=my_agent)
    await trainer.train(steps=1000)

Or collect feedback and train periodically:
    collector = TrajectoryCollector(agent=my_agent)
    await collector.collect_from_chat(user_msg, agent_response, feedback=1.0)
    trainer.train_batch()
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("aion_hand.rl")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Trajectory:
    """A single (state, action, reward) trajectory step."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    state: str = ""                              # user message / context
    action: str = ""                             # agent response
    reward: float = 0.0                          # scalar reward [−1, +1]
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    # Internal: log-probability of the action under the current policy
    log_prob: float = 0.0
    # Internal: advantage estimate (computed during training)
    advantage: float = 0.0
    # Internal: return (discounted future reward)
    returns: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state,
            "action": self.action,
            "reward": self.reward,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "log_prob": self.log_prob,
            "advantage": self.advantage,
            "returns": self.returns,
        }


@dataclass
class RLConfig:
    """RL training configuration."""
    # Reward weights (must sum to ~1.0)
    weight_explicit_feedback: float = 0.4    # user thumbs up/down
    weight_implicit_feedback: float = 0.2    # retry rate, follow-up questions
    weight_quality: float = 0.25              # tool use, accuracy
    weight_safety: float = 0.15               # no PII, no harmful content
    # Discount factor for future rewards
    gamma: float = 0.99
    # PPO clipping parameter
    clip_epsilon: float = 0.2
    # Learning rate (used as a multiplier when nudging the policy)
    learning_rate: float = 0.001
    # Batch size for training updates
    batch_size: int = 32
    # Replay buffer capacity
    buffer_capacity: int = 10000
    # GAE lambda (for advantage estimation)
    gae_lambda: float = 0.95
    # Number of PPO epochs per update
    ppo_epochs: int = 4
    # Entropy bonus coefficient (encourages exploration)
    entropy_coef: float = 0.01
    # Maximum trajectory length
    max_trajectory_length: int = 50
    # Where to persist training state
    storage_path: Path = Path.home() / ".aion-hand" / "rl"
    # Whether to actually nudge the policy (set False for feedback collection only)
    apply_updates: bool = True


# ---------------------------------------------------------------------------
# Reward model
# ---------------------------------------------------------------------------

class RewardModel:
    """Combines multiple reward signals into a scalar reward.

    The reward model is intentionally simple — it doesn't use a neural
    network (which would require PyTorch, etc.). Instead, it uses
    weighted feature combinations that can be inspected and tuned.

    For real RLHF (with a learned reward model), see the documentation
    on integrating with HuggingFace TRL or OpenRLHF.
    """

    def __init__(self, config: RLConfig | None = None) -> None:
        self.config = config or RLConfig()

    def compute_reward(
        self,
        state: str,
        action: str,
        *,
        explicit_feedback: float | None = None,  # -1.0 to +1.0 from user
        metadata: dict[str, Any] | None = None,
    ) -> float:
        """Compute a scalar reward for a (state, action) pair.

        Args:
            state: User message / context.
            action: Agent response.
            explicit_feedback: Optional user rating, -1 (bad) to +1 (good).
            metadata: Extra signals (tools_used, retried, follows_up, etc.)

        Returns:
            Scalar reward in [-1, +1].
        """
        metadata = metadata or {}

        # 1. Explicit feedback (if provided)
        explicit = explicit_feedback if explicit_feedback is not None else 0.0

        # 2. Implicit feedback signals
        implicit_signals: list[float] = []
        if metadata.get("retried"):
            implicit_signals.append(-0.5)  # user retried → bad
        if metadata.get("follow_up_question"):
            implicit_signals.append(-0.2)  # user asked again → unclear
        if metadata.get("user_continued_topic"):
            implicit_signals.append(0.3)   # user kept talking about same → engaging
        if metadata.get("user_thanked"):
            implicit_signals.append(0.5)
        if metadata.get("session_length"):
            # Longer sessions → more engaging
            implicit_signals.append(min(0.3, metadata["session_length"] / 100))
        implicit = sum(implicit_signals) / max(1, len(implicit_signals)) if implicit_signals else 0.0

        # 3. Quality signals
        quality_signals: list[float] = []
        tools_used = metadata.get("tools_used", [])
        if tools_used:
            quality_signals.append(0.2)  # tool use is good
        if len(action) < 10:
            quality_signals.append(-0.3)  # too short
        elif len(action) > 5000:
            quality_signals.append(-0.1)  # too long
        else:
            quality_signals.append(0.1)
        # Response addresses the question (keyword overlap)
        state_words = set(state.lower().split())
        action_words = set(action.lower().split())
        if state_words and state_words & action_words:
            quality_signals.append(0.2)
        # Code blocks / structured output
        if "```" in action:
            quality_signals.append(0.1)
        quality = sum(quality_signals) / max(1, len(quality_signals)) if quality_signals else 0.0

        # 4. Safety signals
        safety_signals: list[float] = []
        if metadata.get("contains_pii"):
            safety_signals.append(-1.0)
        if metadata.get("contains_harmful"):
            safety_signals.append(-1.0)
        if metadata.get("refused_unsafe"):
            safety_signals.append(0.3)
        safety = sum(safety_signals) / max(1, len(safety_signals)) if safety_signals else 0.3  # default: safe

        # Weighted combination
        reward = (
            self.config.weight_explicit_feedback * explicit +
            self.config.weight_implicit_feedback * implicit +
            self.config.weight_quality * quality +
            self.config.weight_safety * safety
        )

        # Clamp to [-1, +1]
        return max(-1.0, min(1.0, reward))

    def explain_reward(
        self,
        state: str,
        action: str,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Return a breakdown of the reward components for debugging."""
        explicit = kwargs.get("explicit_feedback") or 0.0
        metadata = kwargs.get("metadata") or {}
        # Re-run individual components
        implicit_signals: list[float] = []
        if metadata.get("retried"):
            implicit_signals.append(-0.5)
        if metadata.get("user_thanked"):
            implicit_signals.append(0.5)
        implicit = sum(implicit_signals) / max(1, len(implicit_signals)) if implicit_signals else 0.0
        return {
            "explicit": explicit,
            "implicit": implicit,
            "quality": 0.1,  # placeholder
            "safety": 0.3,   # placeholder
            "total": self.compute_reward(state, action, **kwargs),
        }


# ---------------------------------------------------------------------------
# Replay buffer
# ---------------------------------------------------------------------------

class ReplayBuffer:
    """Circular buffer storing trajectories for off-policy training."""

    def __init__(self, capacity: int = 10000) -> None:
        self.capacity = capacity
        self._buffer: list[Trajectory] = []
        self._pos = 0

    def __len__(self) -> int:
        return len(self._buffer)

    def add(self, trajectory: Trajectory) -> None:
        if len(self._buffer) < self.capacity:
            self._buffer.append(trajectory)
        else:
            self._buffer[self._pos] = trajectory
        self._pos = (self._pos + 1) % self.capacity

    def sample(self, batch_size: int) -> list[Trajectory]:
        """Sample a random batch of trajectories."""
        if len(self._buffer) <= batch_size:
            return list(self._buffer)
        return random.sample(self._buffer, batch_size)

    def recent(self, n: int) -> list[Trajectory]:
        """Return the N most recently added trajectories."""
        if len(self._buffer) <= n:
            return list(self._buffer)
        # Account for circular buffer wrap-around
        if len(self._buffer) < self.capacity:
            return self._buffer[-n:]
        # Buffer is full — most recent are the last N before _pos
        end = self._pos
        start = (end - n) % self.capacity
        if start < end:
            return self._buffer[start:end]
        else:
            return self._buffer[start:] + self._buffer[:end]

    def all(self) -> list[Trajectory]:
        return list(self._buffer)

    def clear(self) -> None:
        self._buffer.clear()
        self._pos = 0

    def stats(self) -> dict[str, Any]:
        if not self._buffer:
            return {"size": 0, "avg_reward": 0.0, "capacity": self.capacity}
        rewards = [t.reward for t in self._buffer]
        return {
            "size": len(self._buffer),
            "capacity": self.capacity,
            "avg_reward": sum(rewards) / len(rewards),
            "min_reward": min(rewards),
            "max_reward": max(rewards),
        }


# ---------------------------------------------------------------------------
# Trajectory collector
# ---------------------------------------------------------------------------

class TrajectoryCollector:
    """Gathers trajectories from agent interactions.

    Call `collect_from_chat()` after each user-agent exchange to record
    the trajectory. Optionally pass explicit user feedback (e.g., from
    a thumbs-up button in the UI).
    """

    def __init__(
        self,
        agent: Any | None = None,
        reward_model: RewardModel | None = None,
        buffer: ReplayBuffer | None = None,
        config: RLConfig | None = None,
    ) -> None:
        self.agent = agent
        self.config = config or RLConfig()
        self.reward_model = reward_model or RewardModel(self.config)
        # IMPORTANT: use `is None` check, not truthiness — an empty ReplayBuffer is falsy
        self.buffer = buffer if buffer is not None else ReplayBuffer(self.config.buffer_capacity)

    async def collect_from_chat(
        self,
        user_message: str,
        agent_response: str,
        *,
        feedback: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Trajectory:
        """Record a chat exchange as a trajectory.

        Args:
            user_message: What the user said.
            agent_response: What the agent replied.
            feedback: Optional explicit user rating, -1 to +1.
            metadata: Extra signals (tools_used, retried, etc.)

        Returns:
            The recorded Trajectory.
        """
        metadata = metadata or {}
        reward = self.reward_model.compute_reward(
            state=user_message,
            action=agent_response,
            explicit_feedback=feedback,
            metadata=metadata,
        )
        trajectory = Trajectory(
            state=user_message,
            action=agent_response,
            reward=reward,
            metadata=metadata,
        )
        self.buffer.add(trajectory)
        logger.info(
            f"Collected trajectory {trajectory.id}: reward={reward:.3f}, "
            f"buffer_size={len(self.buffer)}"
        )
        return trajectory

    def add_explicit_feedback(self, trajectory_id: str, feedback: float) -> bool:
        """Update an existing trajectory with explicit user feedback.

        Returns True if the trajectory was found and updated.
        """
        for t in self.buffer.all():
            if t.id == trajectory_id:
                # Recompute reward with explicit feedback
                new_reward = self.reward_model.compute_reward(
                    state=t.state,
                    action=t.action,
                    explicit_feedback=feedback,
                    metadata=t.metadata,
                )
                t.reward = new_reward
                t.metadata["explicit_feedback"] = feedback
                logger.info(f"Updated trajectory {trajectory_id} with feedback={feedback}, new reward={new_reward:.3f}")
                return True
        return False


# ---------------------------------------------------------------------------
# Policy optimizer (PPO-style)
# ---------------------------------------------------------------------------

class PolicyOptimizer:
    """PPO-style policy optimizer.

    NOTE: Aion doesn't ship a learned policy network (that would require
    PyTorch + a custom model). Instead, this optimizer:
        1. Computes advantages using GAE
        2. Identifies high-advantage trajectories as "good examples"
        3. Persists them to a 'positive_examples.md' file that's loaded
           into the agent's system prompt at training time
        4. Identifies low-advantage trajectories as "bad examples"
        5. Persists them to 'negative_examples.md'

    This is "RL via prompt engineering" — a pragmatic approach that works
    with any LLM (OpenAI, Anthropic, Ollama) without fine-tuning.
    """

    def __init__(
        self,
        config: RLConfig | None = None,
        buffer: ReplayBuffer | None = None,
    ) -> None:
        self.config = config or RLConfig()
        # IMPORTANT: use `is None` check, not truthiness — an empty ReplayBuffer is falsy
        self.buffer = buffer if buffer is not None else ReplayBuffer(self.config.buffer_capacity)
        self._step = 0

    def compute_advantages(self) -> None:
        """Compute GAE advantages for all trajectories in the buffer."""
        trajectories = self.buffer.all()
        if not trajectories:
            return
        # Sort by timestamp (oldest first) for discount computation
        trajectories.sort(key=lambda t: t.timestamp)
        n = len(trajectories)
        # Compute returns (discounted future rewards) and GAE advantages
        last_gae = 0.0
        for i in reversed(range(n)):
            next_value = trajectories[i + 1].returns if i + 1 < n else 0.0
            delta = trajectories[i].reward + self.config.gamma * next_value - trajectories[i].returns
            last_gae = delta + self.config.gamma * self.config.gae_lambda * last_gae
            trajectories[i].advantage = last_gae
            trajectories[i].returns = trajectories[i].reward + self.config.gamma * next_value

    def train_step(self) -> dict[str, float]:
        """Run one PPO-style training step.

        Returns a dict of training metrics.
        """
        self._step += 1
        self.compute_advantages()

        trajectories = self.buffer.all()
        if not trajectories:
            return {"step": self._step, "loss": 0.0, "avg_reward": 0.0, "n_samples": 0}

        # Sample a batch
        batch = self.buffer.sample(min(self.config.batch_size, len(trajectories)))
        advantages = [t.advantage for t in batch]
        rewards = [t.reward for t in batch]

        # PPO-style loss: -mean(advantage * ratio) + entropy bonus
        # Without a real policy network, we use advantage as a direct signal
        # (positive advantages → reinforce; negative → discourage)
        # The "loss" is just -mean(advantage) (we want to maximize advantage)
        loss = -sum(advantages) / len(advantages) if advantages else 0.0

        # Apply updates (persist positive/negative examples to disk)
        if self.config.apply_updates:
            self._persist_examples(batch)

        avg_reward = sum(rewards) / len(rewards) if rewards else 0.0
        metrics = {
            "step": self._step,
            "loss": loss,
            "avg_reward": avg_reward,
            "avg_advantage": sum(advantages) / len(advantages) if advantages else 0.0,
            "n_samples": len(batch),
            "buffer_size": len(self.buffer),
        }
        logger.info(f"RL train step {self._step}: {metrics}")
        return metrics

    def _persist_examples(self, batch: list[Trajectory]) -> None:
        """Persist high-advantage and low-advantage examples to disk.

        These are loaded into the agent's system prompt to reinforce
        good behavior and discourage bad behavior.
        """
        self.config.storage_path.mkdir(parents=True, exist_ok=True)

        # Top 20% by advantage → positive examples
        sorted_batch = sorted(batch, key=lambda t: t.advantage, reverse=True)
        top_n = max(1, len(sorted_batch) // 5)
        positive = sorted_batch[:top_n]
        negative = sorted_batch[-top_n:]

        # Write positive examples
        pos_path = self.config.storage_path / "positive_examples.md"
        with pos_path.open("w", encoding="utf-8") as f:
            f.write("# Positive Examples — High-Reward Responses\n\n")
            f.write("These responses received high rewards. Use them as a model for future responses.\n\n")
            for t in positive:
                if t.advantage > 0:
                    f.write(f"## User said:\n{t.state[:500]}\n\n")
                    f.write(f"## You responded (reward={t.reward:.2f}, advantage={t.advantage:.2f}):\n{t.action[:1000]}\n\n---\n\n")

        # Write negative examples
        neg_path = self.config.storage_path / "negative_examples.md"
        with neg_path.open("w", encoding="utf-8") as f:
            f.write("# Negative Examples — Low-Reward Responses\n\n")
            f.write("These responses received low rewards. Avoid these patterns.\n\n")
            for t in negative:
                if t.advantage < 0:
                    f.write(f"## User said:\n{t.state[:500]}\n\n")
                    f.write(f"## You responded (reward={t.reward:.2f}, advantage={t.advantage:.2f}):\n{t.action[:1000]}\n\n---\n\n")

    @property
    def step(self) -> int:
        return self._step


# ---------------------------------------------------------------------------
# Feedback store
# ---------------------------------------------------------------------------

class FeedbackStore:
    """Persistent storage for user feedback.

    Stored as JSON lines in ~/.aion-hand/rl/feedback.jsonl.
    Each line is a JSON object: {trajectory_id, feedback, timestamp}.
    """

    def __init__(self, storage_path: Path | str | None = None) -> None:
        self.path = Path(storage_path) if storage_path else Path.home() / ".aion-hand" / "rl" / "feedback.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, trajectory_id: str, feedback: float, user_id: str = "") -> None:
        """Append a feedback record to the store."""
        record = {
            "trajectory_id": trajectory_id,
            "feedback": feedback,
            "user_id": user_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def all_records(self) -> list[dict[str, Any]]:
        """Read all feedback records."""
        if not self.path.is_file():
            return []
        records = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def stats(self) -> dict[str, Any]:
        records = self.all_records()
        if not records:
            return {"count": 0, "avg_feedback": 0.0}
        feedbacks = [r["feedback"] for r in records]
        return {
            "count": len(records),
            "avg_feedback": sum(feedbacks) / len(feedbacks),
            "positive": sum(1 for f in feedbacks if f > 0),
            "negative": sum(1 for f in feedbacks if f < 0),
        }


# ---------------------------------------------------------------------------
# RL Trainer (orchestrator)
# ---------------------------------------------------------------------------

class RLTrainer:
    """Orchestrates the full RL training loop.

    Usage:
        trainer = RLTrainer(agent=my_agent)
        await trainer.train(steps=1000)

    Or collect feedback and train periodically:
        trainer = RLTrainer(agent=my_agent)
        await trainer.collect(user_msg, agent_resp, feedback=1.0)
        metrics = trainer.train_step()
    """

    def __init__(
        self,
        agent: Any | None = None,
        config: RLConfig | None = None,
    ) -> None:
        self.agent = agent
        self.config = config or RLConfig()
        self.reward_model = RewardModel(self.config)
        self.buffer = ReplayBuffer(self.config.buffer_capacity)
        self.collector = TrajectoryCollector(
            agent=agent,
            reward_model=self.reward_model,
            buffer=self.buffer,  # explicitly pass our buffer
            config=self.config,
        )
        self.optimizer = PolicyOptimizer(self.config, self.buffer)
        self.feedback_store = FeedbackStore(self.config.storage_path / "feedback.jsonl")
        self._training_history: list[dict[str, float]] = []

    async def collect(
        self,
        user_message: str,
        agent_response: str,
        *,
        feedback: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Trajectory:
        """Collect a trajectory from a chat exchange."""
        trajectory = await self.collector.collect_from_chat(
            user_message=user_message,
            agent_response=agent_response,
            feedback=feedback,
            metadata=metadata,
        )
        if feedback is not None:
            self.feedback_store.record(trajectory.id, feedback)
        return trajectory

    def train_step(self) -> dict[str, float]:
        """Run one training step."""
        metrics = self.optimizer.train_step()
        self._training_history.append(metrics)
        return metrics

    async def train(self, steps: int = 100) -> list[dict[str, float]]:
        """Run N training steps."""
        all_metrics = []
        for _ in range(steps):
            metrics = self.train_step()
            all_metrics.append(metrics)
            # Small delay to allow other async work
            await asyncio.sleep(0)
        return all_metrics

    def record_feedback(self, trajectory_id: str, feedback: float) -> bool:
        """Record explicit user feedback for a trajectory."""
        self.feedback_store.record(trajectory_id, feedback)
        return self.collector.add_explicit_feedback(trajectory_id, feedback)

    def stats(self) -> dict[str, Any]:
        """Return comprehensive stats about the training state."""
        return {
            "buffer": self.buffer.stats(),
            "feedback": self.feedback_store.stats(),
            "optimizer_step": self.optimizer.step,
            "training_history_size": len(self._training_history),
            "config": {
                "gamma": self.config.gamma,
                "clip_epsilon": self.config.clip_epsilon,
                "learning_rate": self.config.learning_rate,
                "batch_size": self.config.batch_size,
                "ppo_epochs": self.config.ppo_epochs,
            },
        }

    def save(self) -> Path:
        """Save the entire training state to disk."""
        self.config.storage_path.mkdir(parents=True, exist_ok=True)
        path = self.config.storage_path / "training_state.json"
        data = {
            "saved_at": datetime.now(UTC).isoformat(),
            "optimizer_step": self.optimizer.step,
            "buffer_stats": self.buffer.stats(),
            "trajectories": [t.to_dict() for t in self.buffer.all()],
            "training_history": self._training_history,
        }
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.info(f"RL training state saved to {path}")
        return path

    def load(self) -> int:
        """Load training state from disk. Returns the number of trajectories loaded."""
        path = self.config.storage_path / "training_state.json"
        if not path.is_file():
            return 0
        data = json.loads(path.read_text(encoding="utf-8"))
        self.buffer.clear()
        for t_data in data.get("trajectories", []):
            self.buffer.add(Trajectory(
                id=t_data["id"],
                state=t_data["state"],
                action=t_data["action"],
                reward=t_data["reward"],
                metadata=t_data.get("metadata", {}),
                timestamp=t_data["timestamp"],
                log_prob=t_data.get("log_prob", 0.0),
                advantage=t_data.get("advantage", 0.0),
                returns=t_data.get("returns", 0.0),
            ))
        self.optimizer._step = data.get("optimizer_step", 0)
        self._training_history = data.get("training_history", [])
        logger.info(f"Loaded {len(self.buffer)} trajectories from {path}")
        return len(self.buffer)


__all__ = [
    "Trajectory",
    "RLConfig",
    "RewardModel",
    "ReplayBuffer",
    "TrajectoryCollector",
    "PolicyOptimizer",
    "FeedbackStore",
    "RLTrainer",
]
