from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_tree_row_aggregates_skipped_only_containers_to_skipped_status():
    tree_row = REPO_ROOT / "ui/report-ui/src/components/sidebar/TreeRow.vue"
    source = tree_row.read_text(encoding="utf-8")

    assert 'statuses.includes("SKIPPED")' in source
    assert 'return "SKIPPED"' in source


def test_execution_summary_uses_logical_tests_not_platform_executions_for_header_count():
    execution_summary = REPO_ROOT / "ui/report-ui/src/components/header/ExecutionSummary.vue"
    source = execution_summary.read_text(encoding="utf-8")

    assert 'summaryCount("logicalTests")' in source
    assert 'summaryCount("platformExecutions")' not in source
    assert "executionSummary.testCount" in source
    assert "executionSummary.testsPerTargetCount" not in source


def test_execution_summary_test_count_label_says_tests_not_nodes():
    source = (REPO_ROOT / "ui/report-ui/src/main.ts").read_text(encoding="utf-8")

    assert 'testCount: "No tests | 1 test | {count} tests"' in source
    assert 'testCount: "No nodes | 1 node | {count} nodes"' not in source


def test_main_reads_embedded_report_data_as_json_and_removes_script_node():
    source = (REPO_ROOT / "ui/report-ui/src/main.ts").read_text(encoding="utf-8")

    assert 'document.getElementById("report-data")' in source
    assert "JSON.parse" in source
    assert ".remove()" in source
    assert '"report-json-parse"' in source
    assert '"report-model-create"' in source
    assert '"report-app-mount"' in source
    assert "globalThis.testExecutions" in source
    assert "globalThis.testExecutions.map" not in source


def test_app_times_initial_selection():
    source = (REPO_ROOT / "ui/report-ui/src/App.vue").read_text(encoding="utf-8")

    assert '"report-initial-selection"' in source
    assert "performance.mark" in source
    assert "performance.measure" in source


def test_sidebar_times_tree_state_creation():
    source = (REPO_ROOT / "ui/report-ui/src/components/sidebar/SideBar.vue").read_text(
        encoding="utf-8"
    )

    assert '"report-tree-state-create"' in source
    assert "performance.mark" in source
    assert "performance.measure" in source


def test_visible_rows_are_not_coupled_to_selection_state():
    source = (REPO_ROOT / "ui/report-ui/src/components/sidebar/VisibleTree.ts").read_text(
        encoding="utf-8"
    )

    assert "selected:" not in source
    assert "selection" not in source


def test_tree_row_computes_selection_locally():
    source = (REPO_ROOT / "ui/report-ui/src/components/sidebar/TreeRow.vue").read_text(
        encoding="utf-8"
    )

    assert "const isSelected = computed" in source
    assert "selection.value?.item" in source
    assert "row.selected" not in source


def test_test_node_details_synthesizes_source_and_tag_sections_from_compact_metadata():
    source = (REPO_ROOT / "ui/report-ui/src/components/details/TestNodeDetails.vue").read_text(
        encoding="utf-8"
    )

    assert "props.execution.sourceDataForNode(props.node)" in source
    assert "props.execution.tagLabels(props.node)" in source
    assert 'title: "Source"' in source
    assert 'title: "Tags"' in source
    assert 'type: "labels"' in source
    assert "Buildkite build" in source
    assert "link:${source.buildUrl}" in source
    assert "Buildkite job" in source
    assert "link:${source.jobUrl}" in source
    assert "props.execution.sourceArtifactsForNode(props.node)" in source
    assert 'title: "Artifacts"' in source
    assert "artifactContent[label]" in source
    assert 'sourceContent["Artifact:' not in source
    assert "Artifact:" not in source
    assert ':sections="sections"' in source
    assert ':sections="node.sections"' not in source


def test_artifact_links_display_the_uploaded_relative_path():
    details = (REPO_ROOT / "ui/report-ui/src/components/details/TestNodeDetails.vue").read_text(
        encoding="utf-8"
    )
    rendered_block = (
        REPO_ROOT / "ui/report-ui/src/components/details/RenderedBlock.vue"
    ).read_text(encoding="utf-8")

    assert "`link:${artifact.url}\\n${artifact.relativePath}`" in details
    assert "function linkText(value: string): string" in rendered_block
    assert 'value.substring(5).split("\\n", 2)' in rendered_block


