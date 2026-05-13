# qdb-test-report-buildkite-plugin

## JUNIT to HTML Converter

Basic usage for a single platform report:

```bash
.venv/bin/python tools/junit_html_report.py \
  --title "Build #1234" \
  --platform linux=reports/linux \
  --output report.html
```

Using filtering and build-system integration:

```bash
.venv/bin/python tools/junit_html_report.py \
  --title "CI Pipeline / Build #1234" \
  --platform linux=./results/linux \
  --platform macos=./results/macos \
  --output test-report.html \
  --only-failures \
  --fail-on-status failed \
  --build-url "https://buildkite.example/builds/1234" \
  --commit abc123 \
  --branch main
```

### CLI Reference

| Option | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `--title` | Yes | - | Report title/root node name. |
| `--platform` | Yes | - | Input in `name=path` form. May be repeated. |
| `--output` | Yes | - | Output HTML file path. |
| `--template` | No | `templates/report-template.html` | Path to custom HTML template. |
| `--execution-name` | No | Title | Top-level OTR UI execution name. |
| `--build-url` | No | - | Buildkite build URL metadata. |
| `--commit` | No | - | Commit SHA metadata. |
| `--branch` | No | - | Branch metadata. |
| `--only-failures` | No | - | Filter report to only show `FAILED`/`ERRORED` tests in the tree. |
| `--fail-on-status` | No | `failed` | Exit code 64 if root status matches (`failed`, `errored`, `never`). |

## Licensing and Attribution

- This project includes a vendored and modified version of the **Open Test Reporting (OTR) UI**, licensed under the **Apache License 2.0**. The original license is at `ui/LICENSE.md`.
