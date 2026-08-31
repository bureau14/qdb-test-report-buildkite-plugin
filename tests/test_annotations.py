from annotations import build_annotation_body, get_annotation_style, get_job_annotation_style


def test_build_annotation_body_multi_target():
    summary = {
        "logical_tests": 100,
        "targets": 2,
        "resolved_platforms": ["linux", "macos"],
        "status_counts": {"FAILED": 2, "SKIPPED": 5},
        "logical_status_counts": {"FAILED": 1, "SUCCESSFUL": 99},
    }
    body = build_annotation_body("Unit tests", summary, "http://example.com/report.html")
    assert "## Unit tests" in body
    assert "100 tests, 2 targets, 99 passed, 1 failed, 0 errored, 0 skipped" in body
    assert (
        '<a href="http://example.com/report.html" target="_blank" rel="noopener noreferrer">Open full report</a>'
        in body
    )


def test_build_annotation_body_resolved_targets():
    summary = {
        "logical_tests": 100,
        "targets": 1,
        "resolved_platforms": ["linux"],
        "status_counts": {"SUCCESSFUL": 100},
    }
    body = build_annotation_body("Resolved Tests", summary, "http://example.com/report.html")
    # Should show "100 tests" instead of "1 target" because single-target reports hide the target count.
    assert "100 tests, 100 passed" in body
    assert "1 target" not in body


def test_build_annotation_body_falls_back_to_execution_counts_for_old_summaries():
    summary = {
        "logical_tests": 10,
        "targets": 2,
        "resolved_platforms": ["linux", "macos"],
        "status_counts": {"SUCCESSFUL": 18, "FAILED": 2},
    }
    body = build_annotation_body("Old summary", summary, "http://example.com/report.html")
    assert "10 tests, 2 targets, 18 passed, 2 failed, 0 errored, 0 skipped" in body


def test_build_annotation_body_uses_logical_counts_when_available():
    summary = {
        "logical_tests": 10,
        "targets": 2,
        "resolved_platforms": ["linux", "macos"],
        "status_counts": {"SUCCESSFUL": 18, "FAILED": 2},
        "logical_status_counts": {"SUCCESSFUL": 9, "FAILED": 1},
    }
    body = build_annotation_body("Logical summary", summary, "http://example.com/report.html")
    assert "10 tests, 2 targets, 9 passed, 1 failed, 0 errored, 0 skipped" in body


def test_build_annotation_body_single_target():
    summary = {
        "logical_tests": 50,
        "targets": 1,
        "status_counts": {"FAILED": 0, "SKIPPED": 0},
    }
    body = build_annotation_body("Quick report", summary, "http://example.com/report.html")
    assert "## Quick report" in body
    assert "50 tests, 0 passed, 0 failed, 0 errored, 0 skipped" in body


def test_build_annotation_body_includes_warnings():
    summary = {
        "logical_tests": 50,
        "root_status": "SUCCESSFUL",
        "status_counts": {"SUCCESSFUL": 50},
        "warnings": [
            "A report warning was recorded.",
        ],
    }
    body = build_annotation_body("Full report", summary, "http://example.com/report.html")
    assert "⚠️ Warnings" in body
    assert "A report warning was recorded." in body


def test_build_annotation_body_lists_malformed_junit_xml_files():
    summary = {
        "logical_tests": 1,
        "status_counts": {"SUCCESSFUL": 1},
        "malformed_junit_xml": [
            {
                "file": "reports/linux/broken.xml",
                "platform": "linux",
                "error": "no element found: line 1, column 11",
            }
        ],
    }

    body = build_annotation_body(
        "Job report", summary, "http://example.com/report.html", scope="job"
    )

    assert "Malformed JUnit XML" in body
    assert "reports/linux/broken.xml (linux): no element found: line 1, column 11" in body
    assert get_job_annotation_style(summary) == "error"


def test_build_annotation_body_links_uploaded_malformed_junit_xml():
    summary = {
        "logical_tests": 1,
        "status_counts": {"SUCCESSFUL": 1},
        "malformed_junit_xml": [
            {
                "file": "reports/linux/broken.xml",
                "platform": "linux",
                "error": "no element found: line 1, column 11",
                "url": "https://reports.example.com/xml/reports/linux/broken.xml",
            }
        ],
    }

    body = build_annotation_body("Job report", summary, None, scope="job")

    assert (
        '<a href="https://reports.example.com/xml/reports/linux/broken.xml" '
        'target="_blank" rel="noopener noreferrer">reports/linux/broken.xml (linux)</a>: '
        "no element found: line 1, column 11"
    ) in body


