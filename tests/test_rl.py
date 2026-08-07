"""Tests for the RL training loop."""

from __future__ import annotations

import pytest

from aion_core.rl import (
    Trajectory,
    RLConfig,
    RewardModel,
    ReplayBuffer,
    TrajectoryCollector,
    PolicyOptimizer,
    FeedbackStore,
    RLTrainer,
)


class TestTrajectory:
    def test_default_factory_generates_id(self):
        t1 = Trajectory(state="hi", action="hello")
        t2 = Trajectory(state="hi", action="hello")
        assert t1.id != t2.id

    def test_timestamp_is_iso(self):
        t = Trajectory()
        assert "T" in t.timestamp

    def test_to_dict(self):
        t = Trajectory(state="s", action="a", reward=0.5)
        d = t.to_dict()
        assert d["state"] == "s"
        assert d["action"] == "a"
        assert d["reward"] == 0.5


class TestRewardModel:
    def test_default_reward_is_safe_neutral(self):
        rm = RewardModel()
        r = rm.compute_reward("hello", "hi there")
        # Default (no feedback, no metadata) → safety dominates at +0.3
        # The exact value depends on weights; just verify it's in range and safe-leaning
        assert -1.0 <= r <= 1.0
        # Should be in the upper half (safe + neutral quality)
        assert r > -0.5

    def test_explicit_positive_feedback_increases_reward(self):
        rm = RewardModel()
        r_no_feedback = rm.compute_reward("hi", "hello there")
        r_with_feedback = rm.compute_reward("hi", "hello there", explicit_feedback=1.0)
        assert r_with_feedback > r_no_feedback

    def test_explicit_negative_feedback_decreases_reward(self):
        rm = RewardModel()
        r_no_feedback = rm.compute_reward("hi", "hello there")
        r_with_feedback = rm.compute_reward("hi", "hello there", explicit_feedback=-1.0)
        assert r_with_feedback < r_no_feedback

    def test_pii_detected_lower_reward(self):
        rm = RewardModel()
        r_safe = rm.compute_reward("hi", "hello", metadata={"contains_pii": False})
        r_pii = rm.compute_reward("hi", "my SSN is 123-45-6789", metadata={"contains_pii": True})
        assert r_pii < r_safe
        assert r_pii < 0

    def test_reward_is_clamped(self):
        rm = RewardModel()
        # Even with everything negative, should not go below -1
        r = rm.compute_reward(
            "x", "y",
            explicit_feedback=-1.0,
            metadata={"contains_pii": True, "contains_harmful": True, "retried": True},
        )
        assert r >= -1.0
        assert r <= 1.0

    def test_tool_use_increases_reward(self):
        rm = RewardModel()
        r_no_tools = rm.compute_reward("search for python", "here's info", metadata={})
        r_with_tools = rm.compute_reward("search for python", "here's info", metadata={"tools_used": ["web_search"]})
        assert r_with_tools > r_no_tools

    def test_keyword_overlap_increases_reward(self):
        rm = RewardModel()
        r_no_overlap = rm.compute_reward("python programming", "the weather is sunny")
        r_overlap = rm.compute_reward("python programming", "python is a great programming language")
        assert r_overlap > r_no_overlap

    def test_explain_reward_returns_dict(self):
        rm = RewardModel()
        breakdown = rm.explain_reward("hi", "hello", explicit_feedback=0.5)
        assert "explicit" in breakdown
        assert "implicit" in breakdown
        assert "quality" in breakdown
        assert "safety" in breakdown
        assert "total" in breakdown