def test_ui_source_contract_supports_optional_junit_xml_links():
    global_types = (REPO_ROOT / "ui/report-ui/src/global.d.ts").read_text(encoding="utf-8")
    test_execution = (REPO_ROOT / "ui/report-ui/src/components/common/TestExecution.ts").read_text(
        encoding="utf-8"
    )
    details = (REPO_ROOT / "ui/report-ui/src/components/details/TestNodeDetails.vue").read_text(
        encoding="utf-8"
    )

    assert "xmlUrl: string | undefined" in global_types
    assert "xmlUrls: string[]" in global_types
    assert "qdbProcessId: string | undefined" in global_types
    assert "qdbProcessIds?: string[]" in global_types
    assert "this.sourceTables.xmlUrls[node.source[6]]" in test_execution
    assert "this.sourceTables.qdbProcessIds?.[node.source[7]]" in test_execution
    assert "sourceDataForNode(node: TestNodeData): SourceData[]" in test_execution
    assert "sourceArtifactsForNode(node: TestNodeData): SourceArtifactData[]" in test_execution
    assert "this.children(current).forEach(collect)" in test_execution
    assert "link:${source.xmlUrl}" in details
    assert 'sourceContent["QDB PID"] = source.qdbProcessId' in details
    assert "JUnit XML ${index + 1} (${source.target} / ${source.suite} / ${source.xml})" in details
    assert "Modified from original source" in "\n".join(test_execution.splitlines()[:3])
    assert "Modified from original source" in "\n".join(details.splitlines()[:3])


def test_test_execution_caches_aggregate_values():
    source = (REPO_ROOT / "ui/report-ui/src/components/common/TestExecution.ts").read_text(
        encoding="utf-8"
    )

    assert "private readonly overallStatusValue" in source
    assert "private readonly statusCounts" in source
    assert "private readonly nodesWithChildrenValue" in source
    assert "private readonly firstFailedOrErroredNode" in source
    assert "private readonly tagTables" in source
    assert "tagLabels(node: TestNodeData)" in source


def test_execution_details_uses_summary_style_header():
    source = (REPO_ROOT / "ui/report-ui/src/components/details/ExecutionDetails.vue").read_text(
        encoding="utf-8"
    )

    assert "Modified from original source" in "\n".join(source.splitlines()[:3])
    assert "summaryMessage" in source
    assert "testResultStatusBackgroundColorClasses(execution.overallStatus())" in source
    assert "TestResultStatusIcon" in source


def test_edited_ui_files_have_modified_from_original_source_comment():
    for relative_path in [
        "ui/report-ui/src/components/sidebar/TreeRow.vue",
        "ui/report-ui/src/components/sidebar/ToolBar.vue",
        "ui/report-ui/src/components/sidebar/VisibleTree.ts",
        "ui/report-ui/src/components/sidebar/ExecutionTree.vue",
        "ui/report-ui/src/components/sidebar/SideBar.vue",
        "ui/report-ui/src/components/details/TestNodeDetails.vue",
        "ui/report-ui/src/components/details/RenderedBlock.vue",
        "ui/report-ui/src/components/details/ExecutionDetails.vue",
        "ui/report-ui/src/components/header/ExecutionSummary.vue",
        "ui/report-ui/src/components/common/TestExecution.ts",
        "ui/report-ui/src/App.vue",
        "ui/report-ui/src/main.ts",
    ]:
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        top_of_file_comment = "\n".join(source.splitlines()[:3])
        assert "Modified from original source" in top_of_file_comment


def test_toolbar_status_buttons_are_inclusive_filters():
    tree_state = (REPO_ROOT / "ui/report-ui/src/components/sidebar/TreeState.ts").read_text(
        encoding="utf-8"
    )

    assert "public showAborted = false" in tree_state
    assert "public showFailedAndErrored = false" in tree_state
    assert "public showSkipped = false" in tree_state
    assert "public showSuccessful = false" in tree_state
    assert "if (!this.hasActiveStatusFilter())" in tree_state
    assert "return true" in tree_state
    assert "return this.showFailedAndErrored" in tree_state


