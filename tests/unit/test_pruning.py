import pytest
from models.types import GraphEdge, GraphNode
from pipeline.pruning import prune_graph


def _make_node(node_id: str, symbol: str, file: str = "f.py") -> GraphNode:
    return GraphNode(id=node_id, file=file, symbol=symbol, kind="function")


def _make_edge(src: str, tgt: str) -> GraphEdge:
    return GraphEdge(source=src, target=tgt, relation="calls", confidence="EXTRACTED")


def test_seed_nodes_always_included():
    nodes = {
        "a": _make_node("a", "validate_token"),
        "b": _make_node("b", "unrelated_thing"),
    }
    result = prune_graph(nodes, [], changed_symbols={"validate_token"}, god_nodes=set())
    assert "a" in result


def test_2_hop_neighbours_included():
    nodes = {
        "a": _make_node("a", "validate_token"),
        "b": _make_node("b", "hop1"),
        "c": _make_node("c", "hop2"),
        "d": _make_node("d", "hop3"),
    }
    edges = [_make_edge("a", "b"), _make_edge("b", "c"), _make_edge("c", "d")]
    result = prune_graph(nodes, edges, changed_symbols={"validate_token"}, god_nodes=set())
    assert "b" in result
    assert "c" in result
    assert "d" not in result   # 3 hops away


def test_god_nodes_excluded():
    nodes = {
        "a": _make_node("a", "validate_token"),
        "god": _make_node("god", "hop1"),
    }
    edges = [_make_edge("a", "god")]
    result = prune_graph(
        nodes, edges, changed_symbols={"validate_token"}, god_nodes={"god"}
    )
    assert "god" not in result


def test_hard_cap_drops_lowest_degree_nodes():
    nodes = {f"n{i}": _make_node(f"n{i}", "validate_token") for i in range(10)}
    edges = [_make_edge("n0", f"n{i}") for i in range(1, 6)]
    edges += [_make_edge(f"n{i}", f"x{i}") for i in range(6, 10)]
    all_nodes = {**nodes, **{f"x{i}": _make_node(f"x{i}", "other") for i in range(6, 10)}}
    result = prune_graph(
        all_nodes, edges, changed_symbols={"validate_token"},
        god_nodes=set(), max_nodes=3,
    )
    assert len(result) <= 3


def test_camel_case_token_matching():
    nodes = {
        "a": _make_node("a", "ValidateToken"),
        "b": _make_node("b", "unrelated"),
    }
    # "validate_token" tokens = {"validate", "token"}; "ValidateToken" tokens = {"validate", "token"}
    result = prune_graph(nodes, [], changed_symbols={"validate_token"}, god_nodes=set())
    assert "a" in result
