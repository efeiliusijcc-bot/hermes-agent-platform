from app.api.agents import _execution_artifact_payloads
from app.runtime.hermes import HermesRunResult, RuntimeArtifact


def test_plain_output_keeps_legacy_result_filename() -> None:
    result = HermesRunResult(output="plain text", run_id="run-1", status="completed")

    assert _execution_artifact_payloads(result, None) == [
        ("result.txt", b"plain text", "text/plain; charset=utf-8", "text", "platform")
    ]


def test_structured_report_creates_json_and_markdown_artifacts() -> None:
    raw = 'Model preamble\n{"status":"completed","report_markdown":"# Report"}'
    result = HermesRunResult(output=raw, run_id="run-2", status="completed")
    parsed = {"status": "completed", "report_markdown": "# Report"}

    assert _execution_artifact_payloads(
        result,
        parsed,
    ) == [
        (
            "result.json",
            b'{\n  "status": "completed",\n  "report_markdown": "# Report"\n}',
            "application/json; charset=utf-8",
            "json",
            "platform",
        ),
        ("report.md", b"# Report", "text/markdown; charset=utf-8", "markdown", "platform"),
    ]


def test_runtime_artifacts_keep_type_and_runtime_provenance() -> None:
    result = HermesRunResult(
        output="done",
        run_id="run-3",
        status="completed",
        artifacts=(
            RuntimeArtifact(
                filename="changes.patch",
                content=b"diff --git a/a b/a",
                content_type="text/x-diff; charset=utf-8",
                artifact_type="code_patch",
            ),
        ),
    )

    assert _execution_artifact_payloads(result, None, runtime_source="deepseek")[-1] == (
        "changes.patch",
        b"diff --git a/a b/a",
        "text/x-diff; charset=utf-8",
        "code_patch",
        "deepseek",
    )
