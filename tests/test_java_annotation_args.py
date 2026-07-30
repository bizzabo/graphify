"""Java annotation arguments, not just annotation names.

``@GetMapping("/orders/{id}")`` carries the route path that makes the
declaration an HTTP endpoint. Collecting only the annotation name makes it
indistinguishable from a bare marker, so the arguments are captured onto the
node's metadata alongside the name.
"""
from __future__ import annotations

from pathlib import Path

from graphify.extract import extract


def _annotations(tmp_path: Path, name: str, body: str) -> dict[str, list[dict]]:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    result = extract([path], cache_root=tmp_path / "graphify-out")
    return {
        node["label"]: node["metadata"]["annotations"]
        for node in result["nodes"]
        if node.get("metadata", {}).get("annotations")
    }


_CONTROLLER = """
@RestController
@RequestMapping("/api/orders")
public class OrderController {
  @GetMapping("/{id}")
  public String get() { return null; }

  @PostMapping(value = "/create", produces = "application/json")
  public String create() { return null; }

  @RequestMapping(path = Paths.ORDERS, method = RequestMethod.GET)
  public void legacy() {}

  @Deprecated
  public void old() {}
}
"""


def test_positional_argument_is_keyed_value(tmp_path: Path) -> None:
    annotations = _annotations(tmp_path, "OrderController.java", _CONTROLLER)

    assert annotations["OrderController"] == [
        {"name": "RestController", "args": []},
        {
            "name": "RequestMapping",
            "args": [{"name": "value", "value": "/api/orders", "kind": "string"}],
        },
    ]
    assert annotations[".get()"] == [
        {
            "name": "GetMapping",
            "args": [{"name": "value", "value": "/{id}", "kind": "string"}],
        }
    ]


def test_named_pairs_keep_their_own_names(tmp_path: Path) -> None:
    annotations = _annotations(tmp_path, "OrderController.java", _CONTROLLER)

    assert annotations[".create()"] == [
        {
            "name": "PostMapping",
            "args": [
                {"name": "value", "value": "/create", "kind": "string"},
                {"name": "produces", "value": "application/json", "kind": "string"},
            ],
        }
    ]


def test_constant_reference_is_tagged_reference(tmp_path: Path) -> None:
    annotations = _annotations(tmp_path, "OrderController.java", _CONTROLLER)

    assert annotations[".legacy()"] == [
        {
            "name": "RequestMapping",
            "args": [
                {"name": "path", "value": "Paths.ORDERS", "kind": "reference"},
                {"name": "method", "value": "RequestMethod.GET", "kind": "reference"},
            ],
        }
    ]


def test_marker_annotation_has_empty_args(tmp_path: Path) -> None:
    annotations = _annotations(tmp_path, "OrderController.java", _CONTROLLER)

    assert annotations[".old()"] == [{"name": "Deprecated", "args": []}]


def test_attribute_reference_edges_are_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "OrderController.java"
    path.write_text(_CONTROLLER, encoding="utf-8")
    result = extract([path], cache_root=tmp_path / "graphify-out")

    labels = {node["id"]: node["label"] for node in result["nodes"]}
    attribute_targets = {
        labels[edge["target"]]
        for edge in result["edges"]
        if edge.get("context") == "attribute"
    }
    assert {"RestController", "RequestMapping", "GetMapping", "PostMapping"} <= attribute_targets
