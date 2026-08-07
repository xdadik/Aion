# Aion Hand - Parallel Executor
# Executes execution plans (DAGs) with parallel workers, dependency resolution,
# timeouts, retries, and comprehensive result tracking.

import asyncio
import contextlib
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .planner import ExecutionPlan, PlanNode

logger = logging.getLogger("aion_hand.pipeline")


@dataclass
class ExecutionResult:
    """Result of executing a single plan node."""
    node_id: str = ""
    status: str = "pending"  # success, failed, timeout, cancelled, skipped
    output: Any = None
    tokens_used: int = 0
    elapsed: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status,
            "output": self._safe_output(),
            "tokens_used": self.tokens_used,
            "elapsed": round(self.elapsed, 3),
            "error": self.error,
            "metadata": self.metadata,
            "retry_count": self.retry_count,
        }

    def _safe_output(self) -> Any:
        """Truncate large outputs for serialization."""
        if self.output is None:
            return None
        output_str = str(self.output)
        if len(output_str) > 5000:
            return output_str[:5000] + f"... [truncated, total {len(output_str)} chars]"
        return self.output


class ParallelExecutor:
    """Executes an ExecutionPlan with parallel workers.

    Performs topological sort, resolves dependencies, runs independent
    nodes concurrently using a semaphore-bounded worker pool, and handles
    timeouts and retries with full result tracking.
    """

    def __init__(self, agent: Any, max_workers: int = 5):
        self._agent = agent
        self._max_workers = max_workers
        self._worker_pool = asyncio.Semaphore(max_workers)
        self._results: Dict[str, ExecutionResult] = {}
        self._execution_log: List[Dict[str, Any]] = []
        self._cancelled = False

    @property
    def results(self) -> Dict[str, ExecutionResult]:
        return dict(self._results)

    @property
    def execution_log(self) -> List[Dict[str, Any]]:
        return list(self._execution_log)

    async def execute(self, plan: ExecutionPlan) -> Dict[str, ExecutionResult]:
        """Execute an entire execution plan.

        Args:
            plan: The execution plan (DAG of nodes) to execute.

        Returns:
            Dictionary mapping node IDs to their ExecutionResult.
        """
        self._results = {}
        self._execution_log = []
        self._cancelled = False

        start_time = time.monotonic()
        logger.info(
            f"Starting plan execution: {len(plan.nodes)} nodes, "
            f"max_workers={self._max_workers}, entry={plan.entry_node}"
        )

        self._log("plan_start", {"node_count": len(plan.nodes), "entry": plan.entry_node})

        try:
            topo_order = self._topological_sort(plan)
            logger.debug(f"Topological order: {topo_order}")

            for node_id in plan.nodes:
                self._results[node_id] = ExecutionResult(node_id=node_id, status="pending")

            await self._execute_graph(plan, topo_order)

        except asyncio.CancelledError:
            logger.warning("Plan execution cancelled")
            self._cancelled = True
            for _nid, result in self._results.items():
                if result.status == "pending":
                    result.status = "cancelled"

        elapsed = time.monotonic() - start_time
        successful = sum(1 for r in self._results.values() if r.status == "success")
        failed = sum(1 for r in self._results.values() if r.status == "failed")
        total_tokens = sum(r.tokens_used for r in self._results.values())

        logger.info(
            f"Plan execution complete in {elapsed:.2f}s: "
            f"{successful} succeeded, {failed} failed, {total_tokens} tokens used"
        )
        self._log("plan_end", {
            "elapsed": round(elapsed, 3),
            "successful": successful,
            "failed": failed,
            "total_tokens": total_tokens,
        })

        return dict(self._results)

    def cancel(self) -> None:
        """Request cancellation of the current execution."""
        self._cancelled = True
        logger.info("Execution cancellation requested")

    async def _execute_graph(self, plan: ExecutionPlan, topo_order: List[str]) -> None:
        """Execute the plan graph using event-driven dependency resolution."""
        completed: Set[str] = set()
        in_flight: Set[str] = set()
        failed_nodes: Set[str] = set()
        completion_events: Dict[str, asyncio.Event] = {}

        for node_id in plan.nodes:
            completion_events[node_id] = asyncio.Event()

        async def run_node(node_id: str) -> None:
            """Execute a single node with semaphore gating."""
            async with self._worker_pool:
                if self._cancelled:
                    self._results[node_id].status = "cancelled"
                    completion_events[node_id].set()
                    return

                node = plan.nodes[node_id]

                deps_failed = [
                    dep for dep in node.dependencies
                    if dep in failed_nodes and not self._results[dep].metadata.get("retried", False)
                ]
                if deps_failed:
                    self._results[node_id].status = "failed"
                    self._results[node_id].error = f"Dependencies failed: {deps_failed}"
                    failed_nodes.add(node_id)
                    completion_events[node_id].set()
                    return

                context = self._build_upstream_context(node, plan)
                result = await self._execute_node_with_retries(node, context)
                self._results[node_id] = result

                if result.status == "failed":
                    failed_nodes.add(node_id)

                completion_events[node_id].set()

        while len(completed) < len(plan.nodes) and not self._cancelled:
            ready_nodes = []
            for node_id in topo_order:
                if node_id in completed or node_id in in_flight:
                    continue
                node = plan.nodes[node_id]
                if all(dep in completed for dep in node.dependencies):
                    ready_nodes.append(node_id)

            if not ready_nodes:
                if in_flight:
                    await asyncio.sleep(0.05)
                    for nid in list(in_flight):
                        if completion_events[nid].is_set():
                            in_flight.discard(nid)
                            completed.add(nid)
                    continue
                else:
                    break

            for node_id in ready_nodes:
                if self._cancelled:
                    break
                in_flight.add(node_id)
                asyncio.create_task(self._run_and_catch(node_id, run_node(node_id), completion_events[node_id]))

            if in_flight:
                await asyncio.sleep(0.05)
                for nid in list(in_flight):
                    if completion_events[nid].is_set():
                        in_flight.discard(nid)
                        completed.add(nid)

        if in_flight:
            for nid in list(in_flight):
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(completion_events[nid].wait(), timeout=5.0)
                in_flight.discard(nid)
                completed.add(nid)

    async def _run_and_catch(self, node_id: str, coro: Any, event: asyncio.Event) -> None:
        """Run a node coroutine and ensure the completion event is always set."""
        try:
            await coro
        except Exception as e:
            logger.error(f"Unexpected error in node {node_id}: {e}")
            if node_id in self._results and self._results[node_id].status == "pending":
                self._results[node_id].status = "failed"
                self._results[node_id].error = str(e)
        finally:
            event.set()

    async def _execute_node_with_retries(self, node: PlanNode, context: Dict[str, Any]) -> ExecutionResult:
        """Execute a node with retry logic."""
        last_result = None
        for attempt in range(node.retry_limit + 1):
            if self._cancelled:
                return ExecutionResult(node_id=node.id, status="cancelled", retry_count=attempt)

            result = await self._execute_node(node, context)
            result.retry_count = attempt

            if result.status == "success":
                return result

            last_result = result
            if attempt < node.retry_limit:
                wait_time = min(2.0 ** attempt, 10.0)
                logger.info(
                    f"Node '{node.name}' failed (attempt {attempt + 1}/{node.retry_limit + 1}), "
                    f"retrying in {wait_time}s: {result.error}"
                )
                self._log("node_retry", {
                    "node_id": node.id,
                    "attempt": attempt + 1,
                    "error": result.error,
                    "wait": wait_time,
                })
                await asyncio.sleep(wait_time)

        return last_result or ExecutionResult(
            node_id=node.id, status="failed", error="All retry attempts exhausted", retry_count=node.retry_limit
        )

    async def _execute_node(self, node: PlanNode, context: Dict[str, Any]) -> ExecutionResult:
        """Execute a single node based on its type."""
        start_time = time.monotonic()
        logger.info(f"Executing node '{node.name}' (type={node.node_type})")
        self._log("node_start", {"node_id": node.id, "type": node.node_type})

        try:
            if node.node_type == "agent":
                result = await self._execute_agent_node(node, context)
            elif node.node_type == "tool":
                result = await self._execute_tool_node(node, context)
            elif node.node_type == "parallel":
                result = await self._execute_parallel_node(node, context)
            elif node.node_type == "condition":
                result = await self._execute_condition_node(node, context)
            elif node.node_type == "merge":
                result = await self._execute_merge_node(node, context)
            elif node.node_type == "verify":
                result = await self._execute_verify_node(node, context)
            else:
                result = ExecutionResult(node_id=node.id, status="failed", error=f"Unknown node type: {node.node_type}")
        except TimeoutError:
            elapsed = time.monotonic() - start_time
            result = ExecutionResult(node_id=node.id, status="timeout", error=f"Node timed out after {node.timeout}s", elapsed=elapsed)
            logger.warning(f"Node '{node.name}' timed out after {node.timeout}s")
        except Exception as e:
            elapsed = time.monotonic() - start_time
            result = ExecutionResult(node_id=node.id, status="failed", error=str(e), elapsed=elapsed)
            logger.error(f"Node '{node.name}' failed with error: {e}")
        else:
            result.elapsed = time.monotonic() - start_time

        self._log("node_end", {"node_id": node.id, "status": result.status, "elapsed": round(result.elapsed, 3), "tokens_used": result.tokens_used})
        return result

    async def _execute_agent_node(self, node: PlanNode, context: Dict[str, Any]) -> ExecutionResult:
        """Execute an agent node by calling agent.chat()."""
        if not node.prompt:
            return ExecutionResult(node_id=node.id, status="failed", error="Agent node has no prompt")

        resolved_prompt = self._resolve_prompt_placeholders(node.prompt, context)

        result = await asyncio.wait_for(
            self._agent.chat(message=resolved_prompt),
            timeout=node.timeout,
        )

        if isinstance(result, dict):
            content = result.get("content", "")
            tokens = result.get("metadata", {}).get("tokens_used", 0)
            if not tokens:
                tokens = result.get("metadata", {}).get("total_tokens", 0)
            if not tokens:
                tokens = len(str(content)) // 4
        else:
            content = str(result)
            tokens = len(content) // 4

        return ExecutionResult(node_id=node.id, status="success", output=content, tokens_used=tokens, metadata={"agent_type": node.agent_type})

    async def _execute_tool_node(self, node: PlanNode, context: Dict[str, Any]) -> ExecutionResult:
        """Execute a tool node by calling agent.execute_tool()."""
        if not node.tool_name:
            return ExecutionResult(node_id=node.id, status="failed", error="Tool node has no tool_name")

        tool_args = node.metadata.get("tool_args", {})
        if isinstance(tool_args, str):
            tool_args = {"query": tool_args}

        result = await asyncio.wait_for(
            self._agent.execute_tool(node.tool_name, **tool_args),
            timeout=node.timeout,
        )

        return ExecutionResult(node_id=node.id, status="success", output=result, tokens_used=0, metadata={"tool_name": node.tool_name})

    async def _execute_parallel_node(self, node: PlanNode, context: Dict[str, Any]) -> ExecutionResult:
        """Execute a parallel node - delegates to graph-level parallel execution."""
        parallel_results = context.get("parallel_results", [])
        return ExecutionResult(node_id=node.id, status="success", output=parallel_results, metadata={"parallel_group": node.parallel_group})

    async def _execute_condition_node(self, node: PlanNode, context: Dict[str, Any]) -> ExecutionResult:
        """Execute a condition node - evaluate and route."""
        if not node.prompt:
            return ExecutionResult(node_id=node.id, status="failed", error="Condition node has no prompt to evaluate")

        resolved_prompt = self._resolve_prompt_placeholders(node.prompt, context)
        condition_prompt = f"Evaluate this condition and respond with ONLY 'true' or 'false':\n\n{resolved_prompt}"

        result = await asyncio.wait_for(
            self._agent.chat(message=condition_prompt),
            timeout=node.timeout,
        )

        content = result.get("content", "") if isinstance(result, dict) else str(result)
        evaluation = "true" in content.lower().strip()[:20]

        return ExecutionResult(
            node_id=node.id, status="success",
            output={"condition_result": evaluation, "raw": content},
            tokens_used=len(content) // 4,
            metadata={"condition_result": evaluation},
        )

    async def _execute_merge_node(self, node: PlanNode, context: Dict[str, Any]) -> ExecutionResult:
        """Execute a merge node - combine upstream results."""
        upstream_results = context.get("upstream_results", {})

        if not upstream_results:
            return ExecutionResult(node_id=node.id, status="success", output="", metadata={"merged_count": 0})

        if not node.prompt:
            if isinstance(upstream_results, dict):
                merged_parts = []
                for dep_id in sorted(upstream_results.keys()):
                    dep_result = upstream_results[dep_id]
                    if isinstance(dep_result, dict):
                        merged_parts.append(dep_result.get("output", ""))
                    else:
                        merged_parts.append(str(dep_result))
                merged = "\n\n".join(str(p) for p in merged_parts if p)
            else:
                merged = str(upstream_results)

            return ExecutionResult(
                node_id=node.id, status="success", output=merged,
                metadata={"merged_count": len(upstream_results) if isinstance(upstream_results, dict) else 1},
            )

        resolved_prompt = self._resolve_prompt_placeholders(node.prompt, context)

        result = await asyncio.wait_for(
            self._agent.chat(message=resolved_prompt),
            timeout=node.timeout,
        )

        content = result.get("content", "") if isinstance(result, dict) else str(result)
        tokens = result.get("metadata", {}).get("tokens_used", 0) if isinstance(result, dict) else 0

        return ExecutionResult(
            node_id=node.id, status="success", output=content, tokens_used=tokens or len(content) // 4,
            metadata={"merged_count": len(upstream_results) if isinstance(upstream_results, dict) else 1},
        )

    async def _execute_verify_node(self, node: PlanNode, context: Dict[str, Any]) -> ExecutionResult:
        """Execute a verification node."""
        if not node.prompt:
            return ExecutionResult(node_id=node.id, status="success", output={"verified": True, "notes": "No verification prompt"})

        resolved_prompt = self._resolve_prompt_placeholders(node.prompt, context)

        result = await asyncio.wait_for(
            self._agent.chat(message=resolved_prompt),
            timeout=node.timeout,
        )

        content = result.get("content", "") if isinstance(result, dict) else str(result)
        tokens = result.get("metadata", {}).get("tokens_used", 0) if isinstance(result, dict) else 0

        return ExecutionResult(
            node_id=node.id, status="success", output=content,
            tokens_used=tokens or len(content) // 4,
            metadata={"node_type": "verify"},
        )

    def _build_upstream_context(self, node: PlanNode, plan: ExecutionPlan) -> Dict[str, Any]:
        """Build context from completed upstream dependency results."""
        upstream_results = {}
        all_outputs = []

        for dep_id in node.dependencies:
            dep_result = self._results.get(dep_id)
            if dep_result and dep_result.status == "success":
                upstream_results[dep_id] = dep_result.output
                if dep_result.output is not None:
                    all_outputs.append(str(dep_result.output))

        upstream_text = "\n\n---\n\n".join(all_outputs)

        return {
            "upstream_results": upstream_results,
            "upstream_text": upstream_text,
            "node_id": node.id,
            "node_name": node.name,
            "node_type": node.node_type,
        }

    def _resolve_prompt_placeholders(self, prompt: str, context: Dict[str, Any]) -> str:
        """Resolve {upstream_results} and {context} placeholders in prompts."""
        if not prompt:
            return ""

        upstream_text = context.get("upstream_text", "")
        if "{upstream_results}" in prompt:
            upstream_results = context.get("upstream_results", {})
            if isinstance(upstream_results, dict):
                formatted = []
                for dep_id, output in upstream_results.items():
                    output_str = str(output)[:2000]
                    formatted.append(f"[Result from {dep_id}]:\n{output_str}")
                resolved = prompt.replace("{upstream_results}", "\n\n".join(formatted))
            else:
                resolved = prompt.replace("{upstream_results}", str(upstream_text))
        else:
            resolved = prompt

        if "{context}" in resolved:
            resolved = resolved.replace("{context}", upstream_text or "No context available")

        return resolved

    def _topological_sort(self, plan: ExecutionPlan) -> List[str]:
        """Compute a topological ordering of plan nodes using Kahn's algorithm."""
        in_degree: Dict[str, int] = {nid: 0 for nid in plan.nodes}
        adj: Dict[str, List[str]] = defaultdict(list)

        for node in plan.nodes.values():
            for dep in node.dependencies:
                if dep in plan.nodes:
                    in_degree[node.id] += 1
                    adj[dep].append(node.id)

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        if plan.entry_node in queue:
            queue.remove(plan.entry_node)
            queue.insert(0, plan.entry_node)

        order = []
        while queue:
            node_id = queue.pop(0)
            order.append(node_id)
            for neighbor in adj[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(plan.nodes):
            missing = set(plan.nodes) - set(order)
            logger.warning(f"Cycle detected in plan, missing nodes: {missing}")
            for nid in plan.nodes:
                if nid not in order:
                    order.append(nid)

        return order

    def _log(self, event: str, data: Dict[str, Any]) -> None:
        """Record an execution log entry."""
        self._execution_log.append({"event": event, "timestamp": time.time(), **data})

    def get_metrics(self) -> Dict[str, Any]:
        """Get execution metrics summary."""
        if not self._results:
            return {"nodes_executed": 0}

        statuses = defaultdict(int)
        total_tokens = 0
        total_time = 0.0
        for r in self._results.values():
            statuses[r.status] += 1
            total_tokens += r.tokens_used
            total_time += r.elapsed

        return {
            "nodes_executed": len(self._results),
            "statuses": dict(statuses),
            "total_tokens": total_tokens,
            "total_time": round(total_time, 3),
            "log_entries": len(self._execution_log),
        }
