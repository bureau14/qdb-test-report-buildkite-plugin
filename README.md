# Buildkite Test Report Plugin

This plugin generates self-contained JUnit HTML reports, publishes them to S3/R2-compatible object storage, and creates small Buildkite annotations that link to the uploaded HTML report.

## Runtime model

```text
test job
  -> writes JUnit XML locally
  -> qdb-test-report scope=job generates job HTML and summary JSON
  -> plugin uploads job HTML, summary JSON, and raw XML

full report job
  -> qdb-test-report scope=full lists job XML objects for the current build
  -> plugin downloads XML into .buildkite-test-report/downloaded-xml/
  -> plugin generates aggregate HTML and summary JSON
  -> plugin uploads full HTML and summary JSON
```

The plugin runs from the Buildkite `post-command` hook. It will publish reports even after command fails.

Plugin exits `64` when `fail_on_test_failures` is true and any test fails/errors, exits `1` for internal plugin errors, and otherwise exits `0` so Buildkite can preserve the original command status.

## Object-store configuration

The plugin reuses the same object-store configuration path as the `qdb-artifacts` plugin. Configuration is resolved from `ARTIFACTS_*` environment variables or SSM parameters by `lib/object_store.py`.

Important full-scope rules:

- Full reports only aggregate XML from the current `project_id`, `git_ref`, and `build_id`.
- There is no `LATEST_SUCCESSFUL` lookup.
- There is no main/master branch fallback.
- Full-scope aggregation looks for XML uploaded by earlier `scope: job` runs under `reports/variants/<variant>/builds/<build_id>/jobs`.
- The full step uses `platforms[].name` as the list of variants to search in object storage.
- If no XML is found for a configured variant, the plugin warns and adds a warning to the summary/annotation. This usually means a job failed before publishing XML. Full reports do not fall back to another build.

## Uploaded object layout

Given destination `s3://bucket/prefix`, project `project`, git ref `refs/heads/main`, build `build-1`, variant `linux`, and job `job-1`, job-scope uploads are written under:

```text
prefix/project/refs/heads/main/reports/variants/linux/builds/build-1/jobs/job-1/index.html
prefix/project/refs/heads/main/reports/variants/linux/builds/build-1/jobs/job-1/summary.json
prefix/project/refs/heads/main/reports/variants/linux/builds/build-1/jobs/job-1/xml/<platform>/<relative-junit-path>.xml
```

A full report without `variant` is written under:

```text
prefix/project/refs/heads/main/reports/builds/build-1/full/index.html
prefix/project/refs/heads/main/reports/builds/build-1/full/summary.json
```

A per-variant full report with `variant: linux` is written under:

```text
prefix/project/refs/heads/main/reports/variants/linux/builds/build-1/full/index.html
prefix/project/refs/heads/main/reports/variants/linux/builds/build-1/full/summary.json
```

## Plugin parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `scope` | string | Required. Either `job` or `full`. |
| `title` | string | Required. Report title shown in the HTML UI and annotation. |
| `platforms` | array | Required. List of `{name, path}` objects. For `scope: job`, `path` is a local XML file, XML directory, or glob. For `scope: full`, `name` selects object-store variants to download; configured `path` values are replaced with the full-scope staging paths after download. |
| `variant` | string | Required for `scope: job`. Optional for a per-variant full report and for per-variant annotation/upload paths. |
| `execution_name` | string | Optional top-level execution name in the report. Defaults to the report title in the standalone generator. |
| `project_id` | string | Object-store project namespace. Defaults to `BUILDKITE_PIPELINE_SLUG`. |
| `only_failures` | boolean | Generate an HTML tree containing only failures/errors while keeping full summary counts. Default `false`. |
| `annotate` | boolean | Create Buildkite annotation when a report URL can be built from `ARTIFACTS_DOMAIN`. Default `true`. |
| `fail_on_test_failures` | boolean | Exit `64` when the generated report contains any failed or errored tests. Defaults to `true` for job reports and `false` for full reports. |
| `debug` | boolean | Enable bash debug tracing in plugin hooks. Default `false`. |

## Job-scope example

Use `scope: job` in each test job that produces JUnit XML. The job report is available as soon as that job finishes. In job scope, missing platform paths or paths with no XML files will result in errors.

```yaml
steps:
  - label: ":test_tube: linux haswell tests"
    key: test-linux-haswell
    command: ./run-tests.sh
    plugins:
      - bureau14/qdb-test-report#v0.1.0:
          scope: job
          variant: linux-haswell-release
          title: "Unit tests - linux haswell"
          platforms:
            - name: linux-haswell-release
              path: reports/junit
```

## Full-scope aggregate example

Use `scope: full` after the test jobs. The plugin downloads XML uploaded by the earlier `scope: job` steps from object storage.

```yaml
steps:
  - label: ":bar_chart: Full test report"
    key: full-test-report
    depends_on: # Tests that contribute to the full report.
      - test-linux-haswell
      - test-linux-core2
    allow_dependency_failure: true  # Don't fail the full report step if test jobs fail
    command: "true" # No-op since the plugin runs in the post-command hook
    plugins:
      - bureau14/qdb-test-report#v0.1.0:
          scope: full
          title: "Full unit test report"
          platforms:
            - name: linux-haswell-release
              path: reports/linux-haswell-release
            - name: linux-core2-release
              path: reports/linux-core2-release
```

For a full run, the `path` values are not used as the source of truth for aggregation. The plugin stages downloaded XML under:

```text
.buildkite-test-report/downloaded-xml/<variant>/<job_id>/<relative-junit-path>.xml
```

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

The standalone converter writes progress and summary details to stderr. Malformed or empty XML files are skipped with warnings. If no XML files are discovered across all platforms, it still writes an empty report and logs a warning.

## Licensing and Attribution

- This project includes a vendored and modified version of the **Open Test Reporting (OTR) UI**, licensed under the **Apache License 2.0**. The original license is at `ui/LICENSE.md`.
