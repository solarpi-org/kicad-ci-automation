#!/usr/bin/env bash
set -euo pipefail

# Default values
PROJECT_DIR="."
OUTPUT_DIR="./ci-output"
COMPARE_REF=""
TEMPLATE_DEFINES=""
SKIP_ERC=false
SKIP_DRC=false
SKIP_ODB=false
SKIP_DIFF=false
SKIP_TEMPLATE=false
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
  -d, --defines FILE      Custom template definitions file (JSON, YAML, or KEY=VALUE)
  --skip-erc              Skip Electrical Rules Check
  --skip-drc              Skip Design Rules Check
  --skip-odb              Skip ODB++ export
  --skip-diff             Skip visual diff generation
  --skip-template         Skip template placeholder replacement
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
    -d|--defines)
      TEMPLATE_DEFINES="$2"
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
    --skip-template)
      SKIP_TEMPLATE=true
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

# Create output directory and make path absolute
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

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
TEMPLATE_BRANCH=""
TEMPLATE_COMMIT_MADE=false

# Run template replacement
if [[ "$SKIP_TEMPLATE" == false ]]; then
  print_header "Applying Template Replacements"

  # Get current git SHA
  CURRENT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

  print_info "Current SHA: $CURRENT_SHA"
  print_info "Current branch: $CURRENT_BRANCH"

  # Build template command arguments
  TEMPLATE_ARGS=(--sha "$CURRENT_SHA" --branch "$CURRENT_BRANCH")
  if [[ -n "$TEMPLATE_DEFINES" ]]; then
    if [[ -f "$TEMPLATE_DEFINES" ]]; then
      TEMPLATE_ARGS+=(--defines "$TEMPLATE_DEFINES")
      print_info "Using custom defines: $TEMPLATE_DEFINES"
    else
      print_warning "Custom defines file not found: $TEMPLATE_DEFINES"
    fi
  fi

  # Apply templating to PCB
  if [[ -n "$KICAD_PCB" ]]; then
    print_info "Processing PCB: $KICAD_PCB"
    if kicad-template "$KICAD_PCB" "${TEMPLATE_ARGS[@]}" 2>&1 | tee "$OUTPUT_DIR/template-pcb-log.txt"; then
      print_success "PCB template replacement completed"
    else
      print_warning "PCB template replacement had issues (see $OUTPUT_DIR/template-pcb-log.txt)"
    fi
  fi

  # Apply templating to schematic
  if [[ -n "$KICAD_SCH" ]]; then
    print_info "Processing schematic: $KICAD_SCH"
    if kicad-template "$KICAD_SCH" "${TEMPLATE_ARGS[@]}" 2>&1 | tee "$OUTPUT_DIR/template-sch-log.txt"; then
      print_success "Schematic template replacement completed"
    else
      print_warning "Schematic template replacement had issues (see $OUTPUT_DIR/template-sch-log.txt)"
    fi
  fi

  # Create a temporary CI branch and commit template changes there.
  # This avoids touching the current branch at all - safe to run locally.
  if git -C "$PROJECT_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    pushd "$PROJECT_DIR" > /dev/null

    if git diff --quiet 2>/dev/null; then
      print_info "No template changes to commit"
    else
      ORIG_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "detached")
      TIMESTAMP=$(date +%Y%m%d-%H%M%S)
      TEMPLATE_BRANCH="ci-${ORIG_BRANCH}-${TIMESTAMP}"

      print_info "Creating temporary CI branch: $TEMPLATE_BRANCH"

      # Create branch at current HEAD without switching to it, then commit
      # using a worktree-style approach: stage files, stash index state, commit
      # on new branch, restore original index.
      git branch "$TEMPLATE_BRANCH" HEAD

      # Stage the modified KiCAD files into a temporary index
      [[ -n "$KICAD_PCB" ]] && git add "$(basename "$KICAD_PCB")" 2>/dev/null || true
      [[ -n "$KICAD_SCH" ]] && git add "$(basename "$KICAD_SCH")" 2>/dev/null || true

      # Commit onto the new branch without switching (update-ref trick).
      # Set author/committer identity inline so no global git config is needed
      # (important on bare CI runners).
      TREE=$(git write-tree)
      PARENT=$(git rev-parse HEAD)
      COMMIT=$(GIT_AUTHOR_NAME="kicad-ci" GIT_AUTHOR_EMAIL="kicad-ci@localhost" \
               GIT_COMMITTER_NAME="kicad-ci" GIT_COMMITTER_EMAIL="kicad-ci@localhost" \
               git commit-tree "$TREE" -p "$PARENT" -m "ci: template replacement for diff")
      git update-ref "refs/heads/$TEMPLATE_BRANCH" "$COMMIT"

      # Restore the index to match HEAD (unstage the staged files)
      [[ -n "$KICAD_PCB" ]] && git restore --staged "$(basename "$KICAD_PCB")" 2>/dev/null || true
      [[ -n "$KICAD_SCH" ]] && git restore --staged "$(basename "$KICAD_SCH")" 2>/dev/null || true

      TEMPLATE_COMMIT_MADE=true
      print_success "Template changes committed to $TEMPLATE_BRANCH (current branch unchanged)"
      print_info "kidiff will compare against HEAD on $TEMPLATE_BRANCH"
    fi

    popd > /dev/null
  else
    print_warning "Project directory is not in a git repository - skipping template commit"
  fi
