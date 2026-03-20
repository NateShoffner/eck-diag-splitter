# eck-diag-splitter

Split ECK diagnostic dumps into separate zip files per Elasticsearch instance and optionally patch and minify JSON files to help mitigate analysis failures.

## Requirements

- Python 3.10+
- No third-party dependencies

## Quick Start

```bash
python patch.py <path-to-input-zip> [--patch] [--minify]
```

## Flags

- `--patch`: Patches known problematic JSON files containing prototype pollution patterns that break analysis tools.
- `--minify`: Minify all `*.json` files to reduce file size and mitigate analysis failures due to large JSON files.

# Disclaimer

This tool is provided as-is without any warranties. Use at your own risk. Always review the output files before sharing or using them for analysis.

## Known Issues

- Nodes within the analysis tool may not populate accordingly due to missing or altered metadata in the split files.