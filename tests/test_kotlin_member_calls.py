"""Kotlin receiver-typed member-call resolution.

Kotlin service code is almost entirely member calls (``repo.save(dto)``), and the
receiver is usually a primary-constructor property — the Spring
constructor-injection pattern. A typed receiver must select the method owned by its
declared type; an unresolved, ambiguous, or shadowed receiver must stay unlinked
rather than creating a false call edge.
"""
from __future__ import annotations

from pathlib import Path

from graphify.extract import extract


def _calls(tmp_path: Path, files: dict[str, str]):
    paths = []
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        paths.append(path)
    result = extract(paths, cache_root=tmp_path / "graphify-out")
    calls = {
        (edge["source"], edge["target"])
        for edge in result["edges"]
        if edge.get("relation") == "calls"
    }
    return calls, result


def _find(result: dict, label: str, id_contains: str) -> str:
    return next(
        node["id"]
        for node in result["nodes"]
        if node.get("label") == label and id_contains in node["id"]
    )


def _edge(result: dict, source: str, target: str) -> dict:
    return next(
        edge for edge in result["edges"]
        if edge.get("relation") == "calls"
        and edge["source"] == source
        and edge["target"] == target
    )


_AMBIGUOUS_METHODS = {
    "Repos.kt": (
        "class OrderRepository {\n"
        "    fun save(value: String) {}\n"
        "}\n"
        "class AuditRepository {\n"
        "    fun save(value: String) {}\n"
        "}\n"
    ),
}


def test_constructor_injected_receiver_resolves_to_its_declared_type(tmp_path: Path):
    calls, result = _calls(tmp_path, {
        **_AMBIGUOUS_METHODS,
        "OrderServiceImpl.kt": (
            "class OrderServiceImpl(private val repo: OrderRepository) {\n"
            "    fun create() {\n"
            "        repo.save(\"x\")\n"
            "    }\n"
            "}\n"
        ),
    })

    create = _find(result, ".create()", "orderserviceimpl")
    order_save = _find(result, ".save()", "orderrepository")
    audit_save = _find(result, ".save()", "auditrepository")
    assert (create, order_save) in calls
    assert (create, audit_save) not in calls
    assert _edge(result, create, order_save)["confidence"] == "INFERRED"


def test_class_property_receiver_resolves_to_its_declared_type(tmp_path: Path):
    calls, result = _calls(tmp_path, {
        **_AMBIGUOUS_METHODS,
        "OrderServiceImpl.kt": (
            "class OrderServiceImpl {\n"
            "    private val repo: OrderRepository = OrderRepository()\n"
            "    fun create() {\n"
            "        this.repo.save(\"x\")\n"
            "    }\n"
            "}\n"
        ),
    })

    create = _find(result, ".create()", "orderserviceimpl")
    assert (create, _find(result, ".save()", "orderrepository")) in calls
    assert (create, _find(result, ".save()", "auditrepository")) not in calls


def test_typed_parameter_receiver_resolves(tmp_path: Path):
    calls, result = _calls(tmp_path, {
        **_AMBIGUOUS_METHODS,
        "OrderServiceImpl.kt": (
            "class OrderServiceImpl {\n"
            "    fun create(repo: AuditRepository) {\n"
            "        repo.save(\"x\")\n"
            "    }\n"
            "}\n"
        ),
    })

    create = _find(result, ".create()", "orderserviceimpl")
    assert (create, _find(result, ".save()", "auditrepository")) in calls
    assert (create, _find(result, ".save()", "orderrepository")) not in calls


def test_untyped_local_is_typed_from_its_constructor(tmp_path: Path):
    calls, result = _calls(tmp_path, {
        **_AMBIGUOUS_METHODS,
        "OrderServiceImpl.kt": (
            "class OrderServiceImpl {\n"
            "    fun create() {\n"
            "        val repo = AuditRepository()\n"
            "        repo.save(\"x\")\n"
            "    }\n"
            "}\n"
        ),
    })

    create = _find(result, ".create()", "orderserviceimpl")
    assert (create, _find(result, ".save()", "auditrepository")) in calls
    assert (create, _find(result, ".save()", "orderrepository")) not in calls