fi

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

  # Run kidiff from project directory
  pushd "$PROJECT_DIR" > /dev/null

  # Run kidiff and capture output
  DIFF_LOG="$OUTPUT_DIR/diff-log.txt"
  DIFF_SUCCESS=false

  # If we made a CI branch with template substitutions applied, diff against
  # that branch's tip so kidiff sees the rendered values. Otherwise use HEAD.
  DIFF_NEW_REF="${TEMPLATE_BRANCH:-HEAD}"

  if kidiff \
    -o "$DIFF_OUTPUT" \
    -a "$DIFF_NEW_REF" \
    -b "$COMPARE_REF" \
    --webserver-disable \
    "$(basename "$KICAD_PCB")" 2>&1 | tee "$DIFF_LOG"; then
    print_success "Visual diff generated successfully"
    print_info "Output: $DIFF_OUTPUT"
    DIFF_SUCCESS=true
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
        popd > /dev/null
        exit 1
      fi
    fi
  fi

  popd > /dev/null

  # Generate PDF artifacts if diff was successful
  if [[ "$DIFF_SUCCESS" == true ]]; then
    print_header "Generating PDF Artifacts"
    ARTIFACTS_OUTPUT="$OUTPUT_DIR/artifacts"

    if generate-diff-artifacts "$DIFF_OUTPUT" -o "$ARTIFACTS_OUTPUT" 2>&1 | tee "$OUTPUT_DIR/artifacts-log.txt"; then
      print_success "PDF artifacts generated successfully"
      print_info "Triptych SVGs: $ARTIFACTS_OUTPUT/triptych-svgs/"

      if [[ -f "$ARTIFACTS_OUTPUT/pcb-diff.pdf" ]]; then
        print_info "PCB PDF: $ARTIFACTS_OUTPUT/pcb-diff.pdf"
      fi

      if [[ -f "$ARTIFACTS_OUTPUT/schematic-diff.pdf" ]]; then
        print_info "Schematic PDF: $ARTIFACTS_OUTPUT/schematic-diff.pdf"
      fi
    else
      print_warning "PDF artifact generation had some issues (check $OUTPUT_DIR/artifacts-log.txt)"
      print_info "Triptych SVGs may still be available in: $ARTIFACTS_OUTPUT/triptych-svgs/"
    fi
  fi
elif [[ "$SKIP_DIFF" == false ]] && [[ -z "$COMPARE_REF" ]]; then
  print_warning "Skipping visual diff: No comparison reference specified (use -c/--compare)"
elif [[ "$SKIP_DIFF" == false ]]; then
  print_warning "Skipping visual diff: No PCB file found"
fi

# Clean up temporary CI branch if one was created
if [[ "$TEMPLATE_COMMIT_MADE" == true ]] && [[ -n "$TEMPLATE_BRANCH" ]]; then
  print_header "Cleaning Up CI Branch"
  pushd "$PROJECT_DIR" > /dev/null
  if git branch -D "$TEMPLATE_BRANCH" 2>&1 | tee "$OUTPUT_DIR/template-cleanup-log.txt"; then
    print_success "Temporary branch $TEMPLATE_BRANCH deleted"
  else
    print_warning "Could not delete branch $TEMPLATE_BRANCH - remove it manually with: git branch -D $TEMPLATE_BRANCH"
  fi
  popd > /dev/null
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
