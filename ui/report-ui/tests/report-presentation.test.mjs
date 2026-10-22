import assert from "node:assert/strict";
import {test} from "node:test";

import {
  collectResults,
  countOutcomes,
  filterResults,
  groupResults,
  relatedResults,
  safeReportUrl,
  sortResultGroups,
  valueMismatch
} from "../src/components/common/report-presentation.ts";
import TestExecution from "../src/components/common/TestExecution.ts";

function makeReport(id = "run") {
  return new TestExecution({
    id,
    name : "Report",
    durationMillis : 200,
    sections : [],
    roots : [ "suite" ],
    children : {
      suite : {
        ids : [ "a", "b", "c", "check", "unrelated" ],
        childStatuses : [ "FAILED", "SUCCESSFUL", "SKIPPED" ]
      }
    },
    sourceTables : {
      targets : [ "linux", "windows" ],
      suites : [ "query", "ctest" ],
      xmls : [ "query.xml", "ctest.xml" ]
    },
    sourceArtifactTable : [
      {
        name : "Runner",
        relativePath : "a.log",
        key : "job/logs.zip",
        sizeBytes : 1,
        executionId : "managed"
      },
      {
        name : "Runner",
        relativePath : "b.log",
        key : "job/logs.zip",
        sizeBytes : 1,
        executionId : "other"
      },
    ],
    testNodes : [
      {id : "suite", name : "Suite"},
      {
        id : "a",
        name : "limit-offset - linux",
        status : "FAILED",
        source : [ 0, 0, 0 ],
        sourceArtifacts : [ 0 ],
        sections : [ {
          title : "Reason",
          blocks : [ {
            type : "p",
            content : "mismatched row 1: expected '-19977', got '2'"
          } ]
        } ]
      },
      {
        id : "b",
        name : "limit-offset - windows",
        status : "FAILED",
        source : [ 1, 0, 0 ],
        sourceArtifacts : [ 0 ],
        sections : [ {
          title : "Reason",
          blocks : [ {
            type : "p",
            content : "mismatched row 1: expected '-19977', got '2'"
          } ]
        } ]
      },
      {
        id : "c",
        name : "disabled - linux",
        status : "SKIPPED",
        source : [ 0, 0, 0 ],
        sections : []
      },
      {
        id : "check",
        name : "runner - linux",
        status : "FAILED",
        source : [ 0, 1, 1 ],
        sourceArtifacts : [ 0 ],
        sections : []
      },
      {
        id : "unrelated",
        name : "other - linux",
        status : "FAILED",
        source : [ 0, 1, 1 ],
        sourceArtifacts : [ 1 ],
        sections : []
      },
    ],
    summary : {
      logicalStatusCounts : {FAILED : 1, SKIPPED : 1},
      statusCounts : {FAILED : 2, SKIPPED : 1},
      ctestStatusCounts : {FAILED : 2},
      rootStatus : "FAILED"
    },
  });
}

test(
    "logical headlines, platform results, and CTest checks retain separate counts",
    () => {
      const report = makeReport();
      const results = collectResults([ report ]);
      assert.equal(results.length, 5);
      assert.deepEqual(countOutcomes([ report ], false),
                       {FAILED : 1, SKIPPED : 1});
      assert.deepEqual(countOutcomes([ report ], true), {FAILED : 2});
      const filter = {scope : "problems", search : "", suite : "", status : ""};
      const groups = groupResults(filterResults(results, filter), true);
      assert.equal(groups.length, 1);
      assert.equal(groups[0].name, "limit-offset");
      assert.equal(groups[0].results.length, 2);
      assert.equal(filterResults(results, {...filter, scope : "ctest"}).length,
                   2);
    });

test(
    "group signatures distinguish outcomes and messages and retain report identity",
    () => {
      const results =
          collectResults([
            makeReport("one"), makeReport("two")
          ]).filter((result) => !result.ctest && result.status === "FAILED");
      const groups = groupResults(results, true);
      assert.equal(groups.length, 1);
      assert.equal(groups[0].results.length, 4);
      assert.equal(new Set(groups[0].results.map((result) => result.key)).size,
                   4);
      assert.equal(groupResults(
                       [
                         ...results, {...results[0], reason : "different"},
                         {...results[0], status : "ERRORED"}
                       ],
                       true)
                       .length,
                   3);
    });

