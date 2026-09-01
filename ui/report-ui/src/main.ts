/**
 * Modified from original source: https://github.com/ota4j-team/open-test-reporting/blob/main/html-report/src/main.ts
 */
import { createApp } from "vue";
import { createI18n } from "vue-i18n";

import "./style.css";
import App from "./App.vue";
import TestExecution from "./components/common/TestExecution.ts";
import VueEasyLightbox from "vue-easy-lightbox";

function measureStartup<T>(name: string, callback: () => T): T {
  performance.mark(`${name}-start`);
  const result = callback();
  performance.mark(`${name}-end`);
  performance.measure(name, `${name}-start`, `${name}-end`);
  return result;
}

function readEmbeddedReportData(): ExecutionData[] {
  const el = document.getElementById("report-data");
  if (!el) {
    if (Array.isArray(globalThis.testExecutions)) {
      return globalThis.testExecutions;
    }
    throw new Error("Missing embedded report data: #report-data");
  }

  performance.mark("report-json-parse-start");
  const data: unknown = JSON.parse(el.textContent || "null");
  performance.mark("report-json-parse-end");
  performance.measure(
    "report-json-parse",
    "report-json-parse-start",
    "report-json-parse-end",
  );

  el.remove();
  if (!Array.isArray(data)) {
    throw new Error("Invalid embedded report data: expected an array");
  }
  return data as ExecutionData[];
}

const reportData = readEmbeddedReportData();
const executions = measureStartup("report-model-create", () =>
  reportData.map((it) => new TestExecution(it)),
);
const app = createApp(App, {
  executions,
});

app.use(
  createI18n({
    messages: {
      en: {
        executionSummary: {
          testCount: "No tests | 1 test | {count} tests",
          testsPerTargetCount:
            "No tests per target | 1 test per target | {count} tests per target",
          targetCount: "No targets | 1 target | {count} targets",
          errored: "1 errored | {count} errored",
          failed: "1 failed | {count} failed",
          aborted: "1 aborted | {count} aborted",
          skipped: "1 skipped | {count} skipped",
          execution: "in 1 execution | in { count } executions",
        },
        clipboard: {
          copy: "Copy to clipboard",
        },
        duration: {
          hours: "{count} h",
          minutes: "{count} m",
          seconds: "{count} s",
          millis: "{count} ms",
        },
        toolbar: {
          search: "Search tests",
          sortAlphabetically: "Sort alphabetically",
          sortByExecutionOrder: "Sort by execution order",
          collapseAll: "Collapse all",
          expandAll: "Expand all",
          showAborted: "Show aborted",
          showFailedAndErrored: "Show failed/errored",
          showSkipped: "Show skipped",
          showSuccessful: "Show successful",
        },
      },
    },
  }),
);

app.use(VueEasyLightbox);

performance.mark("report-app-mount-start");
app.mount("#app");
performance.mark("report-app-mount-end");
performance.measure(
  "report-app-mount",
  "report-app-mount-start",
  "report-app-mount-end",
);
