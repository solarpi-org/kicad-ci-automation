# KiCAD CI/CD Automation

Automated CI/CD pipeline for KiCAD projects with ERC, DRC, ODB++ export, and visual diff generation.

## Features

- **Electrical Rules Check (ERC)**: Validates schematic electrical connections
- **Design Rules Check (DRC)**: Validates PCB layout against design rules
- **ODB++ Export**: Generates industry-standard manufacturing files
- **Visual Diff**: Creates visual comparisons between PCB versions using kicad-diff
- **PDF Artifacts**: Automatically generates triptych SVGs and combined PDFs showing layer-by-layer differences

## Quick Start

### Using Nix Flakes

Run the CI pipeline directly:

```bash
nix run .
```

Run with options:

```bash
nix run . -- --help
nix run . -- -p ./my-project -c HEAD~1
```

### Development Shell

Enter a development shell with all tools available:

```bash
nix develop
kicad-ci --help
```

## Usage

```bash
kicad-ci [OPTIONS]
```

### Options

- `-p, --project DIR`: Project directory (default: current directory)
- `-o, --output DIR`: Output directory (default: ./ci-output)
- `-c, --compare REF`: Git reference to compare against (for kicad-diff)
- `--skip-erc`: Skip Electrical Rules Check
- `--skip-drc`: Skip Design Rules Check
- `--skip-odb`: Skip ODB++ export
- `--skip-diff`: Skip visual diff generation
- `--exit-on-error`: Exit immediately on first error (default: continue all checks)
- `-h, --help`: Show help message

### Examples

#### Run all checks on current directory

```bash
kicad-ci
```

#### Run checks on specific project with Git comparison

```bash
kicad-ci -p ./my-board -c main
```

#### Run only ERC and DRC

```bash
kicad-ci --skip-odb --skip-diff
```

#### Run with custom output directory

```bash
kicad-ci -o ./build/ci-reports
```

## Output Structure

After running, the output directory will contain:

```
ci-output/
├── erc-report.json       # ERC violations in JSON format
├── erc-log.txt           # ERC execution log
├── drc-report.json       # DRC violations in JSON format
├── drc-log.txt           # DRC execution log
├── odb.zip               # ODB++ manufacturing files
├── odb-log.txt           # ODB++ export log
├── diff/                 # Visual diff raw output (if --compare used)
│   ├── <commit-hash-old>/
│   │   ├── pcb/          # Old version PCB layer SVGs
│   │   └── sch/          # Old version schematic SVGs
│   ├── <commit-hash-new>/
│   │   ├── pcb/          # New version PCB layer SVGs
│   │   └── sch/          # New version schematic SVGs
│   └── web/              # Interactive HTML viewer
├── diff-log.txt          # Visual diff execution log
└── artifacts/            # Generated PDF artifacts (if --compare used)
    ├── pcb-diff.pdf      # Combined PCB layer differences
    ├── schematic-diff.pdf # Combined schematic differences
    ├── artifacts-log.txt  # Artifact generation log
    ├── triptych-svgs/     # Individual triptych SVGs
    │   ├── pcb-*.svg      # PCB layer triptychs (old+new+overlay)
    │   └── sch-*.svg      # Schematic triptychs (old+new+overlay)
    └── pdfs/              # Individual layer PDFs
        └── ...
```

### Triptych Method

The visual diff uses the "triptych" method to show differences:
- **Green/Cyan tint**: Elements from the old version (green and blue channels boosted)
- **Red/Pink tint**: Elements from the new version (red channel boosted, 50% opacity)
- **Yellow/White**: Areas where versions are identical (colors blend)
- **Pure Green**: Elements that were removed (only in old version)
- **Pure Red**: Elements that were added (only in new version)

Each triptych SVG embeds the complete vector content from both versions with aggressive color tinting applied directly to fill and stroke attributes (not via rasterizing SVG filters). The new version has group-level opacity (`opacity="0.5"` on the group element) to create the overlay effect without compounding transparency on overlapping elements. This approach ensures all vector data is preserved and properly rendered when converting to PDF via Inkscape, which has excellent support for group opacity. The generated PDFs maintain full vector quality - they can be zoomed infinitely without pixelation, making them perfect for documentation, manufacturing reviews, and design comparisons.

## CI/CD Integration

### GitHub Actions

```yaml
name: KiCAD CI

on: [push, pull_request]

jobs:
  kicad-checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Needed for git history comparison

      - uses: cachix/install-nix-action@v24
        with:
          extra_nix_config: |
            experimental-features = nix-command flakes

      - name: Run KiCAD CI
        run: |
          nix run github:yourusername/kicad-ci-automation -- \
            -p . \
            -c ${{ github.event.pull_request.base.sha || 'HEAD~1' }} \
            -o ./ci-output

      - name: Upload CI Reports
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: kicad-ci-reports
          path: ci-output/
```

### GitLab CI

```yaml
kicad-ci:
  image: nixos/nix:latest
  before_script:
    - nix-channel --update
    - nix-env -iA nixpkgs.git
  script:
    - nix --extra-experimental-features "nix-command flakes" run . -- -c HEAD~1
  artifacts:
    when: always
    paths:
      - ci-output/
    reports:
      junit: ci-output/*-report.json
```

## Requirements

- Nix with flakes enabled
- KiCAD project files (*.kicad_pro, *.kicad_sch, *.kicad_pcb)
- Git repository (optional, for visual diff)

## Dependencies

This flake integrates:

- **KiCAD**: PCB design software with CLI tools
- **kicad-diff**: Visual diff tool for PCB layouts (local flake)
- **jq**: JSON processing for report parsing

## Troubleshooting

### "No schematic/PCB file found"

Ensure your project directory contains:
- `*.kicad_sch` for ERC checks
- `*.kicad_pcb` for DRC checks and ODB++ export

### Visual diff not generating

The visual diff requires:
1. A PCB file (`*.kicad_pcb`)
2. A Git repository with history
3. A comparison reference specified with `-c/--compare`

Example:
```bash
kicad-ci -c HEAD~1  # Compare with previous commit
kicad-ci -c main    # Compare with main branch
```

### Exit codes

- `0`: All checks passed
- `1`: One or more checks failed

By default, the script continues running all checks even if one fails. Use `--exit-on-error` to stop at the first failure.

## License

This project integrates kicad-diff which is MIT licensed. See individual component licenses for details.