def test_sidebar_search_is_a_case_insensitive_ancestor_preserving_filter():
    tree_state = (REPO_ROOT / "ui/report-ui/src/components/sidebar/TreeState.ts").read_text(
        encoding="utf-8"
    )
    visible_tree = (REPO_ROOT / "ui/report-ui/src/components/sidebar/VisibleTree.ts").read_text(
        encoding="utf-8"
    )
    toolbar = (REPO_ROOT / "ui/report-ui/src/components/sidebar/ToolBar.vue").read_text(
        encoding="utf-8"
    )
    main = (REPO_ROOT / "ui/report-ui/src/main.ts").read_text(encoding="utf-8")

    assert 'public searchQuery = ""' in tree_state
    assert "hasActiveSearch(): boolean" in tree_state
    assert "matchesSearch(name: string): boolean" in tree_state
    assert "toLocaleLowerCase" in tree_state
    assert "treeState.matchesSearch(node.name)" in visible_tree
    assert "containsSearchMatch" in visible_tree
    assert 'v-model="treeState.searchQuery"' in toolbar
    assert 'type="search"' in toolbar
    assert "toolbar: {" in main
    assert 'search: "Search tests"' in main


def test_sidebar_search_collects_matches_from_all_sibling_branches():
    visible_tree = (REPO_ROOT / "ui/report-ui/src/components/sidebar/VisibleTree.ts").read_text(
        encoding="utf-8"
    )

    assert "let descendantMatch = false" in visible_tree
    assert "for (const child of children)" in visible_tree
    assert "descendantMatch =" in visible_tree


def test_sidebar_search_keeps_all_descendants_of_a_direct_match():
    visible_tree = (REPO_ROOT / "ui/report-ui/src/components/sidebar/VisibleTree.ts").read_text(
        encoding="utf-8"
    )

    assert "function addVisibleDescendants(" in visible_tree
    assert "addVisibleDescendants(execution, node, children)" in visible_tree


def test_sidebar_defaults_to_alphabetical_sorting_at_every_tree_depth():
    tree_state = (REPO_ROOT / "ui/report-ui/src/components/sidebar/TreeState.ts").read_text(
        encoding="utf-8"
    )
    visible_tree = (REPO_ROOT / "ui/report-ui/src/components/sidebar/VisibleTree.ts").read_text(
        encoding="utf-8"
    )
    toolbar = (REPO_ROOT / "ui/report-ui/src/components/sidebar/ToolBar.vue").read_text(
        encoding="utf-8"
    )
    main = (REPO_ROOT / "ui/report-ui/src/main.ts").read_text(encoding="utf-8")

    assert 'public sortMode: "alphabetical" | "execution" = "alphabetical"' in tree_state
    assert "toggleSortMode()" in tree_state
    assert "sortedChildren" in visible_tree
    assert 'treeState.sortMode === "alphabetical"' in visible_tree
    assert "localeCompare" in visible_tree
    assert "treeState.toggleSortMode()" in toolbar
    assert "toolbar.sortAlphabetically" in toolbar
    assert 'sortAlphabetically: "Sort alphabetically"' in main
    assert 'sortByExecutionOrder: "Sort by execution order"' in main


def test_sidebar_syncs_selected_nodes_with_static_url_fragments():
    execution = (REPO_ROOT / "ui/report-ui/src/components/common/TestExecution.ts").read_text(
        encoding="utf-8"
    )
    tree_state = (REPO_ROOT / "ui/report-ui/src/components/sidebar/TreeState.ts").read_text(
        encoding="utf-8"
    )
    sidebar = (REPO_ROOT / "ui/report-ui/src/components/sidebar/SideBar.vue").read_text(
        encoding="utf-8"
    )

    assert "node(id: string): TestNodeData | TestExecution | undefined" in execution
    assert "clearFilters()" in tree_state
    assert "revealNode(execution: TestExecution, node: TestNodeData | TestExecution)" in tree_state
    assert 'hash.startsWith("#node=")' in sidebar
    assert "decodeURIComponent" in sidebar
    assert "execution.node(nodeId)" in sidebar
    assert "treeState.revealNode(linkedSelection.execution, linkedSelection.item)" in sidebar
    assert 'window.addEventListener("hashchange", selectLocationHash)' in sidebar
    assert 'window.removeEventListener("hashchange", selectLocationHash)' in sidebar
    assert "window.history.replaceState" in sidebar
    assert "const locator = `#node=${encodeURIComponent(next.item.id)}`" in sidebar


def test_virtualized_tree_scrolls_selected_deep_link_target_into_view():
    tree = (REPO_ROOT / "ui/report-ui/src/components/sidebar/ExecutionTree.vue").read_text(
        encoding="utf-8"
    )

    assert "watch(selection" in tree
    assert "await nextTick()" in tree
    assert "rows.value.findIndex((row) => row.id === selectedId)" in tree
    assert "selectedTop" in tree
    assert "container.value.scrollTop" in tree
    assert "ROW_HEIGHT" in tree
