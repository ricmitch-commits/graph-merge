from models.types import Change, GraphEdge, GraphNode, SemanticDiff

_RATIONALE_KEYS = {"why", "hack", "note", "fixme"}


def compute_semantic_diff(
    before_nodes: dict[str, GraphNode],
    after_nodes: dict[str, GraphNode],
    before_edges: list[GraphEdge],
    after_edges: list[GraphEdge],
    commit_message: str = "",
) -> SemanticDiff:
    id_map = _build_fallback_id_map(before_nodes, after_nodes)
    remapped_before = {id_map.get(k, k): v for k, v in before_nodes.items()}

    before_ids = set(remapped_before)
    after_ids = set(after_nodes)
    changes: list[Change] = []

    for node_id in after_ids - before_ids:
        node = after_nodes[node_id]
        changes.append(Change(
            type="node_added", node_id=node_id, file=node.file,
            symbol=node.symbol, kind=node.kind,
            after={"calls": node.calls, "imports": node.imports,
                   "properties": node.properties},
        ))

    for node_id in before_ids - after_ids:
        node = remapped_before[node_id]
        changes.append(Change(
            type="node_removed", node_id=node_id, file=node.file,
            symbol=node.symbol, kind=node.kind,
            before={"calls": node.calls, "imports": node.imports,
                    "properties": node.properties},
        ))

    for node_id in before_ids & after_ids:
        b = remapped_before[node_id]
        a = after_nodes[node_id]
        if b.calls != a.calls or b.imports != a.imports or b.properties != a.properties:
            changes.append(Change(
                type="node_modified", node_id=node_id, file=a.file,
                symbol=a.symbol, kind=a.kind,
                before={"calls": b.calls, "imports": b.imports,
                        "properties": b.properties},
                after={"calls": a.calls, "imports": a.imports,
                       "properties": a.properties},
                rationale=_extract_rationale(a.properties),
            ))

    before_triples = {(e.source, e.target, e.relation) for e in before_edges}
    after_triples = {(e.source, e.target, e.relation) for e in after_edges}

    edge_by_triple = {(e.source, e.target, e.relation): e for e in after_edges}
    for triple in after_triples - before_triples:
        changes.append(Change(type="edge_added", edge=edge_by_triple[triple]))

    edge_by_triple_before = {(e.source, e.target, e.relation): e for e in before_edges}
    for triple in before_triples - after_triples:
        changes.append(Change(type="edge_removed", edge=edge_by_triple_before[triple]))

    return SemanticDiff(commit_message=commit_message, changes=changes)


def _extract_rationale(properties: dict) -> str | None:
    for key, value in properties.items():
        if key.lower() in _RATIONALE_KEYS:
            return str(value)
    return None


def _build_fallback_id_map(
    before_nodes: dict[str, GraphNode],
    after_nodes: dict[str, GraphNode],
) -> dict[str, str]:
    """Map before IDs → after IDs when IDs are unstable. Match on (file, symbol, kind)."""
    after_by_tuple = {
        (n.file, n.symbol, n.kind): nid for nid, n in after_nodes.items()
    }
    mapping: dict[str, str] = {}
    for before_id, node in before_nodes.items():
        after_id = after_by_tuple.get((node.file, node.symbol, node.kind))
        if after_id and after_id != before_id:
            mapping[before_id] = after_id
    return mapping