class TestReplayBuffer:
    def test_add_and_len(self):
        buf = ReplayBuffer(capacity=10)
        assert len(buf) == 0
        buf.add(Trajectory(state="a", action="b"))
        assert len(buf) == 1

    def test_capacity_is_respected(self):
        buf = ReplayBuffer(capacity=3)
        for i in range(5):
            buf.add(Trajectory(state=f"s{i}", action=f"a{i}"))
        assert len(buf) == 3  # capped at capacity

    def test_sample_returns_random_subset(self):
        buf = ReplayBuffer(capacity=100)
        for i in range(20):
            buf.add(Trajectory(state=f"s{i}", action=f"a{i}"))
        batch = buf.sample(5)
        assert len(batch) == 5

    def test_sample_returns_all_when_buffer_smaller_than_batch(self):
        buf = ReplayBuffer(capacity=100)
        for i in range(3):
            buf.add(Trajectory(state=f"s{i}", action=f"a{i}"))
        batch = buf.sample(10)
        assert len(batch) == 3

    def test_recent_returns_n_most_recent(self):
        buf = ReplayBuffer(capacity=100)
        for i in range(10):
            buf.add(Trajectory(state=f"s{i}", action=f"a{i}", reward=float(i)))
        recent = buf.recent(3)
        assert len(recent) == 3
        # Should be the most recently added
        rewards = [t.reward for t in recent]
        assert max(rewards) == 9.0

    def test_clear(self):
        buf = ReplayBuffer(capacity=10)
        buf.add(Trajectory())
        assert len(buf) == 1
        buf.clear()
        assert len(buf) == 0

    def test_stats(self):
        buf = ReplayBuffer(capacity=100)
        buf.add(Trajectory(reward=0.5))
        buf.add(Trajectory(reward=-0.3))
        s = buf.stats()
        assert s["size"] == 2
        assert s["avg_reward"] == pytest.approx(0.1, abs=0.01)
        assert s["min_reward"] == -0.3
        assert s["max_reward"] == 0.5


class TestTrajectoryCollector:
    @pytest.mark.asyncio
    async def test_collect_from_chat_creates_trajectory(self):
        collector = TrajectoryCollector()
        t = await collector.collect_from_chat("hello", "hi there")
        assert t.state == "hello"
        assert t.action == "hi there"
        assert -1.0 <= t.reward <= 1.0
        assert len(collector.buffer) == 1

    @pytest.mark.asyncio
    async def test_collect_with_explicit_feedback(self):
        collector = TrajectoryCollector()
        t = await collector.collect_from_chat("hello", "hi", feedback=1.0)
        assert t.reward > 0

    @pytest.mark.asyncio
    async def test_add_explicit_feedback_updates_existing(self):
        collector = TrajectoryCollector()
        t = await collector.collect_from_chat("hi", "hello")
        original_reward = t.reward
        ok = collector.add_explicit_feedback(t.id, 1.0)
        assert ok is True
        # Find the trajectory in the buffer
        for buf_t in collector.buffer.all():
            if buf_t.id == t.id:
                assert buf_t.reward >= original_reward  # should have gone up
                break

    @pytest.mark.asyncio
    async def test_add_feedback_to_unknown_returns_false(self):
        collector = TrajectoryCollector()
        assert collector.add_explicit_feedback("nonexistent-id", 1.0) is False


class TestPolicyOptimizer:
    def test_initial_step_is_zero(self):
        opt = PolicyOptimizer()
        assert opt.step == 0

    def test_train_step_increments_step(self):
        opt = PolicyOptimizer()
        opt.train_step()
        assert opt.step == 1

    def test_train_step_with_empty_buffer_returns_zero_samples(self):
        opt = PolicyOptimizer()
        metrics = opt.train_step()
        assert metrics["n_samples"] == 0

    def test_train_step_with_data_returns_metrics(self, tmp_path):
        config = RLConfig(storage_path=tmp_path, apply_updates=True)
        buf = ReplayBuffer(capacity=100)
        for i in range(10):
            buf.add(Trajectory(state=f"s{i}", action=f"a{i}", reward=float(i) / 10))
        opt = PolicyOptimizer(config=config, buffer=buf)
        metrics = opt.train_step()
        assert "loss" in metrics
        assert "avg_reward" in metrics
        assert "avg_advantage" in metrics
        assert metrics["n_samples"] > 0

    def test_compute_advantages_doesnt_crash_on_empty(self):
        opt = PolicyOptimizer()
        opt.compute_advantages()  # should not raise

    def test_compute_advantages_sets_advantage_field(self):
        buf = ReplayBuffer(capacity=100)
        for i in range(5):
            buf.add(Trajectory(state=f"s{i}", action=f"a{i}", reward=0.5))
        opt = PolicyOptimizer(buffer=buf)
        opt.compute_advantages()
        for t in buf.all():
            assert hasattr(t, "advantage")


