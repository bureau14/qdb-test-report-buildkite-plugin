#!/usr/bin/env python3
"""Serialize the neutral JUnit report model into the report HTML UI data contract."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set

from junit_report_model import (
    ArtifactLink,
    LogicalTest,
    Report,
    TestFile,
    TestSuite,
    TestcaseExecution,
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


def artifact_link_data(artifact: ArtifactLink) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "name": artifact.name,
        "relativePath": artifact.relative_path,
        "key": artifact.key,
        "sizeBytes": artifact.size_bytes,
    }
    if artifact.url:
        data["url"] = artifact.url
    return data


def artifact_display_label(artifact: ArtifactLink, siblings: List[ArtifactLink]) -> str:
    same_name_count = sum(1 for item in siblings if item.name == artifact.name)
    if same_name_count > 1:
        return f"{artifact.name} / {artifact.relative_path}"
    return artifact.name


def artifact_value(artifact: ArtifactLink) -> str:
    if artifact.url:
        return f"link:{artifact.url}"
    return artifact.key


class UiDataBuilder:
    def __init__(self) -> None:
        self._next_id = 1
        self.test_nodes: List[Dict[str, Any]] = []
        self.children: "OrderedDict[str, Dict[str, List[str]]]" = OrderedDict()
        self.source_tables: Dict[str, List[str]] = {
            "targets": [],
            "suites": [],
            "xmls": [],
            "buildUrls": [],
            "jobUrls": [],
            "jobIds": [],
            "xmlUrls": [],
        }
        self._source_indexes: Dict[str, Dict[str, int]] = {key: {} for key in self.source_tables}
        self.tag_tables: Dict[str, List[str]] = {
            "suites": [],
            "platforms": [],
            "classnames": [],
            "testNames": [],
            "logicalIds": [],
        }
        self._tag_indexes: Dict[str, Dict[str, int]] = {key: {} for key in self.tag_tables}

    def next_id(self) -> str:
        value = str(self._next_id)
        self._next_id += 1
        return value

    def _source_index(self, table: str, value: str) -> int:
        indexes = self._source_indexes[table]
        if value not in indexes:
            indexes[value] = len(self.source_tables[table])
            self.source_tables[table].append(value)
        return indexes[value]

    def source(self, execution: TestcaseExecution, build_url: Optional[str]) -> List[int]:
        source = [
            self._source_index("targets", execution.platform),
            self._source_index("suites", execution.suite_name),
            self._source_index("xmls", execution.source_id),
        ]
        if execution.source_job_url:
            source.append(self._source_index("jobUrls", execution.source_job_url))
            if execution.source_job_id:
                source.append(self._source_index("jobIds", execution.source_job_id))
        if build_url:
            while len(source) < 5:
                source.append(-1)
            source.append(self._source_index("buildUrls", build_url))
        if execution.source_xml_url:
            while len(source) < 6:
                source.append(-1)
            source.append(self._source_index("xmlUrls", execution.source_xml_url))
        return source

    def _tag_index(self, table: str, value: str) -> int:
        indexes = self._tag_indexes[table]
        if value not in indexes:
            indexes[value] = len(self.tag_tables[table])
            self.tag_tables[table].append(value)
        return indexes[value]

    def suite_tags(self, suite: TestSuite) -> List[Any]:
        return [0, self._tag_index("suites", suite.name)]

    def logical_tags(self, logical: LogicalTest) -> List[Any]:
        failed_platforms: List[int] = []
        errored_platforms: List[int] = []
        skipped_platforms: List[int] = []
        for execution in logical.executions.values():
            platform_index = self._tag_index("platforms", execution.platform)
            if execution.status == "FAILED":
                failed_platforms.append(platform_index)
            elif execution.status == "ERRORED":
                errored_platforms.append(platform_index)
            elif execution.status == "SKIPPED":
                skipped_platforms.append(platform_index)
        return [
            1,
            self._tag_index("suites", logical.suite_name),
            self._tag_index("classnames", logical.classname),
            self._tag_index("testNames", logical.name),
            self._tag_index("logicalIds", logical.logical_id),
            failed_platforms,
            errored_platforms,
            skipped_platforms,
        ]

    def node(
        self,
        name: str,
        duration_seconds_value: float,
        sections: List[Dict[str, Optional[Any]]] = None,
        status: Optional[str] = None,
        source: Optional[List[int]] = None,
        tags: Optional[List[Any]] = None,
        source_artifacts: Optional[List[ArtifactLink]] = None,
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
        if source is not None:
            result["source"] = source
        if tags is not None:
            result["tags"] = tags
        if source_artifacts:
            result["sourceArtifacts"] = [artifact_link_data(item) for item in source_artifacts]
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


def test_file_duration(test_file: TestFile) -> float:
    return sum(logical_duration(logical) for logical in test_file.logical_tests.values())


def class_duration(logicals: List[LogicalTest]) -> float:
    return sum(logical_duration(logical) for logical in logicals)


def suite_duration(suite: TestSuite) -> float:
    return sum(test_file_duration(test_file) for test_file in suite.test_files.values())


def execution_sections(execution: TestcaseExecution, generated_at: str) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
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

    root_labels = ["view:tests-first"]

    summary_content: Dict[str, Any] = {
        "Suites": len(report.suites),
        "Logical tests": report.logical_test_count,
        "Platform executions": report.platform_execution_count,
        "Status": report.root_status,
        "Generated at": report.generated_at,
    }
    if report.build_url:
        summary_content["Buildkite build"] = f"link:{report.build_url}"
    if report.commit_url:
        summary_content["Git commit"] = f"link:{report.commit_url}"

    suite_ids: List[str] = []

    for suite in report.suites.values():
        suite_child_ids: List[str] = []

        for test_file in suite.test_files.values():
            test_file_child_ids: List[str] = []
            logicals_by_classname: "OrderedDict[str, List[LogicalTest]]" = OrderedDict()

            for logical in test_file.logical_tests.values():
                logicals_by_classname.setdefault(logical.classname, []).append(logical)

            for classname, logicals in logicals_by_classname.items():
                classname_child_ids: List[str] = []

                for logical in logicals:
                    execution_child_ids: List[str] = []

                    for execution in logical.executions.values():
                        if only_failures and execution.status not in {"FAILED", "ERRORED"}:
                            continue

                        platform_node = builder.node(
                            f"{execution.name} - {execution.platform}",
                            execution.duration_seconds,
                            execution_sections(execution, report.generated_at),
                            execution.status,
                            builder.source(execution, report.build_url),
                            source_artifacts=execution.source_artifacts,
                        )
                        execution_child_ids.append(platform_node["id"])

                    if execution_child_ids:
                        logical_node = builder.node(
                            logical.name,
                            logical_duration(logical),
                            tags=builder.logical_tags(logical),
                        )
                        classname_child_ids.append(logical_node["id"])
                        builder.add_children(logical_node["id"], execution_child_ids)

                if classname_child_ids:
                    classname_node = builder.node(
                        classname or "<no classname>",
                        class_duration(logicals),
                    )
                    test_file_child_ids.append(classname_node["id"])
                    builder.add_children(classname_node["id"], classname_child_ids)

            if test_file_child_ids:
                test_file_node = builder.node(
                    test_file.name,
                    test_file_duration(test_file),
                )
                suite_child_ids.append(test_file_node["id"])
                builder.add_children(test_file_node["id"], test_file_child_ids)

        if suite_child_ids:
            suite_node = builder.node(
                suite.name,
                suite_duration(suite),
                tags=builder.suite_tags(suite),
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
            "structuralContainers": len(report.suites)
            + sum(len(suite.test_files) for suite in report.suites.values())
            + sum(
                len({logical.classname for logical in test_file.logical_tests.values()})
                for suite in report.suites.values()
                for test_file in suite.test_files.values()
            )
            + report.logical_test_count,
            "statusCounts": dict(report.status_counts),
            "logicalStatusCounts": dict(report.logical_status_counts),
            "rootStatus": report.root_status,
        },
        "sourceTables": builder.source_tables,
        "tagTables": builder.tag_tables,
        "sections": [
            labels_section(root_labels),
            kvp_section(
                "Report summary",
                summary_content,
            ),
        ],
        "roots": suite_ids,
        "children": dict(builder.children),
        "testNodes": builder.test_nodes,
    }
    if report.artifacts:
        artifact_content: Dict[str, Any] = {}
        for artifact in report.artifacts:
            artifact_content[artifact_display_label(artifact, report.artifacts)] = artifact_value(
                artifact
            )
        execution_data["sections"].append(kvp_section("Artifacts", artifact_content))
    return [execution_data]
