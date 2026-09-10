import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
WEB = BACKEND / "web"
INTERACTIVE_SOURCE = (WEB / "interactive_apps.py").read_text(encoding="utf-8")
TUTOR_SOURCE = (WEB / "ai_tutor.py").read_text(encoding="utf-8")

ALLOWED_PROMPTS = {
    "AI_TUTOR_SYSTEM_PROMPT",
    "INTERACTIVE_TASK_RULES",
    "INTERACTIVE_ANSWER_KEY_RULES",
    "DIGITIZATION_BOOKS_RULES",
}


def _prompt_constants() -> set[str]:
    names: set[str] = set()
    for path in BACKEND.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id.endswith(("_PROMPT", "_RULES")):
                    names.add(target.id)
    return names


def test_only_four_internal_prompt_constants_exist() -> None:
    assert _prompt_constants() == ALLOWED_PROMPTS


def test_old_prompt_tree_and_tutor_policy_are_removed() -> None:
    assert not (WEB / "prompts").exists()
    assert not (WEB / "tutor_policy.py").exists()
    assert (WEB / "prompts.py").is_file()


def test_interactive_generation_uses_only_canvas_prompt_and_explicit_inputs() -> None:
    start = INTERACTIVE_SOURCE.index("async def _generate(")
    end = INTERACTIVE_SOURCE.index("async def generate_teacher_answer_key", start)
    generate_source = INTERACTIVE_SOURCE[start:end]

    assert '"role": "system", "content": INTERACTIVE_TASK_RULES' in generate_source
    assert "AI_TUTOR_SYSTEM_PROMPT" not in generate_source
    assert "INTERACTIVE_ANSWER_KEY_RULES" not in generate_source
    assert "database_context" not in generate_source
    assert "web_context" not in generate_source
    assert "BOOK MODE DATA" in generate_source
    assert "ATTACHED FILE DATA" in generate_source
    assert '"type": "image_url"' in generate_source


def test_interactive_request_skips_supplemental_database_and_web_context() -> None:
    branch = TUTOR_SOURCE.index("if not interactive_requested:")
    database_lookup = TUTOR_SOURCE.index("educational_bundle = await build_educational_context", branch)
    interactive_call = TUTOR_SOURCE.index("interactive_app = await maybe_handle_chat_request")

    assert branch < database_lookup < interactive_call
    call_source = TUTOR_SOURCE[interactive_call:TUTOR_SOURCE.index(")\n    except", interactive_call)]
    assert "context=interactive_book_context" in call_source
    assert "attachment_text=interactive_attachment_text" in call_source
    assert "image_urls=current_image_urls" in call_source
    assert "database_context=" not in call_source
    assert "web_context=" not in call_source
