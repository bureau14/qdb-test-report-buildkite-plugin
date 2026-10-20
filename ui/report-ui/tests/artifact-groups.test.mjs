import assert from "node:assert/strict";
import { test } from "node:test";
import {
  fileLabel,
  formatFileSize,
  groupArtifacts,
} from "../src/components/details/artifact-groups.ts";

function artifact(path, executionId = "run", executionName = "suite") {
  return {
    name: "Test execution artifacts",
    relativePath: path,
    key: "job/logs.zip",
    sizeBytes: 128,
    executionId,
    executionName,
  };
}

test("execution files have readable labels and distinct diagnostic groups", () => {
  const groups = groupArtifacts([
    artifact("test-metadata/hash.json"),
    artifact("build/report.xml"),
    artifact("test-results/run/stdout.log"),
    artifact("test-results/run/qdb_test_log_pid_123_456.json"),
    artifact("test-results/run/test_runner_123_error_dump.log"),
    artifact("query/insecure/log/0-0-0-1/qdbd.log"),
    artifact("query/secure/log/0-0-0-1/qdbd.log"),
    artifact("server-logs/query.tar.gz"),
  ]);
  assert.deepEqual(
    groups.map((group) => group.kind),
    ["report", "crash", "runner", "server", "server", "details", "other"],
  );
  assert.equal(groups.find((group) => group.kind === "runner").files.length, 2);
  assert.equal(
    groups.filter((group) => group.kind === "server")[0].title,
    "Insecure · Node 0-0-0-1",
  );
  assert.equal(
    groups.filter((group) => group.kind === "server")[1].title,
    "Secure · Node 0-0-0-1",
  );
  assert.equal(
    fileLabel(artifact("test-results/run/qdb_test_log_pid_123_456.json")),
    "JSON log",
  );
  assert.equal(
    fileLabel(artifact("test-metadata/hash.json")),
    "Execution manifest",
  );
  assert.equal(
    fileLabel(artifact("query/insecure/log/1/var_lib_build_LOG")),
    "RocksDB LOG",
  );
  assert.equal(
    fileLabel(artifact("query/insecure/log/1/var_lib_build_LOG.old.123")),
    "RocksDB LOG.old.123",
  );
});

test("multiple suite executions do not merge files under an ambiguous log group", () => {
  const groups = groupArtifacts([
    artifact("test-results/one/stdout.log", "one", "alpha"),
    artifact("test-results/two/stdout.log", "two", "beta"),
  ]);
  assert.deepEqual(
    groups.map((group) => group.title),
    ["alpha · Runner logs", "beta · Runner logs"],
  );
});

test("empty files retain explicit units and size labels scale", () => {
  assert.equal(formatFileSize(0), "0 B · empty");
  assert.equal(formatFileSize(1024), "1 KB");
  assert.equal(formatFileSize(1024 * 1024), "1 MB");
});
