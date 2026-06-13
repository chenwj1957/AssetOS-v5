from __future__ import annotations

import json

from src.llm.adapters.codex import _parse_agentic_result


def _line(item: dict) -> str:
    return json.dumps({"type": "item.completed", "item": item})


def test_parse_agentic_result_builds_timeline_from_jsonl() -> None:
    stdout = "\n".join(
        [
            _line({"type": "web_search", "query": "NSW bond lodgement rates"}),
            _line({
                "type": "command_execution",
                "command": "curl https://example.com/bonds",
                "aggregated_output": "<html>bond info</html>",
            }),
            _line({
                "type": "agent_message",
                "text": "Bond is capped at 4 weeks rent. Source: https://example.com/bonds",
            }),
            "",  # trailing blank line
        ]
    )

    result = _parse_agentic_result(stdout)

    assert result.text == "Bond is capped at 4 weeks rent. Source: https://example.com/bonds"
    assert [entry["kind"] for entry in result.timeline] == ["search", "navigation", "message"]
    assert result.timeline[0]["query"] == "NSW bond lodgement rates"
    assert result.timeline[1]["command"].startswith("curl")
    assert result.timeline[2]["citations"] == ["https://example.com/bonds"]


def test_parse_agentic_result_falls_back_for_plain_text() -> None:
    result = _parse_agentic_result("Just a plain text reply, no JSON here.")

    assert result.text == "Just a plain text reply, no JSON here."
    assert result.timeline == []


def test_parse_agentic_result_marks_non_url_commands_as_command() -> None:
    stdout = _line({"type": "command_execution", "command": "ls -la", "aggregated_output": "file1\nfile2"})

    result = _parse_agentic_result(stdout)

    assert result.timeline == [{"kind": "command", "command": "ls -la", "output": "file1\nfile2"}]
