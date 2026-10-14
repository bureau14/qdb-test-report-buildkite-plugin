import assert from "node:assert/strict";
import { test } from "node:test";
import TestExecution from "../src/components/common/TestExecution.ts";

function execution(rootStatus, testNodes = []) {
  return new TestExecution({
    id: "report",
    name: "Report",
    summary: { rootStatus },
    testNodes,
  });
}

test("archive-level report errors stay visible with successful tests", () => {
  const report = execution("ERRORED", [
    { id: "test", name: "passes", status: "SUCCESSFUL" },
  ]);
  assert.equal(report.overallStatus(), "ERRORED");
  assert.equal(report.statusCount().get("SUCCESSFUL"), 1);
  assert.equal(report.statusCount().get("ERRORED"), 0);
  assert.equal(TestExecution.initialSelection([report]).item, report);
});

test("archive-level report errors stay visible with no usable tests", () => {
  assert.equal(execution("ERRORED").overallStatus(), "ERRORED");
});

test("declared success does not hide an errored execution", () => {
  assert.equal(
    execution("SUCCESSFUL", [{ id: "test", status: "ERRORED" }]).overallStatus(),
    "ERRORED",
  );
});
