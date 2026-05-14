#!/usr/bin/env python3
"""Serialize the neutral JUnit report model into the report HTML UI data contract."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set

from junit_report_model import (
    LogicalTest,
    Report,
    TestSuite,
    TestcaseExecution,
    aggregate_status,
)

STATUS_SORT = {"ERRORED": 0, "FAILED": 1, "ABORTED": 2, "SKIPPED": 3, "SUCCESSFUL": 4}


def duration_millis(seconds: float) -> int:
    return int(round(max(seconds, 0.0) * 1000))


def labels_section(labels: List[str]) -> Dict[str, Any]:
    return {"title": "Tags", "blocks": [{"type": "labels", "content": sorted(labels)}]}


def kvp_section(title: str, content: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": title,
        "blocks": [{"type": "kvp", "content": {k: str(v) for k, v in content.items()}}],
    }


def reason_section(reason: str) -> Dict[str, Any]:
    return {"title": "Reason", "blocks": [{"type": "p", "content": reason}]}


def output_section(output: str, generated_at: str) -> Dict[str, Any]:
    return {
        "title": "Attachments",
        "blocks": [
            {
                "type": "sub",
                "content": [
                    {
                        "title": "Standard error",
                        "metaInfo": generated_at,
                        "blocks": [{"type": "pre", "content": output}],
                    }
                ],
            }
        ],
    }


class UiDataBuilder:
    def __init__(self) -> None:
        self._next_id = 1
        self.test_nodes: List[Dict[str, Any]] = []
        self.children: "OrderedDict[str, Dict[str, List[str]]]" = OrderedDict()

    def next_id(self) -> str:
        value = str(self._next_id)
        self._next_id += 1
        return value

    def node(
        self,
        name: str,
        duration_seconds_value: float,
        sections: List[Dict[str, Optional[Any]]] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "id": self.next_id(),
            "name": name,
            "durationMillis": duration_millis(duration_seconds_value),
            "sections": sections or [],
        }
        # Match the report renderer's behavior for structural containers: omit status entirely.
        if status is not None:
            result["status"] = status
        self.test_nodes.append(result)
        return result

    def add_children(self, parent_id: str, child_ids: List[str]) -> None:
        self.children[parent_id] = {"ids": child_ids, "childStatuses": []}

    def finalize_child_statuses(self) -> None:
        node_by_id = {node["id"]: node for node in self.test_nodes}

        def statuses_for(node_id: str) -> Set[str]:
            if node_id in self.children:
                statuses: Set[str] = set()
                for child_id in self.children[node_id]["ids"]:
                    statuses.update(statuses_for(child_id))
                self.children[node_id]["childStatuses"] = sorted(
                    statuses, key=lambda s: STATUS_SORT.get(s, 99)
                )
                return statuses
            status = node_by_id[node_id].get("status")
            return {status} if status else set()

        for parent_id in list(self.children):
            statuses_for(parent_id)


def logical_duration(logical: LogicalTest) -> float:
    return sum(execution.duration_seconds for execution in logical.executions.values())


def suite_duration(suite: TestSuite) -> float:
    return sum(logical_duration(logical) for logical in suite.logical_tests.values())


def logical_sections(logical: LogicalTest) -> List[Dict[str, Any]]:
    labels = [
        f"logical-test-id:{logical.logical_id}",
        f"testsuite:{logical.suite_name}",
        f"classname:{logical.classname}" if logical.classname else "classname:",
        f"test-name:{logical.name}",
    ]
    for execution in logical.executions.values():
        if execution.status == "FAILED":
            labels.append(f"failed-platform:{execution.platform}")
        elif execution.status == "ERRORED":
            labels.append(f"errored-platform:{execution.platform}")
        elif execution.status == "SKIPPED":
            labels.append(f"skipped-platform:{execution.platform}")
    return [labels_section(labels)]


def execution_sections(
    execution: TestcaseExecution, generated_at: str
) -> List[Dict[str, Any]]:
    sections = [
        labels_section(
            [
                f"platform:{execution.platform}",
                f"testsuite:{execution.suite_name}",
                "source:junit",
                f"source-file:{execution.source_id}",
            ]
        )
    ]
    if execution.reason:
        sections.append(reason_section(execution.reason))
    if execution.output:
        sections.append(output_section(execution.output, generated_at))
    return sections


def report_to_report_ui_data(
    report: Report, execution_name: Optional[str] = None, only_failures: bool = False
) -> List[Dict[str, Any]]:
    builder = UiDataBuilder()
    execution_id = builder.next_id()

    root_labels = ["source:junit", "view:tests-first"]
    if report.build_url:
        root_labels.append(f"buildkite-build-url:{report.build_url}")

    suite_ids: List[str] = []

    for suite in report.suites.values():
        suite_child_ids: List[str] = []

        for logical in suite.logical_tests.values():
            execution_child_ids: List[str] = []

            for execution in logical.executions.values():
                if only_failures and execution.status not in {"FAILED", "ERRORED"}:
                    continue

                platform_node = builder.node(
                    execution.platform,
                    execution.duration_seconds,
                    execution_sections(execution, report.generated_at),
                    execution.status,
                )
                execution_child_ids.append(platform_node["id"])

            if execution_child_ids:
                logical_node = builder.node(
                    logical.logical_id,
                    logical_duration(logical),
                    logical_sections(logical),
                )
                suite_child_ids.append(logical_node["id"])
                builder.add_children(logical_node["id"], execution_child_ids)

        if suite_child_ids:
            suite_node = builder.node(
                suite.name,
                suite_duration(suite),
                [labels_section([f"testsuite:{suite.name}", "source:junit"])],
            )
            suite_ids.append(suite_node["id"])
            builder.add_children(suite_node["id"], suite_child_ids)

    builder.finalize_child_statuses()

    execution_data = {
        "id": execution_id,
        "name": execution_name or report.title,
        "durationMillis": duration_millis(report.duration_seconds),
        "summary": {
            "rawTestcases": report.raw_testcases,
            "suites": len(report.suites),
            "logicalTests": report.logical_test_count,
            "platformExecutions": report.platform_execution_count,
            "targets": len(report.platforms),
            "resolvedPlatforms": report.resolved_platforms,
            "structuralContainers": len(builder.test_nodes)
            - report.platform_execution_count,
            "statusCounts": dict(report.status_counts),
            "rootStatus": report.root_status,
        },
        "sections": [
            labels_section(root_labels),
            kvp_section(
                "Report summary",
                {
                    "Raw testcases": report.raw_testcases,
                    "Suites": len(report.suites),
                    "Logical tests": report.logical_test_count,
                    "Platform executions": report.platform_execution_count,
                    "Status": report.root_status,
                    "Generated at": report.generated_at,
                },
            ),
            kvp_section(
                "Infrastructure",
                {
                    "Hostname": "junit-html-report-tool",
                    "Username": "ci",
                    "Operating system": "mixed-platform",
                    "CPU cores": 1,
                },
            ),
        ],
        "roots": suite_ids,
        "children": dict(builder.children),
        "testNodes": builder.test_nodes,
    }
    return [execution_data]
