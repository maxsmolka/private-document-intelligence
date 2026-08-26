import ast
import re
from collections import defaultdict
from pathlib import Path

from pdi.core.config import EXECUTION_RESOURCE_LIMIT_NAMES
from pdi.core.models import Base
from pdi.documents.models import Document
from pdi.execution.specification import ResourceClass

PACKAGE_ROOT = Path(__file__).parents[1] / "pdi"


def module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("pdi", *parts))


def runtime_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()

    class Visitor(ast.NodeVisitor):
        type_checking = False

        def visit_If(self, node: ast.If) -> None:
            guarded = isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
            previous = self.type_checking
            self.type_checking = previous or guarded
            for child in node.body:
                self.visit(child)
            self.type_checking = previous
            for child in node.orelse:
                self.visit(child)

        def visit_Import(self, node: ast.Import) -> None:
            if not self.type_checking:
                imports.update(alias.name for alias in node.names if alias.name.startswith("pdi"))

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if not self.type_checking and node.module and node.module.startswith("pdi"):
                imports.add(node.module)

    Visitor().visit(tree)
    return imports


def package_graph() -> dict[str, set[str]]:
    paths = list(PACKAGE_ROOT.rglob("*.py"))
    modules = {module_name(path): path for path in paths}
    graph: dict[str, set[str]] = defaultdict(set)
    for module, path in modules.items():
        for imported in runtime_imports(path):
            target = imported
            while target not in modules and "." in target:
                target = target.rsplit(".", 1)[0]
            if target in modules and target != module:
                graph[module].add(target)
        graph.setdefault(module, set())
    return graph


def cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    found: list[list[str]] = []
    active: list[str] = []
    visited: set[str] = set()

    def visit(module: str) -> None:
        if module in active:
            cycle = active[active.index(module) :] + [module]
            if cycle not in found:
                found.append(cycle)
            return
        if module in visited:
            return
        active.append(module)
        for dependency in sorted(graph[module]):
            visit(dependency)
        active.pop()
        visited.add(module)

    for module in sorted(graph):
        visit(module)
    return found


def test_runtime_package_graph_has_no_cycles() -> None:
    assert cycles(package_graph()) == []


def test_core_does_not_depend_on_product_domains() -> None:
    for path in (PACKAGE_ROOT / "core").glob("*.py"):
        assert all(
            imported == "pdi.core" or imported.startswith("pdi.core.")
            for imported in runtime_imports(path)
        ), path


def test_model_modules_do_not_depend_on_transport_or_services() -> None:
    prohibited = (".router", ".schemas", ".service")
    for path in PACKAGE_ROOT.rglob("models.py"):
        assert not any(imported.endswith(prohibited) for imported in runtime_imports(path)), path


def test_shared_registry_owns_all_domain_tables() -> None:
    assert Document.metadata is Base.metadata
    assert {
        "documents",
        "document_extractions",
        "knowledge_proposals",
        "search_documents",
        "local_users",
    } <= set(Base.metadata.tables)


def test_execution_boundary_keeps_domain_and_executor_decoupled() -> None:
    for package in ("documents", "intelligence", "knowledge", "search"):
        for path in (PACKAGE_ROOT / package).glob("*.py"):
            assert "pdi.execution.executor" not in runtime_imports(path), path
            assert "pdi.ingestion.worker" not in runtime_imports(path), path
    executor_imports = runtime_imports(PACKAGE_ROOT / "execution" / "executor.py")
    assert not any(imported.startswith("pdi.documents") for imported in executor_imports)


def test_task_specification_has_no_backend_internals_or_compute_core_dependency() -> None:
    specification = (PACKAGE_ROOT / "execution" / "specification.py").read_text(encoding="utf-8")
    for forbidden in ("worker_id", "process_id", "thread_count", "docker", "compute_core"):
        assert forbidden not in specification.casefold()
    project = (PACKAGE_ROOT.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert "compute-core" not in project.casefold()
    assert "compute_core" not in project.casefold()


def test_job_state_mutations_are_centralized_in_queue_policy() -> None:
    mutation_files = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        if re.search(r"\bjob\.state\s*=(?!=)", path.read_text(encoding="utf-8")):
            mutation_files.append(path.relative_to(PACKAGE_ROOT).as_posix())
    assert mutation_files == ["ingestion/queue.py"]


def test_execution_resource_config_and_domain_vocabulary_cannot_drift() -> None:
    assert {item.value for item in ResourceClass} == EXECUTION_RESOURCE_LIMIT_NAMES
