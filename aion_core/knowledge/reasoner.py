"""
GraphReasoner — Reasons over the knowledge graph to provide context-aware
suggestions, risk predictions, strategy recommendations, and failure
explanations.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Dict, List, Optional

from .graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class GraphReasoner:
    """Query and reason over the knowledge graph."""

    def __init__(self, graph: KnowledgeGraph) -> None:
        self._graph = graph

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------

    def get_context_for_task(self, task: str) -> Dict[str, Any]:
        """
        Given a task description, find relevant entities, relations,
        and related past tasks.
        """
        # Search for directly matching entities
        matched = self._graph.semantic_search(task, limit=15)
        matched_ids = {e.id for e in matched}

        # Expand by 2 hops
        expanded_entities: list = []
        for ent in matched:
            neighbors = self._graph.get_related_entities(ent.id, depth=2)
            for n in neighbors:
                if n.id not in matched_ids:
                    expanded_entities.append(n)

        # Gather all relations between matched entities
        all_ids = matched_ids | {e.id for e in expanded_entities}
        relations: list = []
        for eid in all_ids:
            for rel in self._graph.get_relations(eid):
                if rel.source_id in all_ids and rel.target_id in all_ids:
                    relations.append(rel)

        # Find similar past tasks
        past_tasks = [
            e for e in self._graph.find_entities(entity_type="task")
            if any(
                word in e.name.lower()
                for word in task.lower().split()
                if len(word) > 3
            )
        ]

        return {
            "task": task,
            "matched_entities": [
                {"id": e.id, "name": e.name, "type": e.entity_type, "props": e.properties}
                for e in matched
            ],
            "related_entities": [
                {"id": e.id, "name": e.name, "type": e.entity_type}
                for e in expanded_entities[:20]
            ],
            "relations": [
                {
                    "type": r.relation_type,
                    "source": r.source_id,
                    "target": r.target_id,
                    "weight": r.weight,
                }
                for r in relations[:20]
            ],
            "similar_tasks": [
                {"name": t.name, "success": t.properties.get("success")}
                for t in past_tasks[:10]
            ],
            "total_context_size": len(matched) + len(expanded_entities),
        }

    # ------------------------------------------------------------------
    # Tool suggestions
    # ------------------------------------------------------------------

    def suggest_tools(self, task: str) -> List[Dict[str, Any]]:
        """
        Based on similar past tasks, suggest tools that were useful.
        Returns a list sorted by relevance score.
        """
        task_lower = task.lower()
        task_words = set(task_lower.split())

        # Find past tasks that share keywords
        past_tasks = self._graph.find_entities(entity_type="task")
        relevant_tasks: list = []
        for t in past_tasks:
            overlap = len(task_words & set(t.name.lower().split()))
            if overlap > 0:
                relevant_tasks.append((overlap, t))

        relevant_tasks.sort(key=lambda x: x[0], reverse=True)
        top_tasks = [t for _, t in relevant_tasks[:10]]

        # Collect tools used by those tasks
        tool_scores: Dict[str, Dict[str, Any]] = {}
        for t in top_tasks:
            tool_rels = self._graph.get_relations(
                entity_id=t.id, relation_type="uses"
            )
            for rel in tool_rels:
                tool_ent = self._graph.get_entity(rel.target_id)
                if tool_ent and tool_ent.entity_type == "tool":
                    tid = tool_ent.id
                    success_bonus = 1.5 if t.properties.get("success") else 0.5
                    if tid not in tool_scores:
                        tool_scores[tid] = {
                            "name": tool_ent.name,
                            "score": 0.0,
                            "success_count": 0,
                            "fail_count": 0,
                        }
                    tool_scores[tid]["score"] += rel.weight * success_bonus
                    if t.properties.get("success"):
                        tool_scores[tid]["success_count"] += 1
                    else:
                        tool_scores[tid]["fail_count"] += 1

        # Also consider tools directly matching task words
        for tool in self._graph.find_entities(entity_type="tool"):
            tool_words = set(tool.name.lower().replace("-", "_").split("_"))
            overlap = len(task_words & tool_words)
            if overlap > 0 and tool.id not in tool_scores:
                tool_scores[tool.id] = {
                    "name": tool.name,
                    "score": overlap * 0.5,
                    "success_count": 0,
                    "fail_count": 0,
                }

        ranked = sorted(tool_scores.values(), key=lambda x: x["score"], reverse=True)
        return ranked[:10]

    # ------------------------------------------------------------------
    # Risk prediction
    # ------------------------------------------------------------------

    def predict_risks(self, task: str) -> List[Dict[str, Any]]:
        """
        Based on past failures with similar characteristics, predict
        potential risks for a given task.
        """
        task_lower = task.lower()
        task_words = set(task_lower.split())

        # Gather all error entities
        errors = self._graph.find_entities(entity_type="error")
        error_scores: list = []

        for err in errors:
            # Score by keyword overlap with task description
            overlap = len(task_words & set(err.name.lower().split()))
            if overlap == 0:
                # Also check related task names
                related_tasks = self._graph.get_related_entities(
                    err.id, relation_type="caused"
                )
                for rt in related_tasks:
                    overlap += len(task_words & set(rt.name.lower().split()))

            if overlap > 0:
                # Check if this error has been fixed
                fixes = self._graph.get_relations(
                    entity_id=err.id, relation_type="fixed_by"
                )
                error_scores.append({
                    "error": err.name,
                    "score": overlap,
                    "has_known_fix": bool(fixes),
                    "fix_entities": [
                        {
                            "name": self._graph.get_entity(f.target_id).name
                            if self._graph.get_entity(f.target_id)
                            else "unknown"
                        }
                        for f in fixes[:3]
                    ],
                    "related_task_names": [
                        t.name
                        for t in self._graph.get_related_entities(
                            err.id, relation_type="caused"
                        )[:3]
                    ],
                })

        error_scores.sort(key=lambda x: x["score"], reverse=True)
        return error_scores[:10]

    # ------------------------------------------------------------------
    # Strategy suggestion
    # ------------------------------------------------------------------

    def suggest_strategy(self, task: str) -> Dict[str, Any]:
        """
        Based on successful past approaches for similar tasks, suggest
        a strategy.
        """
        task_lower = task.lower()
        task_words = set(task_lower.split())

        # Find successful tasks
        successful = [
            t for t in self._graph.find_entities(entity_type="task")
            if t.properties.get("success") is True
        ]

        # Score by keyword overlap
        scored: list = []
        for t in successful:
            overlap = len(task_words & set(t.name.lower().split()))
            if overlap > 0:
                scored.append((overlap, t))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Aggregate tools from top similar successful tasks
        tool_counter: Counter = Counter()
        strategy_tasks: list = []
        for _, t in scored[:5]:
            tool_rels = self._graph.get_relations(
                entity_id=t.id, relation_type="uses"
            )
            tools_used = []
            for rel in tool_rels:
                tool_ent = self._graph.get_entity(rel.target_id)
                if tool_ent:
                    tool_counter[tool_ent.name] += 1
                    tools_used.append(tool_ent.name)
            strategy_tasks.append({
                "task": t.name,
                "tools": tools_used,
                "result": t.properties.get("result_summary", "")[:200],
            })

        # Determine most effective tool ordering
        tool_sequence = [name for name, _ in tool_counter.most_common(5)]

        # Check for skills that were used in similar tasks
        skills_used: list = []
        for _, t in scored[:5]:
            skill_rels = self._graph.get_relations(
                entity_id=t.id, relation_type="uses", direction="in"
            )
            for rel in skill_rels:
                ent = self._graph.get_entity(rel.source_id)
                if ent and ent.entity_type == "skill":
                    skills_used.append(ent.name)

        return {
            "recommended_tools": tool_sequence,
            "recommended_skills": list(set(skills_used))[:5],
            "similar_successful_tasks": strategy_tasks[:5],
            "confidence": round(min(scored[0][0] / max(len(task_words), 1), 1.0), 3)
            if scored
            else 0.0,
            "approach": self._synthesize_approach(strategy_tasks, tool_sequence),
        }

    def _synthesize_approach(
        self, tasks: List[Dict[str, Any]], tools: List[str]
    ) -> str:
        """Generate a natural-language strategy description."""
        if not tasks:
            return "No similar past tasks found. Consider breaking the task into smaller steps."

        tool_str = ", ".join(tools) if tools else "available tools"
        task_names = [t["task"][:60] for t in tasks[:3]]

        parts = [
            "Based on analysis of similar past tasks:",
        ]
        if task_names:
            parts.append(f"- Similar to: {'; '.join(task_names)}")
        if tools:
            parts.append(f"- Primary tools to use: {tool_str}")
        parts.append(
            "- Approach each step incrementally, verifying results before proceeding."
        )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Failure explanation
    # ------------------------------------------------------------------

    def explain_failure(
        self,
        error: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Look up similar past failures and how they were resolved.
        Returns explanation with fixes, related errors, and path to resolution.
        """
        error_lower = error.lower()
        error_words = set(error_lower.split())

        # Find similar errors
        all_errors = self._graph.find_entities(entity_type="error")
        similar: list = []
        for err in all_errors:
            overlap = len(error_words & set(err.name.lower().split()))
            if overlap > 0 or (len(error_lower) > 10 and error_lower[:15] in err.name.lower()):
                similar.append((overlap, err))

        similar.sort(key=lambda x: x[0], reverse=True)
        top_errors = [err for _, err in similar[:5]]

        # Collect fixes for similar errors
        fixes: list = []
        for err in top_errors:
            fix_rels = self._graph.get_relations(
                entity_id=err.id, relation_type="fixed_by"
            )
            for rel in fix_rels:
                fix_ent = self._graph.get_entity(rel.target_id)
                if fix_ent:
                    fixes.append({
                        "fix_entity": fix_ent.name,
                        "fix_type": fix_ent.entity_type,
                        "fix_properties": fix_ent.properties,
                        "similarity_score": overlap if (overlap := next(
                            (o for o, e in similar if e.id == err.id), 0
                        )) else 0,
                    })

        # Deduplicate fixes by name
        seen_fixes: set = set()
        unique_fixes = []
        for fix in fixes:
            key = fix["fix_entity"]
            if key not in seen_fixes:
                seen_fixes.add(key)
                unique_fixes.append(fix)

        # Find path from this error to any fix entity
        paths: list = []
        for err in top_errors:
            fix_rels = self._graph.get_relations(
                entity_id=err.id, relation_type="fixed_by"
            )
            for rel in fix_rels:
                path = self._graph.find_path(err.id, rel.target_id, max_depth=5)
                if path:
                    paths.append([
                        self._graph.get_entity(pid).name
                        if self._graph.get_entity(pid)
                        else pid
                        for pid in path
                    ])

        # Check context for additional hints
        context_entities = []
        if context:
            context_entities = self._graph.semantic_search(context, limit=5)

        return {
            "error": error,
            "similar_past_errors": [
                {"name": e.name, "type": e.entity_type, "props": e.properties}
                for e in top_errors
            ],
            "known_fixes": unique_fixes[:5],
            "resolution_paths": paths[:3],
            "context_entities": [
                {"name": e.name, "type": e.entity_type}
                for e in context_entities
            ],
            "summary": self._summarize_failure(top_errors, unique_fixes, paths),
        }

    def _summarize_failure(
        self,
        errors: list,
        fixes: list,
        paths: list,
    ) -> str:
        """Produce a human-readable failure explanation summary."""
        if not errors:
            return "No similar errors found in the knowledge graph."

        lines = [f"Found {len(errors)} similar error(s) in history."]

        if fixes:
            lines.append(f"Known fixes ({len(fixes)}):")
            for fix in fixes[:3]:
                lines.append(f"  - {fix['fix_entity']} (type: {fix['fix_type']})")
        else:
            lines.append("No known fixes found for this type of error.")
            lines.append("Consider documenting the solution once resolved.")

        if paths:
            lines.append(f"Resolution path example: {' → '.join(paths[0][:5])}")

        return "\n".join(lines)