test("search includes paths and messages and status changes preserve the query",
     () => {
       const results = collectResults([ makeReport() ]);
       const filter = {
         scope : "tests",
         search : "SUITE",
         suite : "query",
         status : "FAILED"
       };
       assert.equal(filterResults(results, filter).length, 2);
       filter.status = "SKIPPED";
       assert.equal(filterResults(results, filter).length, 1);
       assert.equal(filter.search, "SUITE");
       assert.equal(
           filterResults(results, {...filter, search : "missing"}).length, 0);
       assert.equal(
           filterResults(results, {...filter, search : "-19977", status : ""})
               .length,
           2);
     });

test("related checks match exact managed execution identity", () => {
  const results = collectResults([ makeReport() ]);
  const related = relatedResults(
      results.find((result) => result.selection.item.id === "a"), results);
  assert.deepEqual(related.map((result) => result.selection.item.id),
                   [ "check" ]);
});

test(
    "query comparison extracts values and does not invent structure for other messages",
    () => {
      assert.deepEqual(
          valueMismatch("mismatched row 1: expected '-19977', got '2'"),
          {row : "1", expected : "-19977", actual : "2"});
      assert.equal(valueMismatch("unexpected exception"), undefined);
      assert.equal(safeReportUrl("link:javascript:alert(1)"), undefined);
      assert.equal(safeReportUrl("link:https://example.com/build/12"),
                   "https://example.com/build/12");
    });

test(
    "empty or report-level failures remain valid without invented test outcomes",
    () => {
      const report = new TestExecution({
        id : "error",
        name : "Input error",
        roots : [],
        children : {},
        testNodes : [],
        summary : {
          rootStatus : "ERRORED",
          logicalStatusCounts : {},
          ctestStatusCounts : {}
        }
      });
      assert.equal(report.overallStatus(), "ERRORED");
      assert.deepEqual(collectResults([ report ]), []);
      assert.deepEqual(countOutcomes([ report ], false), {});
    });

test(
    "CTest problem filtering includes failures and errors without passed checks",
    () => {
      const results = collectResults([ makeReport() ]);
      const check = results.find((result) => result.ctest);
      const records = [
        ...results, {...check, key : "error", status : "ERRORED"},
        {...check, key : "passed", status : "SUCCESSFUL"}
      ];
      const filter =
          {scope : "ctest", status : "PROBLEMS", search : "", suite : ""};
      assert.deepEqual(
          filterResults(records, filter).map((result) => result.status),
          [ "FAILED", "FAILED", "ERRORED" ]);
      assert.equal(filterResults(records, {...filter, status : ""}).length, 4);
    });

test(
    "result sorting supports status, name, duration, and grouped problem count",
    () => {
      const result = collectResults([ makeReport() ])[0];
      const makeGroup = (name, status, millis, count = 1) => ({
        key : name,
        name,
        status,
        reason : "",
        results : Array.from(
            {length : count},
            () => ({...result, selection : {item : {durationMillis : millis}}}))
      });
      const groups = [
        makeGroup("Zulu", "SUCCESSFUL", 90),
        makeGroup("Alpha", "FAILED", 10, 2), makeGroup("Beta", "ERRORED", 30)
      ];
      assert.deepEqual(
          sortResultGroups(groups, "status").map((group) => group.name),
          [ "Beta", "Alpha", "Zulu" ]);
      assert.deepEqual(
          sortResultGroups(groups, "name").map((group) => group.name),
          [ "Alpha", "Beta", "Zulu" ]);
      assert.deepEqual(
          sortResultGroups(groups, "duration").map((group) => group.name),
          [ "Zulu", "Beta", "Alpha" ]);
      assert.deepEqual(
          sortResultGroups(groups, "problems").map((group) => group.name),
          [ "Alpha", "Beta", "Zulu" ]);
      assert.deepEqual(groups.map((group) => group.name),
                       [ "Zulu", "Alpha", "Beta" ]);
    });
