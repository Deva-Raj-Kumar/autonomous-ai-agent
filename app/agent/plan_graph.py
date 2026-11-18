"""Task-graph algorithms. Pure functions: no LLM, no I/O, easy to test.

A plan is a DAG, a Directed Acyclic Graph:
  - each task is a node,
  - "t3 depends_on t1" is an arrow t1 -> t3 (t1 must finish first),
  - "acyclic" = no loops. If t1 waits for t2 and t2 waits for t1, nothing can ever start.

We use Kahn's algorithm (topological sort):
  1. Count each task's unfinished dependencies (its "in-degree").
  2. Tasks with 0 dependencies are ready. Take one, mark it done, and lower the
     count of every task that depends on it.
  3. Repeat. If tasks are left over that never reach 0, there is a cycle.
"""

import heapq
from collections.abc import Sequence
from typing import Protocol

PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}  # lower number = runs earlier


class GraphTask(Protocol):
    """Anything with these attributes works (PlannedTask and Task both do).

    A Protocol is "duck typing" with type hints: no inheritance needed.
    """

    id: str
    depends_on: list[str]
    priority: str


def find_graph_errors(tasks: Sequence[GraphTask]) -> list[str]:
    """Return a list of human-readable problems. An empty list means the graph is valid."""
    if not tasks:
        return ["The plan has no tasks."]

    errors: list[str] = []
    ids = [t.id for t in tasks]
    known = set(ids)

    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        errors.append(f"Duplicate task ids: {', '.join(duplicates)}.")

    for task in tasks:
        if task.id in task.depends_on:
            errors.append(f"Task {task.id} depends on itself.")
        for dep in task.depends_on:
            if dep not in known:
                errors.append(f"Task {task.id} depends on unknown task '{dep}'.")

    if not duplicates:  # cycle detection needs unique ids
        stuck = _unsortable_tasks(tasks)
        if stuck:
            errors.append(f"Circular dependency between tasks: {', '.join(stuck)}.")
    return errors


def compute_execution_order(tasks: Sequence[GraphTask]) -> list[str]:
    """Topological order. Among tasks that are ready at the same time, higher
    priority goes first, then original listing order.

    Raises ValueError if the graph has a cycle.
    """
    index = {t.id: i for i, t in enumerate(tasks)}
    deps = {t.id: [d for d in t.depends_on if d in index] for t in tasks}
    dependents: dict[str, list[str]] = {t.id: [] for t in tasks}
    for task_id, task_deps in deps.items():
        for dep in task_deps:
            dependents[dep].append(task_id)

    remaining = {task_id: len(task_deps) for task_id, task_deps in deps.items()}
    by_id = {t.id: t for t in tasks}

    def sort_key(task_id: str) -> tuple[int, int, str]:
        return (PRIORITY_RANK.get(by_id[task_id].priority, 1), index[task_id], task_id)

    # A heap always pops the smallest key: the most important ready task.
    ready = [sort_key(task_id) for task_id, count in remaining.items() if count == 0]
    heapq.heapify(ready)

    order: list[str] = []
    while ready:
        *_, task_id = heapq.heappop(ready)
        order.append(task_id)
        for child in dependents[task_id]:
            remaining[child] -= 1
            if remaining[child] == 0:
                heapq.heappush(ready, sort_key(child))

    if len(order) != len(tasks):
        raise ValueError("Task graph contains a cycle.")
    return order


def compute_parallel_groups(tasks: Sequence[GraphTask]) -> list[list[str]]:
    """Group tasks into waves. Wave N contains tasks whose dependencies all finished in
    earlier waves, so everything inside one wave could run at the same time.
    """
    order = compute_execution_order(tasks)  # also validates there is no cycle
    by_id = {t.id: t for t in tasks}
    level: dict[str, int] = {}
    for task_id in order:  # dependencies always come before their dependents in `order`
        task_deps = [d for d in by_id[task_id].depends_on if d in by_id]
        level[task_id] = 1 + max((level[d] for d in task_deps), default=-1)

    groups: list[list[str]] = [[] for _ in range(max(level.values()) + 1)]
    for task_id in order:  # keeps the priority ordering inside each wave
        groups[level[task_id]].append(task_id)
    return groups


def _unsortable_tasks(tasks: Sequence[GraphTask]) -> list[str]:
    """Ids of tasks that can never start because they are part of (or behind) a cycle."""
    try:
        compute_execution_order(tasks)
        return []
    except ValueError:
        pass
    # Re-run Kahn's algorithm quickly to find which tasks never became ready.
    known = {t.id for t in tasks}
    remaining = {t.id: {d for d in t.depends_on if d in known} for t in tasks}
    finished: set[str] = set()
    progress = True
    while progress:
        progress = False
        for task_id, task_deps in remaining.items():
            if task_id not in finished and task_deps <= finished:
                finished.add(task_id)
                progress = True
    return sorted(set(remaining) - finished)
