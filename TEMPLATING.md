# KiCAD Templating Engine

The KiCAD templating engine allows you to use placeholders in your PCB and schematic designs that get automatically replaced with real values during the CI/CD pipeline.

## Quick Start

1. **Add placeholders to your KiCAD designs**
   - In KiCAD PCB Editor, add text on any layer (e.g., B.SilkS for back silkscreen)
   - Use placeholder syntax: `[sshhaa]`, `[branch]`, `[date]`, etc.
   - Example: Add `[sshhaa]` as text on the back silkscreen of your PCB

2. **Run your CI pipeline**
   ```bash
   nix run .# -- -p ../mgn1-adapter -c 8eb6388...
   ```
   The templating engine runs automatically and replaces placeholders with actual values.

## Available Placeholders

### Built-in Placeholders

| Placeholder   | Description                        | Example Output      |
|---------------|-----------------------------------|---------------------|
| `[sshhaa]`    | Short Git SHA (7 characters)      | `a1b2c3d`          |
| `[sha]`       | Full Git SHA                      | `a1b2c3d4e5f6...`  |
| `[branch]`    | Current Git branch name           | `main`             |
| `[version]`   | Project version (from git tag)    | `v1.0.0` or `dev`  |
| `[date]`      | Current date (YYYY-MM-DD)         | `2026-02-07`       |
| `[datetime]`  | Current date and time             | `2026-02-07 12:34:56` |
| `[year]`      | Current year                      | `2026`             |

### Custom Placeholders

You can define your own placeholders using a definitions file in JSON, YAML, or KEY=VALUE format.

## Usage Examples

### In PCB Designs

Add version information to your PCB silkscreen:
```
Text: "Rev: [sshhaa]"
Layer: B.SilkS
Result: "Rev: a1b2c3d"
```

Add build date:
```
Text: "Built: [date]"
Layer: F.SilkS
Result: "Built: 2026-02-07"
```

### Custom Definitions File

Create a file to define your own placeholders:

**JSON format (`defines.json`):**
```json
{
  "project": "Solar Power Controller",
  "pcb_rev": "Rev B",
  "author": "Your Name",
  "company": "ACME Corp"
}
```

**YAML format (`defines.yaml`):**
```yaml
project: Solar Power Controller
pcb_rev: Rev B
author: Your Name
company: ACME Corp
```

**KEY=VALUE format (`defines.txt`):**
```
# Project definitions
project=Solar Power Controller
pcb_rev=Rev B
author=Your Name
company=ACME Corp
```

Then use them in your KiCAD designs:
```
Text: "[project] - [pcb_rev]"
Result: "Solar Power Controller - Rev B"
```

### Manual Usage

Run the templating script manually on a specific file:

```bash
# Auto-detect git info
kicad-template path/to/design.kicad_pcb

# Use custom definitions
kicad-template design.kicad_pcb --defines defines.json

# Override specific values
kicad-template design.kicad_pcb --sha abc1234 --version "v2.0.0"

# Combine custom definitions with overrides
kicad-template design.kicad_pcb --defines defines.json --sha abc1234

# Dry run to see what would change
kicad-template design.kicad_pcb --dry-run

# List all available placeholders and their values
kicad-template design.kicad_pcb --list-placeholders
kicad-template design.kicad_pcb --defines defines.json --list-placeholders
```

### CI/CD Integration

The templating engine is integrated into the `kicad-ci` pipeline:

```bash
# Runs templating automatically
nix run .# -- -p ../project -c HEAD~1

# Use custom definitions in CI
nix run .# -- -p ../project -c HEAD~1 --defines ../project/defines.json

# Skip templating if needed
nix run .# -- -p ../project -c HEAD~1 --skip-template
```

## How It Works

1. **For PCB files (`.kicad_pcb`)**:
   - Uses the KiCAD `pcbnew` Python API
   - Iterates through all text objects on the board
   - Finds and replaces placeholder patterns
   - Preserves all formatting, positioning, and layer assignments

2. **For Schematic files (`.kicad_sch`)**:
   - Performs text-based search and replace
   - Works with KiCAD 6+ S-expression format
   - Maintains file structure and formatting

3. **Git Integration**:
   - Automatically detects current Git SHA, branch, and tags
   - Falls back to "unknown" if not in a Git repository
   - Can be overridden with command-line arguments

## Best Practices

1. **Choose the right layer**:
   - Use `F.SilkS` or `B.SilkS` for visible markings
   - Use `F.Fab` or `B.Fab` for fabrication/assembly notes
   - Avoid using copper layers for version info

2. **Font sizing**:
   - Keep text readable at your PCB's manufacturing scale
   - Typical minimum: 0.8mm to 1.0mm height
   - Check your fab house's minimum text requirements

3. **Placeholder format**:
   - Always use square brackets: `[placeholder]`
   - Case-sensitive (use lowercase)
   - No spaces inside brackets

4. **Version control**:
   - Commit your designs with placeholders intact
   - Commit your `defines.json` or definitions file
   - Let the CI/CD pipeline replace them during builds
   - Don't commit files with replaced values

5. **Custom definitions priority**:
   - Custom definitions override built-in placeholders
   - Command-line arguments (`--sha`, `--version`) override everything
   - Use custom defines to set project-specific defaults

## Troubleshooting

**Placeholder not being replaced:**
- Check spelling (must match exactly: `[sshhaa]` not `[sshaa]`)
- Ensure text is a `PCB_TEXT` object, not part of a footprint
- Run with `--dry-run` to see what would be replaced

**"pcbnew module not found":**
- Make sure you're running in the Nix environment
- The script needs KiCAD's Python bindings
- Run via `nix run` or in `nix develop` shell

**Git info shows "unknown":**
- Ensure you're in a Git repository
- Check that `git` command is available
- Override with `--sha` and `--branch` flags if needed

## Example Workflow

1. Design your PCB in KiCAD, add `[sshhaa]` text to back silkscreen
2. Commit your changes: `git add . && git commit -m "Add version text"`
3. Run CI: `nix run .# -- -p ../project -c HEAD~1`
4. The pipeline will:
   - Replace `[sshhaa]` with the actual commit SHA
   - Generate visual diffs with the updated version text
   - Create PDFs showing the version number on your PCB

## Technical Details

- **Script location**: `kicad-template.py`
- **Integration**: Added to `flake.nix` as `kicad-template` package
- **Runtime**: Uses KiCAD's bundled Python with pcbnew bindings
- **File modification**: Updates files in-place (make backups if running manually!)
