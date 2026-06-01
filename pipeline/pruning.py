import re
from pathlib import Path

from models.types import GraphEdge, GraphNode


def prune_graph(
    nodes: dict[str, GraphNode],
    edges: list[GraphEdge],
    changed_symbols: set[str],
    god_nodes: set[str],
    max_nodes: int = 500,
) -> dict[str, GraphNode]:
    adj: dict[str, set[str]] = {nid: set() for nid in nodes}
    for edge in edges:
        if edge.source in adj:
            adj[edge.source].add(edge.target)
        if edge.target in adj:
            adj[edge.target].add(edge.source)

    changed_tokens: set[str] = set()
    for sym in changed_symbols:
        changed_tokens.update(_tokenize(sym))

    seeds = {
        nid for nid, node in nodes.items()
        if _tokenize(node.symbol) & changed_tokens
    }

    within_2_hops = _bfs(seeds, adj, max_hops=2)
    kept = {nid: nodes[nid] for nid in within_2_hops if nid not in god_nodes and nid in nodes}

    if len(kept) > max_nodes:
        degrees = {nid: len(adj.get(nid, set())) for nid in kept}
        top = sorted(kept, key=lambda n: degrees[n], reverse=True)[:max_nodes]
        kept = {nid: kept[nid] for nid in top}

    return kept


def load_god_nodes(report_path: Path) -> set[str]:
    if not report_path.exists():
        return set()
    god_nodes: set[str] = set()
    for line in report_path.read_text().splitlines():
        if "god node" in line.lower() or "highest degree" in line.lower():
            match = re.search(r"`([^`]+)`", line)
            if match:
                god_nodes.add(match.group(1))
    return god_nodes


def _tokenize(symbol: str) -> set[str]:
    tokens = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", symbol)
    return {t.lower() for t in tokens if len(t) > 1}


def _bfs(seeds: set[str], adj: dict[str, set[str]], max_hops: int) -> set[str]:
    visited = set(seeds)
    frontier = set(seeds)
    for _ in range(max_hops):
        next_frontier = set()
        for node in frontier:
            for neighbour in adj.get(node, set()):
                if neighbour not in visited:
                    visited.add(neighbour)
                    next_frontier.add(neighbour)
        frontier = next_frontier
    return visited
