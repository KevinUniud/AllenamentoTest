from __future__ import annotations

import ast
from pathlib import Path

from testlogica import generator
from testlogica.questions import equivalence, logical_consequence, truth_value


def test_generator_keeps_public_builder_compatibility() -> None:
    assert generator.build_exercise is equivalence.build_exercise
    assert generator.build_ex_depth is equivalence.build_ex_depth
    assert generator.build_tvq is truth_value.build_tvq
    assert generator.build_logical_consequence_question is logical_consequence.build_logical_consequence_question


def test_lazy_generator_dependencies_exist() -> None:
    questions_dir = Path(__file__).parents[1] / "testlogica" / "questions"
    for module_path in questions_dir.glob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        delegated_names = [
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_delegate"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ]
        missing = [name for name in delegated_names if not hasattr(generator, name)]
        assert not missing, f"{module_path.name}: dipendenze delegate mancanti: {missing}"
