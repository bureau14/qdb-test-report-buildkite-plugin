# Buildkite Test Report Plugin

A [Buildkite plugin](https://buildkite.com/docs/plugins) for generating self-contained JUnit HTML reports, publishing them to S3/R2-compatible object storage, and adding Buildkite annotations that link to the uploaded reports.

## What it does

- **Job** — after each test step finishes, reads that job's local JUnit XML, generates a per-job HTML report, uploads the HTML/summary/raw XML, and optionally fails the step when tests failed.
- **Aggregate** — in a later reporting step, downloads XML uploaded by earlier job steps for a list of variants, generates one aggregate HTML report, and uploads the aggregate HTML/summary.

The two modes use separate top-level configuration blocks:

- `job` uses one local `junit_reports_path` and one `variant`.
- `aggregate` uses a list of `variants` and does not read local test output paths.

Common report options such as `title`, `only_failures`, `annotate`, and `project_id` stay at the plugin top level.

The plugin runs from the Buildkite `post-command` hook, so reports are still published after the step command exits with a failure.

The plugin exits `64` when `job.fail_on_test_failures` is true and the generated job report contains failed or errored tests. It exits `1` for internal plugin errors and otherwise exits `0` so Buildkite can preserve the original command status.

## Requirements

- **Python 3** must be available on the host agent (`python3` in `PATH`).
- The agent must have IAM permissions (S3) or SSM-stored R2 credentials configured. See [Backend configuration](#backend-configuration).
- Test jobs must write JUnit XML before the `post-command` hook runs.

## Usage

### Job report, one test step

Configure a `job` block in each test job that produces JUnit XML. The `variant` identifies the platform/configuration and becomes the object-store prefix used by later aggregate reports.

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
            junit_reports_path: reports/junit
```

`job.junit_reports_path` can be:

- a directory, searched recursively for `*.xml`;
- a single XML file;
- a glob, such as `reports/**/*.xml`.

If the path does not exist or no XML files are found, the job report fails with a plugin error.

By default, job mode exits `64` when the report contains failed or errored tests. Disable that if your pipeline already handles test failures another way:

```yaml
plugins:
  - bureau14/qdb-test-report#master:
      title: "Unit tests - linux haswell"
      job:
        variant: linux-haswell-release
        junit_reports_path: reports/junit
        fail_on_test_failures: false
```

### Aggregate report, multiple variants

Configure an `aggregate` block after the test jobs. The plugin downloads XML uploaded by earlier `job` steps for each configured variant and generates one aggregate report.

```yaml
steps:
  - label: ":bar_chart: Aggregate test report"
    key: aggregate-test-report
    depends_on:
      - test-linux-haswell
      - test-linux-core2
    allow_dependency_failure: true
    command: "true" # No-op; the plugin runs in the post-command hook.
    plugins:
      - bureau14/qdb-test-report#master:
          title: "Aggregate unit test report"
          aggregate:
            variants:
              - linux-haswell-release
              - linux-core2-release
```

Aggregate mode does not accept `junit_reports_path` or `fail_on_test_failures`: it is a reporting step, not a test-execution step. If no XML is found for a configured variant, the plugin warns and adds that warning to the summary/annotation. Aggregate reports only use XML from the current build.

### Per-variant aggregate report

Usually an aggregate report is uploaded under the build-level aggregate path. If you want the report URL grouped under a specific variant, set `aggregate.variant`:

```yaml
plugins:
  - bureau14/qdb-test-report#master:
      title: "Linux aggregate test report"
      aggregate:
        variant: linux
        variants:
          - linux-haswell-release
          - linux-core2-release
```

This only changes where the aggregate HTML/summary are uploaded; the variants to aggregate still come from `aggregate.variants`.

### Generate a smaller failures-only report

Set `only_failures: true` in either mode to generate an HTML tree containing only failed/errored tests while keeping full summary counts:

```yaml
plugins:
  - bureau14/qdb-test-report#master:
      title: "Failures only"
      only_failures: true
      aggregate:
        variants:
          - linux-haswell-release
          - linux-core2-release
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
        junit_reports_path: reports/junit
```

## Configuration reference

### Top-level keys

| Key | Type | Required | Description |
| --- | --- | :---: | --- |
| `title` | string | ✓ | Report title shown in the HTML UI and annotation. |
| `job` | object | job or aggregate | Per-job report/XML upload configuration. Configure exactly one of `job` or `aggregate`. |
| `aggregate` | object | job or aggregate | Aggregate report configuration. Configure exactly one of `job` or `aggregate`. |
| `execution_name` | string |  | Optional top-level execution name in the report. Defaults to the report title in the standalone generator. |
| `project_id` | string |  | Object-store project namespace. Defaults to `BUILDKITE_PIPELINE_SLUG`. |
| `only_failures` | boolean |  | Generate an HTML tree containing only failures/errors while keeping full summary counts. Default: `false`. |
| `annotate` | boolean |  | Create Buildkite annotation when a report URL can be built from `ARTIFACTS_DOMAIN`. Default: `true`. |
| `debug` | boolean |  | Enable bash debug tracing in plugin hooks. Default: `false`. |

### `job` object keys

| Key | Type | Required | Description |
| --- | --- | :---: | --- |
| `variant` | string | ✓ | Test variant name and XML upload prefix, for example `linux-haswell-release`. |
| `junit_reports_path` | string | ✓ | Local JUnit XML file, directory, or glob to read from the test job. |
| `fail_on_test_failures` | boolean |  | Exit `64` when the generated job report contains failed or errored tests. Default: `true`. |

### `aggregate` object keys

| Key | Type | Required | Description |
| --- | --- | :---: | --- |
| `variants` | array of strings | ✓ | Variant names to search in object storage for XML uploaded by job-mode runs. |
| `variant` | string |  | Optional variant grouping for the aggregate report upload/annotation URL. Does not change which XML is aggregated. |

## Object-store layout

The plugin reuses the same object-store configuration path as the `qdb-artifacts` plugin. Configuration is resolved from `ARTIFACTS_*` environment variables or SSM parameters by `lib/object_store.py`.

Given destination `s3://bucket/prefix`, project `project`, git ref `refs/heads/main`, build `build-1`, variant `linux`, and job `job-1`, job-mode uploads are written under:

```text
prefix/project/refs/heads/main/reports/variants/linux/builds/build-1/jobs/job-1/index.html
prefix/project/refs/heads/main/reports/variants/linux/builds/build-1/jobs/job-1/summary.json
prefix/project/refs/heads/main/reports/variants/linux/builds/build-1/jobs/job-1/xml/linux/<relative-junit-path>.xml
```

Aggregate mode looks for XML uploaded by earlier job-mode runs under:

```text
prefix/project/refs/heads/main/reports/variants/<variant>/builds/<build_id>/jobs/*/xml/<variant>/**/*.xml
```

An aggregate report without `aggregate.variant` is written under:

```text
prefix/project/refs/heads/main/reports/builds/build-1/full/index.html
prefix/project/refs/heads/main/reports/builds/build-1/full/summary.json
```

A per-variant aggregate report with `aggregate.variant: linux` is written under:

```text
prefix/project/refs/heads/main/reports/variants/linux/builds/build-1/full/index.html
prefix/project/refs/heads/main/reports/variants/linux/builds/build-1/full/summary.json
```

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

The standalone converter writes progress and summary details to stderr. Malformed or empty XML files are skipped with warnings. If no XML files are discovered across all configured inputs, it still writes an empty report and logs a warning.

## Licensing and Attribution

- This project includes a vendored and modified version of the **Open Test Reporting (OTR) UI**, licensed under the **Apache License 2.0**. The original license is at `ui/LICENSE.md`.
