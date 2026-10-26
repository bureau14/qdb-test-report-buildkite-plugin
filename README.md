# Buildkite Test Report Plugin

A [Buildkite plugin](https://buildkite.com/docs/plugins) for generating self-contained JUnit HTML reports, publishing them to S3/R2-compatible object storage, and adding Buildkite annotations that link to the uploaded reports.

## What it does

- **Job report** — after a test step finishes, reads that job's local JUnit XML from `job.junit_input_path`, generates a per-job HTML report, uploads the HTML/summary/raw XML, and optionally fails the step when tests failed.
- **Aggregate report** — in a later reporting step, discovers XML uploaded by earlier job-report steps for the current build, downloads it, generates one aggregate HTML report, and uploads the aggregate HTML/summary.

Each platform-execution leaf is labeled `{test name} - {platform}`, preserving test identity in the sidebar and detail header. When `ARTIFACTS_DOMAIN` is configured, its Source panel links `JUnit XML` directly to the exact raw XML that produced the selected execution. Without a browser-facing artifacts domain, the XML name remains visible but is not made clickable.

The self-contained report supports case-insensitive sidebar search without a server. It also updates the browser URL to `#node=<id>` for the selected report node; share that full URL to open the same static report with the node selected, its path expanded, and the sidebar scrolled to it. Node IDs are specific to the generated report file.

Configure exactly one mode per plugin invocation:

- `job` requires `variant` and at least one of `junit_input_path` or `manifest_input_path`.
- `aggregate` enables full-build report mode; optional download settings tune aggregate XML fetch concurrency.

Common report options such as `title`, `only_failures`, `annotate`, and `project_id` stay at the plugin top level.

Job and aggregate annotations separate failed and errored executions into two tables. The Boost.Test/test-runner table shows Suite / report, test case, failure reason, and execution time. Suite / report displays the suite name once when it equals the XML report filename stem; otherwise it displays `suite::report`. This affects only the label, preserving internal grouping and deduplication keys. The CTest table shows test case (without the repeated class name), failure reason, and execution time. Execution time is shown in seconds to three decimal places in the final column; missing durations in older summaries appear as a dash. Neither table includes status, targets, or XML links. Errored executions have an `ERRORED:` prefix in the failure reason; ordinary failures have no prefix. Failure reasons are flattened to one line and capped at 240 characters, including the prefix; missing reasons appear as a dash. Each test case appears once, using the reason and execution time from its first reported failing or errored target. All target executions remain available in the full report. Both tables share Buildkite's 1 MiB annotation limit, with a count of omitted test cases when necessary. The summary and full-report link retain their space in the annotation.

The plugin runs from the Buildkite `post-command` hook, so reports are still published after the step command exits with a failure.

The plugin exits `64` when `job.fail_on_test_failures` is true and the generated job report contains failed or errored tests or malformed JUnit XML, whether collected through legacy inputs or execution manifests. Setting it to `false` allows those results to exit `0`. Malformed legacy XML remains listed in the report and summary and creates an error annotation listing the malformed files when `annotate: true`. Malformed manifest-owned XML remains an errored launcher result. When the HTML report is available through `ARTIFACTS_DOMAIN`, that annotation includes its link; if the report is unavailable, it still creates the error annotation without a link. When the original job command exits non-zero but every reported test passes, the plugin creates a warning annotation explaining the mismatch, even without `ARTIFACTS_DOMAIN`. It also exits `1` for other internal plugin errors and otherwise exits `0` so Buildkite can preserve the original command status. Aggregate mode does not fail on test failures or malformed JUnit XML; it exits `0` while retaining diagnostics and error-style annotations when enabled. It also exits `0` when no XML is discovered, but creates an error-style annotation unless `annotate: false` is set.

## Historical test health

Run `tools/test_history.py` to analyze the latest N completed builds on `master`.
It writes a searchable, self-contained `history.html` and a machine-readable
`history.json`. This is a standalone command; existing job and aggregate report
steps do not change.

```powershell
# Set BUILDKITE_API_TOKEN in the environment (read_builds scope).
python tools/test_history.py --organization quasardb --pipeline quasardb-build --builds 30 --output reports/history
```

Install `lib/requirements.txt` first. The command uses the standard AWS credential
chain and requires `s3:ListBucket` and `s3:GetObject` on the report objects. Tokens
are read from the environment, never from command-line arguments or output.
Build metadata comes from the [Buildkite Builds API](https://buildkite.com/docs/apis/rest-api/builds),
with pagination and a branch filter. The sample organization is configurable;
use your organization's Buildkite slug.

`--branch` defaults to `master`; `--destination` defaults to
`s3://qdb-cicd-artifacts`; `--project` defaults to `quasardb-build`.
The build **UUID** (`id`), rather than the build number, resolves reports beneath:

```text
s3://qdb-cicd-artifacts/quasardb-build/refs/heads/{branch}/reports/builds/{build_id}/variants/{platform}/jobs/{job_id}/xml/**
```

Both loose XML and `junit.zip` uploads use the existing aggregate downloader,
including archive validation. One build is downloaded at a time into temporary
storage and deleted after parsing. Builds are selected by creation order, with
unfinished builds excluded. Failed and canceled completed builds remain in the
window so failures are not filtered away. Fewer than N builds are returned if
the available completed branch history is shorter.

The report displays:

| Signal | Meaning |
| --- | --- |
| Suspected flaky | At least two pass/fail transitions in measured history, or both passing and failing observations in one build. A single regression is insufficient. |
| Failed since | Start of the current uninterrupted failure streak, with its build number. A window edge or missing/skipped predecessor makes this a lower bound. |
| New failure / resolved | Latest build failed/passed after the previous measured outcome passed/failed. Gaps can separate those observations. |
| Failure frequency | Failing builds divided by builds with a passing or failing observation; errors count as failures. |
| Duration regression | Latest passing duration is at least twice the median of at least three earlier passing build durations. |
| Coverage / timeline | Per-build XML counts and report error counts; pass/fail/skip/missing cells link to each Buildkite build. |

Identity is `(platform, relative XML path, suite, class, test name)`; job and build
UUIDs are excluded. Platforms remain separate. Renamed tests or report paths
start new histories. Repeated observations in one build retain all statuses and
job IDs in JSON, with a failure taking precedence in the timeline. Passing
durations are reduced to a per-build median so retries do not overweight the
historical baseline. Mixed results can indicate retries, repeated tests, or
identity collisions; cross-build changes can indicate regressions or fixes.
The flaky flag is therefore a triage signal, not proof of nondeterminism.

Missing and skipped results never imply a pass or recovery. Malformed XML and
rejected archives appear in report diagnostics (full details in JSON); zero-XML
builds remain visible. Transport/authentication errors abort the command rather
than silently publishing incomplete history. The command cannot infer which
tests an unreported job should have run, so inspect coverage before acting on
signals from partially reported builds.

Useful future additions include same-commit retry recovery rates, failure-reason
clusters, platform-specific failure comparisons, slowest tests and cumulative CI
time, and links to owners or quarantine decisions. These need job retry metadata,
stable ownership data, or agreed policy before they can become reliable actions.

## Requirements

- **Python 3** must be available on the host agent (`python3` in `PATH`).
- The agent must have IAM permissions (S3) or SSM-stored R2 credentials configured. See [Backend configuration](#backend-configuration).
- Test jobs must write JUnit XML before the `post-command` hook runs.
- Aggregate steps must depend on the test/reporting jobs whose uploaded XML they should include.

## Usage

### Job report, one test step

Configure a `job` block in each test job that produces JUnit XML. The `variant` identifies the platform/configuration and becomes the object-store grouping used by aggregate discovery.

```yaml
steps:
  - label: ":test_tube: linux haswell tests"
    key: test-linux-haswell
    command: ./run-tests.sh
    plugins:
      - bureau14/qdb-test-report#master:
          title: "Unit tests - linux haswell"
          job:
            variant: linux-haswell-release
            junit_input_path: reports/junit
            artifacts:
              - name: Test logs
                input_path: "test-logs-*.tar.gz"
```

`job.junit_input_path` can be:

- a directory, searched recursively for `*.xml`;
- a single XML file;
- a glob, such as `reports/**/*.xml`.

If the path does not exist or no XML files are found, the job report fails with a plugin error.

`job.artifacts` can optionally upload additional non-JUnit files, such as server logs or debug bundles. Each entry requires a `name` and `input_path`. The input path supports the same path styles as `junit_input_path` except directories upload all regular files recursively instead of filtering to XML. Missing or empty additional artifact inputs log a warning, are recorded in `summary.json`, and do not fail the report.

### Launcher execution manifests

Set `job.manifest_input_path: "test-metadata/*.json"` to collect results from the
QuasarDB CTest launcher. The path accepts a JSON file, a directory of JSON files,
or a glob. Existing `junit_input_path` and `artifacts` inputs continue to collect
CTest, query, and other reports that do not have manifests. At least one report
or manifest must be found. `Test execution artifacts` is a reserved artifact group.

Each version 1 manifest records `execution_id`, `name`, `status`, `exit_code`,
`reports`, and `artifacts`. Report and artifact entries contain a checkout-relative
`path`, a `role`, and a `required` flag. Directories in `artifacts` are collected
recursively, including binary dumps. Absolute paths, parent traversal, symlinks
outside the checkout, and files claimed by multiple executions are rejected.
The launcher writes the manifest atomically before spawning the test and updates
it with the runner PID, duration, and exit status. A hard kill can leave its status
as `running`; collection treats that as an interrupted execution. Manifests with
Buildkite build/job IDs belonging to another build/job are ignored.

The plugin collects the manifest itself, original reports, and all declared
artifacts into `logs.zip`. JUnit reports are copied into `junit.zip` with a
`qdb.execution_id` suite property; the original files remain unchanged and are
available as artifacts. The summary records that same ID on each artifact.
Both job and aggregate reports use the ID for exact associations, without PID
or filename matching. Legacy executions retain their existing matching behavior
and do not receive artifacts belonging to managed executions.

Missing, empty, or malformed required JUnit reports produce an errored launcher
result, with the original report retained when present. Interrupted executions
and unsuccessful processes whose XML contains no failure also produce an error
result. Valid XML that already describes a failed process is not duplicated.
Successful executions with no JUnit report declared receive a successful launcher
result. Optional missing logs and dumps are normal; missing required artifacts
produce an error result. These launcher errors follow `job.fail_on_test_failures`, just like malformed legacy JUnit XML. Aggregate steps need no additional configuration.

By default, job mode exits `64` when the report contains failed or errored tests. Disable that if your pipeline already handles test failures another way:

```yaml
plugins:
  - bureau14/qdb-test-report#master:
      title: "Unit tests - linux haswell"
      job:
        variant: linux-haswell-release
        junit_input_path: reports/junit
        fail_on_test_failures: false
```

### Aggregate report

Configure an empty `aggregate` block in a later step. The aggregate step discovers all raw XML uploaded by earlier job-report steps for the same Buildkite build.

```yaml
steps:
  - label: ":test_tube: linux haswell tests"
    key: test-linux-haswell
    command: ./run-tests.sh
    plugins:
      - bureau14/qdb-test-report#master:
          title: "Unit tests - linux haswell"
          job:
            variant: linux-haswell-release
            junit_input_path: reports/junit

  - label: ":test_tube: linux core2 tests"
    key: test-linux-core2
    command: ./run-tests.sh
    plugins:
      - bureau14/qdb-test-report#master:
          title: "Unit tests - linux core2"
          job:
            variant: linux-core2-release
            junit_input_path: reports/junit

  - label: ":bar_chart: Aggregate test report"
    key: aggregate-test-report
    depends_on:
      - test-linux-haswell
      - test-linux-core2
    allow_dependency_failure: true
    command: "true" # No-op; the plugin runs in the post-command hook.
    plugins:
      - bureau14/qdb-test-report#master:
          title: "Full test report"
          aggregate: {}
```

Aggregate mode only uses XML uploaded by job-report steps for the current build. It does not read local JUnit paths.

If no XML is discovered, aggregate mode:

- logs that no XML was found;
- creates an error-style Buildkite annotation when `annotate: true`;
- skips aggregate report upload;
- exits `0`.

### Generate a smaller failures-only report

Set `only_failures: true` in either mode to generate an HTML tree containing only failed/errored tests while keeping full summary counts:

```yaml
plugins:
  - bureau14/qdb-test-report#master:
      title: "Failures only"
      only_failures: true
      aggregate: {}
```

### Disable Buildkite annotation

Set `annotate: false` to skip creating the Buildkite annotation:

```yaml
plugins:
  - bureau14/qdb-test-report#master:
      title: "Unit tests - linux haswell"
      annotate: false
      job:
        variant: linux-haswell-release
        junit_input_path: reports/junit
```

## Configuration reference

### Top-level keys

| Key | Type | Required | Description |
| --- | --- | :---: | --- |
| `title` | string | ✓ | Report title shown in the HTML UI and annotation. |
| `job` | object | job or aggregate | Per-job report/XML upload configuration. Configure exactly one of `job` or `aggregate`. |
| `aggregate` | object | job or aggregate | Enables aggregate report mode. Configure exactly one of `job` or `aggregate`. |
| `execution_name` | string |  | Optional top-level execution name in the report. Defaults to the report title in the standalone generator. |
| `project_id` | string |  | Object-store project namespace. Defaults to `BUILDKITE_PIPELINE_SLUG`. |
| `only_failures` | boolean |  | Generate an HTML tree containing only failures/errors while keeping full summary counts. Default: `false`. |
| `annotate` | boolean |  | Create Buildkite annotation when a report URL can be built from `ARTIFACTS_DOMAIN`. Default: `true`. |
| `debug` | boolean |  | Enable bash debug tracing in plugin hooks. Default: `false`. |
| `log_level` | string |  | Minimum message severity: `debug`, `info`, `warning`, `error`, or `fatal`. Default: `error` (quiet; errors and fatal messages only). |
| `upload_parallel` | integer |  | Maximum simultaneous file uploads. Defaults to the agent's logical CPU count (or `1` if unavailable); use `1` for serial uploads. Applies to additional artifacts and HTML/XML uploads. |

### `job` object keys

| Key | Type | Required | Description |
| --- | --- | :---: | --- |
| `variant` | string | ✓ | Test variant name and object-store grouping, for example `linux-haswell-release`. |
| `junit_input_path` | string | Conditional | Local JUnit XML file, directory, or glob. Required unless `manifest_input_path` is set. |
| `manifest_input_path` | string |  | Optional version 1 launcher execution manifests (JSON file, directory, or glob). |
| `fail_on_test_failures` | boolean |  | Exit `64` when the generated job report contains failed or errored tests or malformed JUnit XML (legacy or manifest-owned). Default: `true`; `false` reports these errors without failing the step. |
| `artifacts` | array |  | Optional additional artifact groups to upload and link from the report. Each item requires `name` and `input_path`. Missing files warn but do not fail. |

### `aggregate` object keys

| Key | Type | Required | Description |
| --- | --- | :---: | --- |
| `download_parallel` | integer |  | Number of XML files to download in parallel after S3/R2 listing. Default: `32`. |
| `download_concurrency` | integer |  | Per-file boto3 transfer concurrency for XML downloads. Default: `4`. |

Set `log_level: info` to show progress, listing/download durations, and model/UI/HTML generation timings. Set `log_level: debug` for per-file parsing, test details, and duplicate decisions. Warnings remain in report metadata where applicable even when console output is quiet. `debug: true` independently enables shell tracing and can produce output at any log level.

Timing traces at `info` include environment setup (venv creation/upgrades and dependency installation), object-store configuration, XML discovery/downloads, direct/fallback summary collection, model/UI construction, JSON/HTML/summary writing, uploads, annotations, and the total report invocation. Python traces pair `trace start` and `trace end` by `id` and report `wall_s`, `thread_cpu_s`, and exception status. Shell traces report whole seconds and the command exit code; `hook.report` also includes Python startup/imports and temporary-directory cleanup. `plugin.total` starts after plugin configuration/logging and includes staging cleanup. Nested stages are inclusive, so do not add parent and child durations together. Thread CPU measures only the calling thread, not download workers or subprocesses; a large wall/CPU gap is a clue to waiting, not proof of network latency.

Use `log_level: debug` for individual XML parsing, S3 client creation, SSM requests (parameter names only), download keys, and outer retry attempts. Outer retry sleeps are traced at `info`; boto3's internal retries/timeouts are included in each attempt's wall time. Start with the largest `info` stage, then use its nested stages or `debug` traces to narrow it down. Setup currently recreates the environment on every checkout and summary downloads are serial; timings will show whether these costs matter on your agents. Trace logging preserves the default quiet `error` level and does not log credentials or full function arguments.

Uploads use up to `upload_parallel` workers, defaulting to the agent's logical CPU count and capped by the number of files, each owning a separate boto3 session and reused client. Per-file multipart transfers use no additional transfer threads, keeping simultaneous file uploads bounded. Additional artifacts finish before report generation so their links and metadata are available. HTML and job XML upload concurrently; `summary.json` is published last, after every required file succeeds. Upload failures retain the existing retries, fail the plugin, and cancel queued uploads; uploads already running finish before staging cleanup. Batch traces remain inclusive wall timings, while individual upload traces can overlap and must not be summed to obtain batch elapsed time.

One known source of long waits: a missing optional summary is retried like any other download failure before being skipped. The default outer retry schedule alone sleeps for 375 seconds (6 minutes 15 seconds) across ten attempts, excluding request time and boto3 retries. Serial summary collection can accumulate that delay per missing manifest. Look for `store.backoff` entries inside `aggregate.summaries.direct` to confirm whether this affects a run.

## Object-store layout

The plugin reuses the same object-store configuration path as the `qdb-artifacts` plugin. Configuration is resolved from `ARTIFACTS_*` environment variables or SSM parameters by `lib/object_store.py`.

Given destination `s3://bucket/prefix`, project `project`, git ref `refs/heads/main`, build `build-1`, variant `linux`, and job `job-1`, job-mode uploads are written under:

```text
prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/index.html
prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/summary.json
prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/xml/junit.zip
prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/artifacts/logs.zip
```

The job `summary.json` includes an `artifacts` array with ZIP object keys, public URLs when `ARTIFACTS_DOMAIN` is configured, member paths (`archive_member`), uncompressed member sizes, and warnings for configured artifact inputs that produced no files. ZIP links carry a `#zip-member=<encoded-path>` fragment identifying the original file. Job and aggregate HTML reports offer individual-file downloads and a ZIP download fallback. JUnit members retain their original relative paths; log members use `<artifact-name-slug>/<relative-artifact-path>`.

Individual-file downloads fetch the whole ZIP on demand and extract only the selected member in the browser. The two most recently used ZIPs are cached; no archives are fetched during report startup. The HTML embeds JSZip, so no CDN or extraction service is required. Fetches use the user's browser credentials and require same-origin access or credentialed CORS when the artifact domain differs. If authentication, network access, or extraction fails, the report displays a retry message and keeps the direct ZIP link available.

Browser extraction accepts at most 128 MiB of downloaded ZIP data, 10,000 parsed archive entries, and 64 MiB for the selected uncompressed file. Download size is enforced while reading the response, including when `Content-Length` is absent or incorrect. Fetching the archive, including its response body, has a 60-second deadline. Oversized or timed-out downloads show the reason and keep the direct ZIP link available; these limits do not prevent downloading the complete ZIP directly.

Aggregate mode discovers XML and job summaries under the current build's variants prefix:

```text
prefix/project/refs/heads/main/reports/builds/build-1/variants/*/jobs/*/xml/**/*.xml
prefix/project/refs/heads/main/reports/builds/build-1/variants/*/jobs/*/xml/junit.zip
prefix/project/refs/heads/main/reports/builds/build-1/variants/*/jobs/*/summary.json
```

Aggregate mode downloads each JUnit ZIP once and extracts its XML members into the variant/job staging directory. Legacy individual XML uploads remain supported. When both forms exist for a job, its ZIP takes precedence to avoid duplicate results.

JUnit ZIP extraction is streamed in 64 KiB chunks without fixed archive-size, member-count, XML-size, or total-extracted-size caps. Large valid JUnit inputs are included rather than rejected. The browser download limits above apply only to interactive individual-file extraction and do not gate report generation.

Corrupt, empty, unsafe, duplicate-member, or conflicting-path JUnit ZIPs are rejected per job without discarding valid sibling jobs. Partial extraction is removed before report generation. The HTML report and `summary.json` retain the rejected archive's object key, variant, job ID, error, and public download URL when available in `junit_archive_errors`. The report status and annotation are errors, and the plugin exits with status `1` after publishing the usable report—even when all archives were rejected or no public HTML URL is configured. Object-store transport errors still fail the invocation rather than being classified as invalid archive content.

The aggregate report is written under:

```text
prefix/project/refs/heads/main/reports/builds/build-1/full/index.html
prefix/project/refs/heads/main/reports/builds/build-1/full/summary.json
```

Successful aggregate summaries include discovered XML counts for variants, jobs, and XML files.
Aggregate leaf XML links always target the original contributing job XML objects, never the aggregate step's temporary downloaded files.

## Backend configuration

Config is resolved in order: **environment variable → SSM parameter → default**.

| Setting | Env var | SSM parameter | Default |
| --- | --- | --- | --- |
| Backend | `ARTIFACTS_BACKEND` | `/services/buildkite/config/artifacts/object-store/backend` | `s3` |
| Destination | `ARTIFACTS_DESTINATION` | `/services/buildkite/config/artifacts/object-store/destination` | _(required)_ |
| Endpoint URL | `ARTIFACTS_ENDPOINT_URL` | `/services/buildkite/config/artifacts/object-store/endpoint-url` | _(none)_ |
| R2 Account ID | `ARTIFACTS_R2_ACCOUNT_ID` | `/services/buildkite/config/artifacts/object-store/r2/account-id` | _(R2 only)_ |
| R2 Access Key ID | `ARTIFACTS_R2_ACCESS_KEY_ID` | `/services/buildkite/config/artifacts/object-store/r2/access-key-id` | _(R2 only)_ |
| R2 Secret Access Key | `ARTIFACTS_R2_SECRET_ACCESS_KEY` | `/services/buildkite/credentials/artifacts/r2/secret-access-key` | _(R2 only)_ |
| Artifacts domain | `ARTIFACTS_DOMAIN` | `/services/buildkite/config/artifacts/object-store/r2/artifacts-domain` | _(optional)_ |

For **AWS S3**, the agent's IAM role is used — no explicit credentials needed.

For **Cloudflare R2**, set `ARTIFACTS_BACKEND=r2` and provide the R2 credentials above.

## JUnit to HTML converter

The plugin uses a custom script to generate HTML reports from JUnit XML. The script is located at `tools/junit_html_report.py` and can be used independently of Buildkite.

Basic usage for a single platform report:

```bash
python3 tools/junit_html_report.py \
  --title "Build #1234" \
  --platform linux=reports/linux \
  --output report.html
```

Using filtering, summary JSON, and build-system metadata:

```bash
python3 tools/junit_html_report.py \
  --title "CI Pipeline / Build #1234" \
  --platform linux=./results/linux \
  --platform macos=./results/macos \
  --output test-report.html \
  --summary-json summary.json \
  --only-failures \
  --fail-on-test-failures \
  --build-url "https://buildkite.example/builds/1234" \
  --commit-url "https://github.com/acme/project/commit/abc123"
```

### CLI reference

| Option | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `--title` | Yes | - | Report title/root node name. |
| `--platform` | Yes | - | Input in `name=path` form. May be repeated. `path` may be a single XML file or a directory searched recursively for `*.xml`. |
| `--output` | Yes | - | Output HTML file path. |
| `--summary-json` | No | - | Optional output summary JSON file path. |
| `--template` | No | `tools/templates/report-template.html` | Path to custom HTML template. |
| `--execution-name` | No | Title | Top-level OTR UI execution name. |
| `--build-url` | No | - | Buildkite build URL metadata. |
| `--commit-url` | No | - | Git commit URL metadata. |
| `--only-failures` | No | `false` | Filter report to only show `FAILED`/`ERRORED` tests in the tree while keeping full summary counts. |
| `--fail-on-test-failures` | No | `false` | Exit code `64` if any test has status `FAILED` or `ERRORED`. |
| `--log-level` | No | `error` | Minimum message severity: `debug`, `info`, `warning`, `error`, or `fatal`. Use `info` for progress and phase timings, or `debug` for per-file details. |

The standalone converter is quiet by default; errors are written to stderr. Empty XML files are skipped with warnings visible at `warning` or more verbose levels. Malformed XML files emit errors and are recorded in `summary.json` so the Buildkite plugin can fail the build and annotate the invalid inputs. If no XML files are discovered across all configured inputs, it still writes an empty report and logs a warning when enabled.

Boost.Test cases skipped with a diagnostic chain ending in the exact reason
`disabled` are omitted during report-model ingestion. These are filtered-out or
default-disabled tests. Runtime skips, unknown skip diagnostics, failures, and
fixture errors remain visible. Job and aggregate counts are derived from the
retained cases, while source XML and execution-manifest artifact associations
remain intact. No additional manifest metadata is required.

## Licensing and Attribution

- This project includes a vendored and modified version of the **Open Test Reporting (OTR) UI**, licensed under the **Apache License 2.0**. The original license is at `ui/LICENSE.md`.
