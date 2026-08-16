from app.api.agents import _execution_artifact_payloads
from app.runtime.hermes import HermesRunResult


def test_plain_output_keeps_legacy_result_filename() -> None:
    result = HermesRunResult(output="plain text", run_id="run-1", status="completed")

    assert _execution_artifact_payloads(result, None) == [
        ("result.txt", b"plain text", "text/plain; charset=utf-8")
    ]


def test_structured_report_creates_json_and_markdown_artifacts() -> None:
    raw = '{"status":"completed","report_markdown":"# Report"}'
    result = HermesRunResult(output=raw, run_id="run-2", status="completed")

    assert _execution_artifact_payloads(
        result,
        {"status": "completed", "report_markdown": "# Report"},
    ) == [
        ("result.json", raw.encode(), "application/json; charset=utf-8"),
        ("report.md", b"# Report", "text/markdown; charset=utf-8"),
    ]
