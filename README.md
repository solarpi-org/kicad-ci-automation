# KiCAD CI/CD Automation

[![CI](https://github.com/solarpi-org/kicad-ci-automation/actions/workflows/ci.yml/badge.svg)](https://github.com/solarpi-org/kicad-ci-automation/actions/workflows/ci.yml)
[![SBOM](https://img.shields.io/badge/SBOM-CycloneDX%20%7C%20SPDX-blue)](https://github.com/solarpi-org/kicad-ci-automation/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Automated CI/CD pipeline for KiCAD projects with ERC, DRC, ODB++ export, visual diffs, and SBOM generation.

## Features

- **Electrical Rules Check (ERC)**: Validates schematic electrical connections
- **Design Rules Check (DRC)**: Validates PCB layout against design rules
- **ODB++ Export**: Generates industry-standard manufacturing files
- **Visual Diff**: Creates triptych overlays comparing PCB/schematic versions (purple = removed, green = added)
- **Template Replacement**: Substitutes KiCAD text variables from a defines file before running checks
- **SBOM Generation**: Produces CycloneDX and SPDX software bills of materials via [sbomnix](https://github.com/tiiuae/sbomnix)

## Quick Start

### As a Reusable GitHub Actions Workflow

This is the intended usage — add to your KiCAD project repo:

```yaml
# .github/workflows/kicad-ci.yml
name: KiCAD CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  release:
    types: [published]

jobs:
  kicad-ci:
    uses: solarpi-org/kicad-ci-automation/.github/workflows/kicad-ci.yml@main
    with:
      project-path: .
      enable-diff: true
      # defines-file: defines.json   # uncomment if using template replacement
    secrets: inherit
    permissions:
      contents: write
      pull-requests: write
```

This gives you:
- **Push/PR**: ERC + DRC + ODB++ export, with PR comments summarizing violations
- **PR**: Visual diff against the base branch (triptych PDFs)
- **Release**: All of the above + SBOM attached as release artifacts

### Running Locally

```bash
# Run full pipeline
nix run github:solarpi-org/kicad-ci-automation -- --help

# Run on a specific project
nix run github:solarpi-org/kicad-ci-automation -- -p ./my-board -c main

# Generate SBOM only
nix run github:solarpi-org/kicad-ci-automation#generate-sbom
```

### Development Shell

```bash
nix develop github:solarpi-org/kicad-ci-automation
kicad-ci --help
```

## Usage

```
kicad-ci [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `-p, --project DIR` | Project directory (default: current directory) |
| `-o, --output DIR` | Output directory (default: `./ci-output`) |
| `-c, --compare REF` | Git reference to compare against for visual diff |
| `-d, --defines FILE` | Template definitions file (JSON, YAML, or KEY=VALUE) |
| `-n, --prefix PREFIX` | Prefix for output filenames (e.g. `pr-42-abc1234`) |
| `--skip-erc` | Skip Electrical Rules Check |
| `--skip-drc` | Skip Design Rules Check |
| `--skip-odb` | Skip ODB++ export |
| `--skip-diff` | Skip visual diff generation |
| `--skip-template` | Skip template placeholder replacement |
| `--exit-on-error` | Exit immediately on first error (default: continue all checks) |
| `-h, --help` | Show help message |

### Examples

```bash
# Run all checks on current directory
kicad-ci

# Run checks with comparison against main branch
kicad-ci -p ./my-board -c main

# Run only ERC and DRC
kicad-ci --skip-odb --skip-diff

# Run with template replacement
kicad-ci -d defines.json

# Run with prefixed output filenames
kicad-ci -n "v1.0-abc1234" -o ./build
```

## Output Structure

Output files are named `[prefix-]boardname-suffix.ext`:

```
ci-output/
├── [prefix-]boardname-erc-report.json    # ERC violations
├── [prefix-]boardname-erc.log            # ERC execution log
├── [prefix-]boardname-drc-report.json    # DRC violations
├── [prefix-]boardname-drc.log            # DRC execution log
├── [prefix-]boardname-odb.zip            # ODB++ manufacturing files
├── [prefix-]boardname-odb.log            # ODB++ export log
├── [prefix-]boardname-diff.log           # Visual diff log
├── [prefix-]boardname-pcb-diff.pdf       # Combined PCB layer differences
├── [prefix-]boardname-schematic-diff.pdf # Combined schematic differences
└── artifacts-boardname/                  # Intermediate diff artifacts
    ├── triptych-svgs/                    # Individual layer triptych SVGs
    │   ├── pcb-*.svg
    │   └── sch-*.svg
    └── pdfs/                             # Individual layer PDFs
```

## Visual Diff — Triptych Method

The visual diff overlays old and new versions with color tinting:

- **Purple**: Old/removed content (complementary tint, full opacity)
- **Green**: New/added content (green tint, 50% group opacity)
- **Blended**: Areas where both versions overlap

All output is fully vector — PDFs can be zoomed infinitely without pixelation.

## SBOM Generation

Generate a Software Bill of Materials for the kicad-ci runtime closure:

```bash
# Generate in current directory
nix run .#generate-sbom

# Generate in a specific directory
nix run .#generate-sbom -- ./my-sbom-dir
```

Produces CycloneDX (`.cdx.json`), SPDX (`.spdx.json`), and CSV formats. The SBOM is cached based on the Nix store hash — regeneration is skipped when the closure hasn't changed.

On releases, SBOMs are automatically attached as GitHub release artifacts.

## Reusable Workflow Inputs

| Input | Type | Default | Description |
|-------|------|---------|-------------|
| `project-path` | string | `.` | Path to KiCAD project within the repo |
| `enable-diff` | boolean | `true` | Run visual diff on pull requests |
| `defines-file` | string | `""` | Template defines file path (auto-detected if empty) |
| `kicad-ci-ref` | string | `main` | Git ref of kicad-ci-automation to use |

## Requirements

- Nix with flakes enabled
- KiCAD project files (`*.kicad_sch`, `*.kicad_pcb`)
- Git repository (for visual diff and template replacement)

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for the full text.

### Dependencies

- [KiCad-Diff](https://github.com/Gasman2014/KiCad-Diff) (MIT) — Visual diff tool for KiCad PCBs. Uses a [Nix-packaged fork](https://github.com/murdoa/KiCad-Diff).
- [sbomnix](https://github.com/tiiuae/sbomnix) (Apache-2.0) — SBOM generation for Nix packages.
