#!/usr/bin/env bash
set -euo pipefail

# Default values
PROJECT_DIR="."
OUTPUT_DIR="./ci-output"
COMPARE_REF=""
SKIP_ERC=false
SKIP_DRC=false
SKIP_ODB=false
SKIP_DIFF=false
EXIT_ON_ERROR=false

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
  echo -e "${BLUE}========================================${NC}"
  echo -e "${BLUE}$1${NC}"
  echo -e "${BLUE}========================================${NC}"
}

print_success() {
  echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
  echo -e "${RED}✗ $1${NC}"
}

print_warning() {
  echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
  echo -e "${BLUE}ℹ $1${NC}"
}

usage() {
  cat <<EOF
Usage: kicad-ci [OPTIONS]

Run KiCAD CI/CD checks including ERC, DRC, ODB++ export, and visual diffs.

OPTIONS:
  -p, --project DIR       Project directory (default: current directory)
  -o, --output DIR        Output directory (default: ./ci-output)
  -c, --compare REF       Git reference to compare against (for kicad-diff)
  --skip-erc              Skip Electrical Rules Check
  --skip-drc              Skip Design Rules Check
  --skip-odb              Skip ODB++ export
  --skip-diff             Skip visual diff generation
  --exit-on-error         Exit immediately on first error (default: continue all checks)
  -h, --help              Show this help message

EXAMPLES:
  # Run all checks on current directory
  kicad-ci

  # Run checks on specific project with comparison
  kicad-ci -p ./my-project -c HEAD~1

  # Run only ERC and DRC
  kicad-ci --skip-odb --skip-diff

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    -p|--project)
      PROJECT_DIR="$2"
      shift 2
      ;;
    -o|--output)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    -c|--compare)
      COMPARE_REF="$2"
      shift 2
      ;;
    --skip-erc)
      SKIP_ERC=true
      shift
      ;;
    --skip-drc)
      SKIP_DRC=true
      shift
      ;;
    --skip-odb)
      SKIP_ODB=true
      shift
      ;;
    --skip-diff)
      SKIP_DIFF=true
      shift
      ;;
    --exit-on-error)
      EXIT_ON_ERROR=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

# Validate project directory
if [[ ! -d "$PROJECT_DIR" ]]; then
  print_error "Project directory does not exist: $PROJECT_DIR"
  exit 1
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Find KiCAD project files
print_header "Finding KiCAD Project Files"

KICAD_PRO=$(find "$PROJECT_DIR" -maxdepth 2 -name "*.kicad_pro" | head -n 1)
KICAD_SCH=$(find "$PROJECT_DIR" -maxdepth 2 -name "*.kicad_sch" | head -n 1)
KICAD_PCB=$(find "$PROJECT_DIR" -maxdepth 2 -name "*.kicad_pcb" | head -n 1)

if [[ -n "$KICAD_PRO" ]]; then
  print_info "Found project: $KICAD_PRO"
fi
if [[ -n "$KICAD_SCH" ]]; then
  print_info "Found schematic: $KICAD_SCH"
fi
if [[ -n "$KICAD_PCB" ]]; then
  print_info "Found PCB: $KICAD_PCB"
fi

# Check KiCAD CLI version
print_header "KiCAD Version"
kicad-cli version

OVERALL_STATUS=0

# Run ERC (Electrical Rules Check)
if [[ "$SKIP_ERC" == false ]] && [[ -n "$KICAD_SCH" ]]; then
  print_header "Running Electrical Rules Check (ERC)"
  ERC_OUTPUT="$OUTPUT_DIR/erc-report.json"

  if kicad-cli sch erc \
    --format json \
    --output "$ERC_OUTPUT" \
    --exit-code-violations \
    "$KICAD_SCH" 2>&1 | tee "$OUTPUT_DIR/erc-log.txt"; then
    print_success "ERC passed with no violations"
  else
    ERC_EXIT_CODE=$?
    print_error "ERC failed with exit code $ERC_EXIT_CODE"
    OVERALL_STATUS=1

    # Parse and display violations if JSON report exists
    if [[ -f "$ERC_OUTPUT" ]]; then
      VIOLATION_COUNT=$(jq '.sheets[].violations | length' "$ERC_OUTPUT" 2>/dev/null | awk '{s+=$1} END {print s}')
      if [[ -n "$VIOLATION_COUNT" ]] && [[ "$VIOLATION_COUNT" -gt 0 ]]; then
        print_warning "Found $VIOLATION_COUNT ERC violation(s)"
        print_info "See detailed report: $ERC_OUTPUT"
      fi
    fi

    if [[ "$EXIT_ON_ERROR" == true ]]; then
      exit 1
    fi
  fi