def test_build_annotation_body_explains_empty_global_targets():
    summary = {
        "logical_tests": 135,
        "root_status": "SUCCESSFUL",
        "targets": 4,
        "platforms": ["linux", "macos", "windows", "freebsd-haswell"],
        "resolved_platforms": ["linux", "macos", "windows"],
        "status_counts": {"SUCCESSFUL": 134, "SKIPPED": 1},
    }
    body = build_annotation_body("Full report", summary, "http://example.com/report.html")
    assert "⚠️ Warnings" in body
    assert "No test executions for 1 configured target: freebsd-haswell." in body


def test_build_annotation_body_explains_empty_job_report_once():
    summary = {
        "logical_tests": 0,
        "root_status": "SUCCESSFUL",
        "targets": 1,
        "resolved_platforms": [],
        "status_counts": {},
    }
    body = build_annotation_body(
        "Job report", summary, "http://example.com/report.html", scope="job"
    )
    assert "⚠️ Warnings" in body
    assert "This job report is empty: 0 tests produced no test executions." in body
    assert "configured targets produced no test executions" not in body


def test_build_annotation_body_explains_job_report_with_no_passing_tests():
    summary = {
        "logical_tests": 5,
        "root_status": "SUCCESSFUL",
        "status_counts": {"SKIPPED": 5},
    }
    body = build_annotation_body(
        "Job report", summary, "http://example.com/report.html", scope="job"
    )
    assert "⚠️ Warnings" in body
    assert "This job report has 0 passing tests." in body


def test_get_annotation_style_error():
    assert get_annotation_style({"status_counts": {"FAILED": 1}}) == "error"
    assert get_annotation_style({"root_status": "FAILED"}) == "error"


def test_get_annotation_style_success():
    assert (
        get_annotation_style(
            {
                "root_status": "SUCCESSFUL",
                "status_counts": {"SUCCESSFUL": 10, "SKIPPED": 0},
            }
        )
        == "success"
    )


def test_get_annotation_style_warning_when_report_has_warnings():
    assert (
        get_annotation_style(
            {
                "root_status": "SUCCESSFUL",
                "status_counts": {"SUCCESSFUL": 10},
                "warnings": ["A report warning was recorded."],
            }
        )
        == "warning"
    )


def test_get_annotation_style_warning_when_a_target_has_no_executions():
    assert (
        get_annotation_style(
            {
                "root_status": "SUCCESSFUL",
                "targets": 2,
                "resolved_platforms": ["linux"],
                "status_counts": {"SUCCESSFUL": 10},
            }
        )
        == "warning"
    )


def test_get_annotation_style_error_takes_precedence_over_warnings():
    assert (
        get_annotation_style(
            {
                "root_status": "FAILED",
                "targets": 2,
                "resolved_platforms": ["linux"],
                "status_counts": {"FAILED": 1},
                "warnings": ["A report warning was recorded."],
            }
        )
        == "error"
    )


def test_get_annotation_style_skipped_success():
    # Skips are treated as success for non-job annotations.
    summary = {
        "root_status": "SUCCESSFUL",
        "status_counts": {"SUCCESSFUL": 10, "SKIPPED": 1},
    }
    assert get_annotation_style(summary) == "success"
    summary_only_skipped = {
        "root_status": "SUCCESSFUL",
        "status_counts": {"SKIPPED": 5},
    }
    assert get_annotation_style(summary_only_skipped) == "success"


def test_get_job_annotation_style_warns_when_no_tests_passed():
    assert (
        get_job_annotation_style(
            {
                "root_status": "SUCCESSFUL",
                "logical_tests": 5,
                "status_counts": {"SKIPPED": 5},
            }
        )
        == "warning"
    )


def test_get_job_annotation_style_warns_when_report_is_empty():
    assert (
        get_job_annotation_style(
            {
                "root_status": "SUCCESSFUL",
                "logical_tests": 0,
                "status_counts": {},
            }
        )
        == "warning"
    )


def test_get_job_annotation_style_keeps_error_precedence():
    assert (
        get_job_annotation_style(
            {
                "root_status": "FAILED",
                "logical_tests": 1,
                "status_counts": {"FAILED": 1},
            }
        )
        == "error"
    )
