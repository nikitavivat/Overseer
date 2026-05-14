"""Graph definition and validation."""

from __future__ import annotations

import pytest

from overseer import Function, Process


def _noop():
    return None


def test_add_node_assigns_start_node():
    p = Process("p")
    p.add_node("a", Function(_noop))
    assert p.start_node == "a"


def test_explicit_start_overrides_implicit():
    p = Process("p")
    p.add_node("a", Function(_noop))
    p.add_node("b", Function(_noop), start=True)
    assert p.start_node == "b"


def test_duplicate_node_rejected():
    p = Process("p")
    p.add_node("a", Function(_noop))
    with pytest.raises(ValueError, match="already defined"):
        p.add_node("a", Function(_noop))


def test_reserved_terminal_name_rejected():
    p = Process("p")
    with pytest.raises(ValueError, match="reserved"):
        p.add_node("end", Function(_noop))


def test_non_node_non_callable_rejected():
    p = Process("p")
    with pytest.raises(TypeError, match="Node or callable"):
        p.add_node("a", "not a node")  # type: ignore[arg-type]


def test_connect_unknown_source():
    p = Process("p")
    p.add_node("a", Function(_noop))
    with pytest.raises(ValueError, match="Unknown source"):
        p.connect("nope", "a")


def test_connect_terminal_target_is_ok():
    p = Process("p")
    p.add_node("a", Function(_noop))
    p.connect("a", "end")
    assert p.validate().ok


def test_validation_flags_unreachable_node():
    p = Process("p")
    p.add_node("a", Function(_noop))
    p.add_node("b", Function(_noop))  # never connected
    p.connect("a", "end")
    warnings = " ".join(p.validate().warnings)
    assert "unreachable" in warnings


def test_topology_serializes_for_ui():
    p = Process("p")
    p.add_node("a", Function(_noop))
    p.connect("a", "end")
    topo = p.topology()
    assert topo["name"] == "p"
    assert any(n["id"] == "end" for n in topo["nodes"])
    assert any(e["target"] == "end" for e in topo["edges"])
