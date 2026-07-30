"""Kotlin annotation collection.

Kotlin had no annotation collector at all: ``_kotlin_extra_walk`` handled only
``enum_entry``, so a Spring service yielded no annotation data of any kind.
Collecting them has one Kotlin-specific wrinkle — a class that declares a
primary constructor does not own its annotations. tree-sitter-kotlin parses
them as a *preceding sibling* ``annotated_expression`` chain and gives the
``class_declaration`` no ``modifiers`` child, which is the shape almost every
constructor-injected Spring bean has.
"""
from __future__ import annotations

from pathlib import Path

from graphify.extract import extract


def _extract(tmp_path: Path, files: dict[str, str]) -> dict:
    paths = []
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        paths.append(path)
    return extract(paths, cache_root=tmp_path / "graphify-out")


def _annotations(result: dict) -> dict[str, list[dict]]:
    return {
        node["label"]: node["metadata"]["annotations"]
        for node in result["nodes"]
        if node.get("metadata", {}).get("annotations")
    }


_PRIMARY_CONSTRUCTOR = """
@RestController
@RequestMapping("/api/registration")
class RegistrationController(private val service: RegistrationService) {

    @GetMapping("/{id}")
    fun get(@PathVariable id: Long): RegistrationDTO = service.findById(id)

    @PostMapping(value = ["/create"], produces = ["application/json"])
    fun create(@RequestBody dto: RegistrationDTO): RegistrationDTO = service.create(dto)
}
"""

_NO_CONSTRUCTOR = """
@RestController
@RequestMapping("/api/plain")
class PlainController {
    @RequestMapping(value = ["/x"], method = [RequestMethod.GET])
    fun x() {}

    @GetMapping
    fun bare() {}
}
"""


def test_class_with_primary_constructor_reads_the_sibling_chain(tmp_path: Path) -> None:
    result = _extract(tmp_path, {"RegistrationController.kt": _PRIMARY_CONSTRUCTOR})

    assert _annotations(result)["RegistrationController"] == [
        {"name": "RestController", "args": []},
        {
            "name": "RequestMapping",
            "args": [{"name": "value", "value": "/api/registration", "kind": "string"}],
        },
    ]


def test_class_without_primary_constructor_reads_modifiers(tmp_path: Path) -> None:
    result = _extract(tmp_path, {"PlainController.kt": _NO_CONSTRUCTOR})

    assert _annotations(result)["PlainController"] == [
        {"name": "RestController", "args": []},
        {
            "name": "RequestMapping",
            "args": [{"name": "value", "value": "/api/plain", "kind": "string"}],
        },
    ]


def test_method_route_arguments_are_captured(tmp_path: Path) -> None:
    annotations = _annotations(
        _extract(tmp_path, {"RegistrationController.kt": _PRIMARY_CONSTRUCTOR})
    )

    assert annotations[".get()"] == [
        {
            "name": "GetMapping",
            "args": [{"name": "value", "value": "/{id}", "kind": "string"}],
        }
    ]
    assert annotations[".create()"] == [
        {
            "name": "PostMapping",
            "args": [
                {"name": "value", "value": ["/create"], "kind": "array"},
                {"name": "produces", "value": ["application/json"], "kind": "array"},
            ],
        }
    ]


def test_array_arguments_and_bare_annotation(tmp_path: Path) -> None:
    annotations = _annotations(_extract(tmp_path, {"PlainController.kt": _NO_CONSTRUCTOR}))

    assert annotations[".x()"] == [
        {
            "name": "RequestMapping",
            "args": [
                {"name": "value", "value": ["/x"], "kind": "array"},
                {"name": "method", "value": ["RequestMethod.GET"], "kind": "array"},
            ],
        }
    ]
    assert annotations[".bare()"] == [{"name": "GetMapping", "args": []}]


def test_table_annotation_and_const_value(tmp_path: Path) -> None:
    result = _extract(
        tmp_path,
        {
            "Registration.kt": """
@Table(TableNames.REGISTRATION)
data class Registration(val id: Long)

object TableNames {
    const val REGISTRATION = "registration"
    val derived = compute()
}
"""
        },
    )

    assert _annotations(result)["Registration"] == [
        {
            "name": "Table",
            "args": [
                {"name": "value", "value": "TableNames.REGISTRATION", "kind": "reference"}
            ],
        }
    ]

    const_values = {
        node["label"]: node["metadata"]["const_value"]
        for node in result["nodes"]
        if "const_value" in node.get("metadata", {})
    }
    assert const_values == {"REGISTRATION": "registration"}


def test_kotlin_emits_attribute_reference_edges(tmp_path: Path) -> None:
    result = _extract(tmp_path, {"RegistrationController.kt": _PRIMARY_CONSTRUCTOR})

    labels = {node["id"]: node["label"] for node in result["nodes"]}
    attribute_targets = {
        labels[edge["target"]]
        for edge in result["edges"]
        if edge.get("context") == "attribute"
    }
    assert {"RestController", "RequestMapping", "GetMapping", "PostMapping"} <= attribute_targets


def test_unrelated_annotated_expression_is_not_attributed_to_the_class(
    tmp_path: Path,
) -> None:
    result = _extract(
        tmp_path,
        {
            "Mixed.kt": """
val warmup = @Suppress("unused") compute()

class Untouched(private val dep: Dep)
"""
        },
    )

    assert "Untouched" not in _annotations(result)