elif [[ "$SKIP_ERC" == false ]]; then
  print_warning "Skipping ERC: No schematic file found"
fi

# Run DRC (Design Rules Check)
if [[ "$SKIP_DRC" == false ]] && [[ -n "$KICAD_PCB" ]]; then
  print_header "Running Design Rules Check (DRC)"
  DRC_OUTPUT="$OUTPUT_DIR/drc-report.json"

  if kicad-cli pcb drc \
    --format json \
    --output "$DRC_OUTPUT" \
    --exit-code-violations \
    "$KICAD_PCB" 2>&1 | tee "$OUTPUT_DIR/drc-log.txt"; then
    print_success "DRC passed with no violations"
  else
    DRC_EXIT_CODE=$?
    print_error "DRC failed with exit code $DRC_EXIT_CODE"
    OVERALL_STATUS=1

    # Parse and display violations if JSON report exists
    if [[ -f "$DRC_OUTPUT" ]]; then
      VIOLATION_COUNT=$(jq '[.violations, .unconnected_items, .schematic_parity] | map(length) | add' "$DRC_OUTPUT" 2>/dev/null)
      if [[ -n "$VIOLATION_COUNT" ]] && [[ "$VIOLATION_COUNT" -gt 0 ]]; then
        print_warning "Found $VIOLATION_COUNT DRC violation(s)"
        print_info "See detailed report: $DRC_OUTPUT"
      fi
    fi

    if [[ "$EXIT_ON_ERROR" == true ]]; then
      exit 1
    fi
  fi
elif [[ "$SKIP_DRC" == false ]]; then
  print_warning "Skipping DRC: No PCB file found"
fi

# Export ODB++
if [[ "$SKIP_ODB" == false ]] && [[ -n "$KICAD_PCB" ]]; then
  print_header "Exporting ODB++"
  ODB_OUTPUT="$OUTPUT_DIR/odb.zip"

  if kicad-cli pcb export odb \
    --output "$ODB_OUTPUT" \
    "$KICAD_PCB" 2>&1 | tee "$OUTPUT_DIR/odb-log.txt"; then
    print_success "ODB++ export completed successfully"
    print_info "Output: $ODB_OUTPUT"
  else
    print_error "ODB++ export failed"
    OVERALL_STATUS=1

    if [[ "$EXIT_ON_ERROR" == true ]]; then
      exit 1
    fi
  fi
elif [[ "$SKIP_ODB" == false ]]; then
  print_warning "Skipping ODB++ export: No PCB file found"
fi

# Run kicad-diff
if [[ "$SKIP_DIFF" == false ]] && [[ -n "$KICAD_PCB" ]] && [[ -n "$COMPARE_REF" ]]; then
  print_header "Generating Visual Diff"
  DIFF_OUTPUT="$OUTPUT_DIR/diff"
  mkdir -p "$DIFF_OUTPUT"

  # Run kidiff and capture output
  DIFF_LOG="$OUTPUT_DIR/diff-log.txt"
  if kidiff \
    -o "$DIFF_OUTPUT" \
    -a "$COMPARE_REF" \
    -b HEAD \
    --webserver-disable \
    "$KICAD_PCB" 2>&1 | tee "$DIFF_LOG"; then
    print_success "Visual diff generated successfully"
    print_info "Output: $DIFF_OUTPUT"
  else
    DIFF_EXIT_CODE=$?
    # Check if the failure was due to no differences (which is not really an error)
    if grep -q "There is no difference" "$DIFF_LOG" 2>/dev/null; then
      print_warning "No changes detected in PCB between $COMPARE_REF and HEAD"
      print_info "Skipping visual diff generation"
    else
      print_error "Visual diff generation failed with exit code $DIFF_EXIT_CODE"
      OVERALL_STATUS=1

      if [[ "$EXIT_ON_ERROR" == true ]]; then
        exit 1
      fi
    fi
  fi
elif [[ "$SKIP_DIFF" == false ]] && [[ -z "$COMPARE_REF" ]]; then
  print_warning "Skipping visual diff: No comparison reference specified (use -c/--compare)"
elif [[ "$SKIP_DIFF" == false ]]; then
  print_warning "Skipping visual diff: No PCB file found"
fi

# Summary
print_header "CI/CD Summary"
if [[ $OVERALL_STATUS -eq 0 ]]; then
  print_success "All checks passed!"
else
  print_error "Some checks failed. See logs in $OUTPUT_DIR for details."
fi

echo ""
print_info "Output directory: $OUTPUT_DIR"
echo ""

exit $OVERALL_STATUS
