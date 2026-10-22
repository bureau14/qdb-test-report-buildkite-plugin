import assert from "node:assert/strict";
import {test} from "node:test";

import {statusCounts} from "../src/components/common/presentation.ts";

test("skipped-only containers keep their aggregate status", () => {
  const execution = new TestExecution({
    id : "skipped-report",
    roots : [ "suite" ],
    children : {suite : {ids : [ "skip" ], childStatuses : [ "SKIPPED" ]}},
    testNodes :
      [ {id : "suite", name : "Suite"}, {id : "skip", status : "SKIPPED"} ],
  });
  assert.equal(execution.displayStatus(execution.node("suite")), "SKIPPED");
  assert.deepEqual(execution.counts(execution.node("suite")), {SKIPPED : 1});
});
import TestExecution from "../src/components/common/TestExecution.ts";
import TreeState from "../src/components/sidebar/TreeState.ts";
import {visibleRows} from "../src/components/sidebar/VisibleTree.ts";

function report(status = "FAILED", extra = {}) {
  return new TestExecution({
    id : "report",
    name : "Full test report",
    durationMillis : 200,
    summary : {
      rootStatus : status,
      statusCounts : {SUCCESSFUL : 9, FAILED : 1},
      logicalStatusCounts : {SUCCESSFUL : 4, FAILED : 1},
      logicalTests : 5
    },
    roots : [ "suite" ],
    children : {
      suite : {ids : [ "logical" ], childStatuses : [ "FAILED", "SUCCESSFUL" ]},
      logical : {
        ids : [ "failed", "passed" ],
        childStatuses : [ "FAILED", "SUCCESSFUL" ]
      },
    },
    testNodes : [
      {id : "suite", name : "Suite"},
      {id : "logical", name : "Case", tags : [ 1 ]},
      {
        id : "failed",
        name : "Case - linux",
        status : "FAILED",
        source : [ 0, 0, 0 ],
        sections : [ {
          title : "Reason",
          blocks : [ {type : "p", content : "Expected 1, got 2"} ]
        } ]
      },
      {
        id : "passed",
        name : "Case - windows",
        status : "SUCCESSFUL",
        source : [ 1, 0, 0 ]
      },
    ],
    sourceTables : {
      targets : [ "linux", "windows" ],
      suites : [ "Suite" ],
      xmls : [ "suite.xml" ]
    },
    ...extra,
  });
}

test(
  "opening a failed report selects its overview and enables the combined filter",
  () => {
    const execution = report();
    assert.equal(TestExecution.initialSelection([ execution ]).item, execution);
    const state = new TreeState([ execution ]);
    assert.equal(state.showFailedAndErrored, true);
    assert.equal(state.nodes.suite.collapsed, false);
    assert.equal(state.nodes.logical.collapsed, true);
    assert.deepEqual(visibleRows([ execution ], state).map((row) => row.id),
      [ "report", "suite", "logical" ]);
  });

test("large failed reports expand affected branches down to the logical test",
  () => {
    const execution = report();
    execution.size = () => 40000;
    const state = new TreeState([ execution ]);
    assert.equal(state.nodes.suite.collapsed, false);
    assert.equal(state.nodes.logical.collapsed, true);
  });

test(
  "direct-link reveal overrides the default filter and expands the passed target",
  () => {
    const execution = report();
    const state = new TreeState([ execution ]);
    state.searchQuery = "other test";
    state.revealNode(execution, execution.node("passed"));
    assert.equal(state.hasActiveStatusFilter(), false);
    assert.equal(state.searchQuery, "");
    assert.ok(
      visibleRows([ execution ], state).some((row) => row.id === "passed"));
  });

test(
  "overview navigation can reveal a failed target without clearing the filter",
  () => {
    const execution = report();
    const state = new TreeState([ execution ]);
    state.revealNode(execution, execution.node("failed"), false);
    assert.equal(state.showFailedAndErrored, true);
    const ids = visibleRows([ execution ], state).map((row) => row.id);
    assert.ok(ids.includes("failed"));
    assert.ok(!ids.includes("passed"));
  });

test(
  "branch counts do not double count structural nodes or change full-report counts",
  () => {
    const execution = report();
    assert.deepEqual(
      execution.counts(execution.node("suite")), {FAILED : 1, SUCCESSFUL : 1});
    assert.deepEqual(statusCounts([ execution ]), {SUCCESSFUL : 9, FAILED : 1});
    assert.equal(
      execution.problemReason(execution.node("logical")), "Expected 1, got 2");
    assert.equal(execution.displayName(execution.node("failed")), "linux");
    assert.equal(execution.node("failed").name, "Case - linux");
  });

test("report-level errors activate the filter even with no failing testcase",
  () => {
    const execution =
      report("ERRORED", {roots : [], children : {}, testNodes : []});
    assert.equal(new TreeState([ execution ]).showFailedAndErrored, true);
    assert.equal(TestExecution.initialSelection([ execution ]).item, execution);
  });

test("CTest-only failures enable the filter and keep execution counts distinct",
  () => {
    const execution = report("FAILED", {
      summary : {
        rootStatus : "FAILED",
        logicalTests : 10,
        logicalStatusCounts : {SUCCESSFUL : 10},
        statusCounts : {SUCCESSFUL : 10},
        ctestExecutions : 1,
        ctestStatusCounts : {FAILED : 1}
      },
    });
    assert.equal(new TreeState([ execution ]).showFailedAndErrored, true);
    assert.deepEqual(execution.counts(), {SUCCESSFUL : 10, FAILED : 1});
    assert.deepEqual(execution.summary.logicalStatusCounts, {SUCCESSFUL : 10});
  });

test("successful and empty reports open without a failure filter", () => {
  const execution =
    report("SUCCESSFUL", {roots : [], children : {}, testNodes : []});
  assert.equal(new TreeState([ execution ]).hasActiveStatusFilter(), false);
  assert.equal(TestExecution.initialSelection([]), undefined);
});

test("search preserves failed target context and excludes successful siblings",
  () => {
    const execution = report();
    const state = new TreeState([ execution ]);
    state.searchQuery = "linux";
    assert.deepEqual(visibleRows([ execution ], state).map((row) => row.id),
      [ "report", "suite", "logical", "failed" ]);
  });