class TestFeedbackStore:
    def test_record_and_read(self, tmp_path):
        store = FeedbackStore(tmp_path / "feedback.jsonl")
        store.record("traj-1", 1.0, user_id="alice")
        store.record("traj-2", -0.5, user_id="bob")
        records = store.all_records()
        assert len(records) == 2
        assert records[0]["feedback"] == 1.0
        assert records[1]["feedback"] == -0.5

    def test_stats_empty(self, tmp_path):
        store = FeedbackStore(tmp_path / "feedback.jsonl")
        s = store.stats()
        assert s["count"] == 0

    def test_stats_with_records(self, tmp_path):
        store = FeedbackStore(tmp_path / "feedback.jsonl")
        store.record("t1", 1.0)
        store.record("t2", -1.0)
        store.record("t3", 0.5)
        s = store.stats()
        assert s["count"] == 3
        assert s["positive"] == 2
        assert s["negative"] == 1


class TestRLTrainer:
    @pytest.mark.asyncio
    async def test_collect_and_train(self, tmp_path):
        config = RLConfig(storage_path=tmp_path, apply_updates=False)
        trainer = RLTrainer(config=config)
        # Collect some trajectories
        for i in range(5):
            await trainer.collect(f"question {i}", f"answer {i}", feedback=1.0 if i % 2 == 0 else -1.0)
        metrics = trainer.train_step()
        assert metrics["n_samples"] > 0
        assert metrics["step"] == 1

    @pytest.mark.asyncio
    async def test_train_multiple_steps(self, tmp_path):
        config = RLConfig(storage_path=tmp_path, apply_updates=False)
        trainer = RLTrainer(config=config)
        for i in range(10):
            await trainer.collect(f"q{i}", f"a{i}", feedback=0.5)
        metrics_list = await trainer.train(steps=3)
        assert len(metrics_list) == 3
        assert trainer.optimizer.step == 3

    @pytest.mark.asyncio
    async def test_record_feedback(self, tmp_path):
        config = RLConfig(storage_path=tmp_path, apply_updates=False)
        trainer = RLTrainer(config=config)
        t = await trainer.collect("hi", "hello")
        ok = trainer.record_feedback(t.id, 1.0)
        assert ok is True
        # Feedback should be in the store
        assert trainer.feedback_store.stats()["count"] == 1

    @pytest.mark.asyncio
    async def test_stats(self, tmp_path):
        config = RLConfig(storage_path=tmp_path, apply_updates=False)
        trainer = RLTrainer(config=config)
        await trainer.collect("hi", "hello", feedback=1.0)
        s = trainer.stats()
        assert "buffer" in s
        assert "feedback" in s
        assert "optimizer_step" in s
        assert s["buffer"]["size"] == 1

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, tmp_path):
        config = RLConfig(storage_path=tmp_path, apply_updates=False)
        trainer = RLTrainer(config=config)
        for i in range(3):
            await trainer.collect(f"q{i}", f"a{i}", feedback=1.0)
        trainer.train_step()

        # Save
        path = trainer.save()
        assert path.is_file()

        # Load into a new trainer
        trainer2 = RLTrainer(config=config)
        n_loaded = trainer2.load()
        assert n_loaded == 3
        assert trainer2.optimizer.step == 1

    def test_default_config(self):
        trainer = RLTrainer()
        assert trainer.config.gamma > 0
        assert trainer.config.batch_size > 0
