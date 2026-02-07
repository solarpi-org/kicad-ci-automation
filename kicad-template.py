#!/usr/bin/env python3
"""
KiCAD Templating Engine - Replace placeholders in KiCAD PCB and schematic files

Supports placeholders like:
  [sshhaa]    - Git commit SHA (short, 7 chars)
  [sha]       - Git commit SHA (full)
  [branch]    - Current git branch name
  [date]      - Current date (YYYY-MM-DD)
  [datetime]  - Current date and time
  [version]   - Project version (from git tag or custom)

Plus custom definitions from a file (JSON, YAML, or KEY=VALUE format)

Usage:
  kicad-template.py <pcb_or_sch_file> [--sha <commit>] [--branch <name>] [--version <ver>]
  kicad-template.py <pcb_or_sch_file> --defines defines.json
"""

import argparse
import os
import sys
import subprocess
import json
from datetime import datetime
from pathlib import Path


def get_git_info(repo_path="."):
    """Get git information for template replacement"""
    info = {}

    try:
        # Get full SHA
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        info['sha'] = result.stdout.strip()
        info['sshhaa'] = info['sha'][:7]  # Short SHA

        # Get branch name
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        info['branch'] = result.stdout.strip()

        # Try to get version from git tag
        result = subprocess.run(
            ['git', 'describe', '--tags', '--abbrev=0'],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            info['version'] = result.stdout.strip()
        else:
            info['version'] = 'dev'

    except (subprocess.CalledProcessError, FileNotFoundError):
        # Git not available or not a git repo
        info['sha'] = 'unknown'
        info['sshhaa'] = 'unknown'
        info['branch'] = 'unknown'
        info['version'] = 'dev'

    return info


def load_custom_defines(defines_file):
    """
    Load custom template definitions from a file.

    Supports formats:
    - JSON: {"key": "value", ...}
    - YAML: key: value (requires PyYAML)
    - KEY=VALUE: Simple key-value pairs, one per line

    Returns:
        dict: Custom template definitions
    """
    defines_path = Path(defines_file)

    if not defines_path.exists():
        print(f"Warning: Defines file not found: {defines_file}")
        return {}

    try:
        with open(defines_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()

        # Try JSON first
        if defines_path.suffix in ['.json', '.jsn']:
            return json.loads(content)

        # Try YAML
        if defines_path.suffix in ['.yaml', '.yml']:
            try:
                import yaml
                return yaml.safe_load(content)
            except ImportError:
                print("Warning: PyYAML not installed, cannot parse YAML. Trying KEY=VALUE format...")

        # Try KEY=VALUE format
        defines = {}
        for line in content.splitlines():
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith('#') or line.startswith('//'):
                continue

            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                # Remove quotes if present
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                defines[key] = value

        if defines:
            return defines

        # If we got here, try JSON as last resort
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            print(f"Warning: Could not parse defines file format: {defines_file}")
            return {}

    except Exception as e:
        print(f"Error loading defines file: {e}")
        return {}


def get_template_values(args):
    """Build dictionary of template placeholder -> replacement value"""
    values = {}

    # Start with custom defines if provided
    if args.defines:
        custom_defines = load_custom_defines(args.defines)
        values.update(custom_defines)
        if custom_defines:
            print(f"Loaded {len(custom_defines)} custom definition(s) from {args.defines}")

    # Get git info
    git_info = get_git_info(os.path.dirname(args.file) or '.')

    # Add built-in values (custom defines take precedence if they set these)
    if 'sshhaa' not in values:
        values['sshhaa'] = args.sha[:7] if args.sha else git_info['sshhaa']
    if 'sha' not in values:
        values['sha'] = args.sha if args.sha else git_info['sha']
    if 'branch' not in values:
        values['branch'] = args.branch if args.branch else git_info['branch']
    if 'version' not in values:
        values['version'] = args.version if args.version else git_info['version']

    # Date/time values (unless overridden)
    now = datetime.now()
    if 'date' not in values:
        values['date'] = now.strftime('%Y-%m-%d')
    if 'datetime' not in values:
        values['datetime'] = now.strftime('%Y-%m-%d %H:%M:%S')
    if 'year' not in values:
        values['year'] = now.strftime('%Y')

    return values


def process_pcb(pcb_path, template_values, dry_run=False):
    """
    Process a .kicad_pcb file and replace template placeholders.

    Note: KiCAD 6+ PCBs are text-based S-expression format,
    so we can use simple text replacement.
    """
    print(f"Loading PCB: {pcb_path}")

    try:
        with open(pcb_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading PCB: {e}")
        return False

    original_content = content
    replacements_made = 0

    # Replace all placeholders
    for placeholder, value in template_values.items():
        pattern = f'[{placeholder}]'
        if pattern in content:
            print(f"  Found '{pattern}' -> '{value}'")
            count = content.count(pattern)
            content = content.replace(pattern, value)
            replacements_made += count

    if replacements_made > 0 and not dry_run:
        print(f"Saving updated PCB...")
        with open(pcb_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✓ Made {replacements_made} replacement(s)")
    elif replacements_made > 0:
        print(f"[DRY RUN] Would make {replacements_made} replacement(s)")
    else:
        print("No template placeholders found")

    return True


def process_schematic(sch_path, template_values, dry_run=False):
    """
    Process a .kicad_sch file and replace template placeholders.

    Note: KiCAD 6+ schematics are text-based S-expression format,
    so we can use simple text replacement for now.
    For more complex manipulation, we'd need the full schematic API.
    """
    print(f"Loading schematic: {sch_path}")

    try:
        with open(sch_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading schematic: {e}")
        return False

    original_content = content
    replacements_made = 0

    # Replace all placeholders
    for placeholder, value in template_values.items():
        pattern = f'[{placeholder}]'
        if pattern in content:
            print(f"  Found '{pattern}' -> '{value}'")
            count = content.count(pattern)
            content = content.replace(pattern, value)
            replacements_made += count

    if replacements_made > 0 and not dry_run:
        print(f"Saving updated schematic...")
        with open(sch_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✓ Made {replacements_made} replacement(s)")
    elif replacements_made > 0:
        print(f"[DRY RUN] Would make {replacements_made} replacement(s)")
    else:
        print("No template placeholders found")

    return True


def main():
    parser = argparse.ArgumentParser(
        description='Replace template placeholders in KiCAD files',
        epilog='''
Examples:
  kicad-template design.kicad_pcb
  kicad-template design.kicad_pcb --defines custom.json
  kicad-template design.kicad_pcb --sha abc1234 --version v1.0
  kicad-template design.kicad_pcb --dry-run --list-placeholders
        '''
    )
    parser.add_argument(
        'file',
        help='Path to .kicad_pcb or .kicad_sch file'
    )
    parser.add_argument(
        '--defines',
        help='Path to custom definitions file (JSON, YAML, or KEY=VALUE format)'
    )
    parser.add_argument(
        '--sha',
        help='Git commit SHA to use (overrides auto-detection)'
    )
    parser.add_argument(
        '--branch',
        help='Git branch name to use (overrides auto-detection)'
    )
    parser.add_argument(
        '--version',
        help='Version string to use (overrides auto-detection)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be replaced without making changes'
    )
    parser.add_argument(
        '--list-placeholders',
        action='store_true',
        help='List all available placeholders and their current values'
    )

    args = parser.parse_args()

    # Get template values
    template_values = get_template_values(args)

    # List placeholders if requested
    if args.list_placeholders:
        print("Available template placeholders:")

        # Separate built-in and custom
        builtin_keys = {'sshhaa', 'sha', 'branch', 'version', 'date', 'datetime', 'year'}
        custom_keys = set(template_values.keys()) - builtin_keys

        if builtin_keys & set(template_values.keys()):
            print("\n  Built-in placeholders:")
            for key in sorted(builtin_keys):
                if key in template_values:
                    print(f"    [{key}] -> {template_values[key]}")

        if custom_keys:
            print("\n  Custom placeholders:")
            for key in sorted(custom_keys):
                print(f"    [{key}] -> {template_values[key]}")

        return 0

    # Check file exists
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        return 1

    # Process based on file type
    if file_path.suffix == '.kicad_pcb':
        success = process_pcb(file_path, template_values, args.dry_run)
    elif file_path.suffix == '.kicad_sch':
        success = process_schematic(file_path, template_values, args.dry_run)
    else:
        print(f"Error: Unsupported file type: {file_path.suffix}")
        print("Supported types: .kicad_pcb, .kicad_sch")
        return 1

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
