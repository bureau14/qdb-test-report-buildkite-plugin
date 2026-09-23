# Buildkite Test Report Plugin

A [Buildkite plugin](https://buildkite.com/docs/plugins) for generating self-contained JUnit HTML reports, publishing them to S3/R2-compatible object storage, and adding Buildkite annotations that link to the uploaded reports.

## What it does

- **Job report** — after a test step finishes, reads that job's local JUnit XML from `job.junit_input_path`, generates a per-job HTML report, uploads the HTML/summary/raw XML, and optionally fails the step when tests failed.
- **Aggregate report** — in a later reporting step, discovers XML uploaded by earlier job-report steps for the current build, downloads it, generates one aggregate HTML report, and uploads the aggregate HTML/summary.

Each platform-execution leaf is labeled `{test name} - {platform}`, preserving test identity in the sidebar and detail header. When `ARTIFACTS_DOMAIN` is configured, its Source panel links `JUnit XML` directly to the exact raw XML that produced the selected execution. Without a browser-facing artifacts domain, the XML name remains visible but is not made clickable.

The self-contained report supports case-insensitive sidebar search without a server. It also updates the browser URL to `#node=<id>` for the selected report node; share that full URL to open the same static report with the node selected, its path expanded, and the sidebar scrolled to it. Node IDs are specific to the generated report file.

Configure exactly one mode per plugin invocation:

- `job` requires `variant` and `junit_input_path`.
- `aggregate` enables full-build report mode; optional download settings tune aggregate XML fetch concurrency.

Common report options such as `title`, `only_failures`, `annotate`, and `project_id` stay at the plugin top level.

Job and aggregate annotations separate failed and errored executions into two tables. The Boost.Test/test-runner table shows Suite / report, test case, failure reason, and execution time. Suite / report displays the suite name once when it equals the XML report filename stem; otherwise it displays `suite::report`. This affects only the label, preserving internal grouping and deduplication keys. The CTest table shows test case (without the repeated class name), failure reason, and execution time. Execution time is shown in seconds to three decimal places in the final column; missing durations in older summaries appear as a dash. Neither table includes status, targets, or XML links. Errored executions have an `ERRORED:` prefix in the failure reason; ordinary failures have no prefix. Failure reasons are flattened to one line and capped at 240 characters, including the prefix; missing reasons appear as a dash. Each test case appears once, using the reason and execution time from its first reported failing or errored target. All target executions remain available in the full report. Both tables share Buildkite's 1 MiB annotation limit, with a count of omitted test cases when necessary. The summary and full-report link retain their space in the annotation.

The plugin runs from the Buildkite `post-command` hook, so reports are still published after the step command exits with a failure.

The plugin exits `64` when `job.fail_on_test_failures` is true and the generated job report contains failed or errored tests. It exits `1` when any discovered JUnit XML is malformed and creates an error annotation listing the malformed files when `annotate: true`. When the HTML report is available through `ARTIFACTS_DOMAIN`, that annotation includes its link; if the report is unavailable, it still creates the error annotation without a link. When the original job command exits non-zero but every reported test passes, the plugin creates a warning annotation explaining the mismatch, even without `ARTIFACTS_DOMAIN`. It also exits `1` for other internal plugin errors and otherwise exits `0` so Buildkite can preserve the original command status. Aggregate mode exits `0` when no XML is discovered, but creates an error-style annotation unless `annotate: false` is set.

## Requirements

- **Python 3.7 or newer** must be available on the host agent (`python3` in `PATH`).
- Manifest validation uses pure-Python fastjsonschema; no Rust compiler is required. Python 3.7 agents use the compatible Boto3 1.33 series, while newer agents retain normal dependency resolution.
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

### `job` object keys

| Key | Type | Required | Description |
| --- | --- | :---: | --- |
| `variant` | string | ✓ | Test variant name and object-store grouping, for example `linux-haswell-release`. |
| `junit_input_path` | string | ✓ | Local JUnit XML file, directory, or glob to read from the test job. |
| `manifest_input_path` | string | | Optional execution manifest file or glob; enables exact-path artifact uploads and incomplete-execution reporting. |
| `fail_on_test_failures` | boolean |  | Exit `64` when the generated job report contains failed or errored tests. Default: `true`. |
| `artifacts` | array |  | Optional additional artifact groups to upload and link from the report. Each item requires `name` and `input_path`. Missing files warn but do not fail. |

### `aggregate` object keys

| Key | Type | Required | Description |
| --- | --- | :---: | --- |
| `download_parallel` | integer |  | Number of XML files to download in parallel after S3/R2 listing. Default: `32`. |
| `download_concurrency` | integer |  | Per-file boto3 transfer concurrency for XML downloads. Default: `4`. |

The aggregate step logs listing and download durations separately so slow object-store listing can be distinguished from many-small-file download time.

## Object-store layout

The plugin reuses the same object-store configuration path as the `qdb-artifacts` plugin. Configuration is resolved from `ARTIFACTS_*` environment variables or SSM parameters by `lib/object_store.py`.

Given destination `s3://bucket/prefix`, project `project`, git ref `refs/heads/main`, build `build-1`, variant `linux`, and job `job-1`, job-mode uploads are written under:

```text
prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/index.html
prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/summary.json
prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/xml/<relative-junit-path>.xml
prefix/project/refs/heads/main/reports/builds/build-1/variants/linux/jobs/job-1/artifacts/<artifact-name-slug>/<relative-artifact-path>
```

The job `summary.json` includes an `artifacts` array with uploaded artifact keys, public URLs when `ARTIFACTS_DOMAIN` is configured, sizes, and warnings for configured artifact inputs that produced no files. Job and aggregate HTML reports render these links in the report-level Artifacts section and in each test leaf's Source section beside the Buildkite job/JUnit XML links. The JUnit XML link targets the raw uploaded object and retains its `attachment` disposition.

Aggregate mode discovers XML and job summaries under the current build's variants prefix:

```text
prefix/project/refs/heads/main/reports/builds/build-1/variants/*/jobs/*/xml/**/*.xml
prefix/project/refs/heads/main/reports/builds/build-1/variants/*/jobs/*/summary.json
```

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

The standalone converter writes progress and summary details to stderr. Empty XML files are skipped with warnings. Malformed XML files are recorded in `summary.json` so the Buildkite plugin can fail the build and annotate the invalid inputs. If no XML files are discovered across all configured inputs, it still writes an empty report and logs a warning.

## Licensing and Attribution

- This project includes a vendored and modified version of the **Open Test Reporting (OTR) UI**, licensed under the **Apache License 2.0**. The original license is at `ui/LICENSE.md`.

### QDB executable metadata

Boost.Test producers can put a single versioned JSON record in the suite-level
`<system-out>` (not in a testcase):

```text
QDB_TEST_METADATA {"version":1,"pid":90560,"log_path":"test_log/qdb_test_log_pid_90560_1724412755000000000.json"}
```

`pid` is a positive integer. Omit `log_path` when the executable has no JSON
logger. The path uses `/` separators and is relative to `PROJECT_ROOT`, or the
producer's working directory when `PROJECT_ROOT` is unset. Configure artifact
uploads so their recorded relative paths match; the existing
`test_log/qdb_test_log_pid_*.json` glob preserves this path.

The report matches the explicit path only against artifacts from the XML's
originating job. A missing upload produces a warning, without falling back to
another file with the same PID. Without a path, PID matching remains available.
Older reports using the `qdb_test_process_id` testcase remain supported. Invalid
or unsupported metadata is ignored with a warning; conflicting records are not
assigned to cases. The linked JSON is the whole executable's log, shared by its
cases, and does not create an extra testcase.

## Execution manifests

The job.manifest_input_path option accepts a checkout-relative file or glob, for
example test-metadata/*.json. The versioned contract is
[execution-manifest-v1.schema.json](schemas/execution-manifest-v1.schema.json);
a complete producer example is in [schemas/examples](schemas/examples).

A launcher owns one manifest per JUnit destination. It writes the initial running
record **before** launching the test, and atomically replaces it with completed,
failed, or aborted plus the exit code after execution and cleanup. On a retry
it replaces that destination's manifest and results; execution_id identifies the
new invocation. A forced kill may leave running, which the reporter treats as an
incomplete execution. Artifact paths can be declared before files exist, allowing
server archives to be packaged afterward.

Paths use forward slashes and are relative to the checkout root, not the manifest
directory. Absolute paths, traversal, duplicate JUnit claims, and symlinks escaping
the checkout are rejected. Every declared file that exists is uploaded automatically;
no artifact glob is needed for managed executions. Missing required artifacts are
shown in execution details; optional crash dumps can set required to false.
The original manifest is uploaded as an attachment too.

For a manifested report, matching uses the originating CI job and exact artifact
path only. PID and JUnit filename inference are disabled. Processes, exit status,
and execution ID appear in the report's Execution section. Server PIDs may use a
shell PID namespace on Windows; they are descriptive, never matching keys.

Missing, empty or malformed JUnit creates an infrastructure error with the
execution's available attachments. A nonzero exit with otherwise successful JUnit,
or an unfinished/aborted execution, is also visible. Aggregate reports discover
job summaries even when the job uploaded no XML. Validated manifests are retained
in those summaries so aggregate reports preserve the same associations.

Reports without a manifest retain the legacy JUnit metadata / PID / filename
fallbacks during migration. Unsupported manifest versions or invalid manifests
fail validation instead of silently falling back. Producers should validate their
fixtures against this schema before changing the contract.
