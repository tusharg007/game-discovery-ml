from __future__ import annotations

import math
from collections.abc import Iterable


def ranking_metrics(
    recommendations: Iterable[str], relevant_items: set[str], ks: tuple[int, ...] = (5, 10, 20)
) -> dict[str, float]:
    if not relevant_items:
        raise ValueError("Ranking metrics require at least one relevant item")
    if any(k <= 0 for k in ks):
        raise ValueError("Every K must be positive")
    ranked = list(recommendations)
    if len(ranked) != len(set(ranked)):
        raise ValueError("Recommendations must be unique")
    result: dict[str, float] = {}
    for k in ks:
        top = ranked[:k]
        hits = sum(item in relevant_items for item in top)
        dcg = sum(
            1.0 / math.log2(rank + 1)
            for rank, item in enumerate(top, start=1)
            if item in relevant_items
        )
        ideal_hits = min(len(relevant_items), k)
        idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
        result[f"recall@{k}"] = hits / len(relevant_items)
        result[f"ndcg@{k}"] = dcg / idcg
        result[f"hit_rate@{k}"] = float(hits > 0)
    return result


def top_unseen_items(ranking: Iterable[str], seen_items: set[str], k: int) -> list[str]:
    if k < 1:
        raise ValueError("K must be at least one")
    output: list[str] = []
    included: set[str] = set()
    for item_id in ranking:
        if item_id in seen_items or item_id in included:
            continue
        output.append(item_id)
        included.add(item_id)
        if len(output) == k:
            break
    return output