def test_explicit_type_receiver_is_exact(tmp_path: Path):
    calls, result = _calls(tmp_path, {
        "Repos.kt": (
            "object OrderRepository {\n"
            "    fun purge() {}\n"
            "}\n"
            "class AuditRepository {\n"
            "    fun purge() {}\n"
            "}\n"
        ),
        "Cleanup.kt": (
            "class Cleanup {\n"
            "    fun run() {\n"
            "        OrderRepository.purge()\n"
            "    }\n"
            "}\n"
        ),
    })

    run = _find(result, ".run()", "cleanup")
    order_purge = _find(result, ".purge()", "orderrepository")
    assert (run, order_purge) in calls
    assert (run, _find(result, ".purge()", "auditrepository")) not in calls
    assert _edge(result, run, order_purge)["confidence"] == "EXTRACTED"


def test_this_receiver_resolves_to_the_callers_own_type(tmp_path: Path):
    calls, result = _calls(tmp_path, {
        "Other.kt": (
            "class Other {\n"
            "    fun helper() {}\n"
            "}\n"
        ),
        "OrderServiceImpl.kt": (
            "class OrderServiceImpl {\n"
            "    fun helper() {}\n"
            "    fun create() {\n"
            "        this.helper()\n"
            "    }\n"
            "}\n"
        ),
    })

    create = _find(result, ".create()", "orderserviceimpl")
    assert (create, _find(result, ".helper()", "orderserviceimpl")) in calls
    assert (create, _find(result, ".helper()", "other")) not in calls


def test_ambiguous_receiver_type_emits_no_edge(tmp_path: Path):
    calls, result = _calls(tmp_path, {
        "a/Repo.kt": "class Repo {\n    fun save(value: String) {}\n}\n",
        "b/Repo.kt": "class Repo {\n    fun save(value: String) {}\n}\n",
        "OrderServiceImpl.kt": (
            "class OrderServiceImpl(private val repo: Repo) {\n"
            "    fun create() {\n"
            "        repo.save(\"x\")\n"
            "    }\n"
            "}\n"
        ),
    })

    create = _find(result, ".create()", "orderserviceimpl")
    assert not [target for source, target in calls
                if source == create and target.endswith("_save")]


def test_conflicting_bindings_for_one_name_emit_no_edge(tmp_path: Path):
    calls, result = _calls(tmp_path, {
        **_AMBIGUOUS_METHODS,
        "OrderServiceImpl.kt": (
            "class OrderServiceImpl {\n"
            "    fun create() {\n"
            "        val repo: OrderRepository = OrderRepository()\n"
            "        repo.save(\"x\")\n"
            "    }\n"
            "    fun audit() {\n"
            "        val repo: AuditRepository = AuditRepository()\n"
            "        repo.save(\"y\")\n"
            "    }\n"
            "}\n"
        ),
    })

    create = _find(result, ".create()", "orderserviceimpl")
    audit = _find(result, ".audit()", "orderserviceimpl")
    order_save = _find(result, ".save()", "orderrepository")
    audit_save = _find(result, ".save()", "auditrepository")
    for caller in (create, audit):
        assert (caller, order_save) not in calls
        assert (caller, audit_save) not in calls


def test_untypable_receiver_does_not_fall_back_to_a_name_match(tmp_path: Path):
    calls, result = _calls(tmp_path, {
        **_AMBIGUOUS_METHODS,
        "OrderServiceImpl.kt": (
            "class OrderServiceImpl {\n"
            "    fun create(repo: Any) {\n"
            "        repo.save(\"x\")\n"
            "    }\n"
            "}\n"
        ),
    })

    create = _find(result, ".create()", "orderserviceimpl")
    assert (create, _find(result, ".save()", "orderrepository")) not in calls
    assert (create, _find(result, ".save()", "auditrepository")) not in calls
