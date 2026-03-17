#!/usr/bin/env bash
set -euo pipefail

# Default values
PROJECT_DIR="."
OUTPUT_DIR="./ci-output"
COMPARE_REF=""
TEMPLATE_DEFINES=""
OUTPUT_PREFIX=""
SKIP_ERC=false
SKIP_DRC=false
SKIP_ODB=false
SKIP_DIFF=false
SKIP_TEMPLATE=false
SKIP_PLOTS=false
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
  -n, --prefix PREFIX     Prefix for output filenames (e.g. "pr-42-abc1234")
  --skip-erc              Skip Electrical Rules Check
  --skip-drc              Skip Design Rules Check
  --skip-odb              Skip ODB++ export
  --skip-diff             Skip visual diff generation
  --skip-template         Skip template placeholder replacement
  --skip-plots            Skip schematic/PCB PDF plot export
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
    -n|--prefix)
      OUTPUT_PREFIX="$2"
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
    --skip-plots)
      SKIP_PLOTS=true
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

# Build output filename: prefix-boardname-suffix.ext or boardname-suffix.ext
outname() {
  # Usage: outname <board_stem> <suffix> <ext>
  #   e.g. outname "mgn1-adapter" "erc-report" "json"
  #     -> "pr-42-abc1234-mgn1-adapter-erc-report.json" (with prefix)
  #     -> "mgn1-adapter-erc-report.json"                (without)
  local stem="$1" suffix="$2" ext="$3"
  if [[ -n "$OUTPUT_PREFIX" ]]; then
    echo "${OUTPUT_PREFIX}-${stem}-${suffix}.${ext}"
  else
    echo "${stem}-${suffix}.${ext}"
  fi
}

# Find KiCAD project files
print_header "Finding KiCAD Project Files"

mapfile -t KICAD_SCHS < <(find "$PROJECT_DIR" -maxdepth 2 -name "*.kicad_sch" | sort)
mapfile -t KICAD_PCBS < <(find "$PROJECT_DIR" -maxdepth 2 -name "*.kicad_pcb" | sort)

if [[ ${#KICAD_SCHS[@]} -gt 0 ]]; then
  print_info "Found ${#KICAD_SCHS[@]} schematic(s):"
  for f in "${KICAD_SCHS[@]}"; do print_info "  $f"; done
fi
if [[ ${#KICAD_PCBS[@]} -gt 0 ]]; then
  print_info "Found ${#KICAD_PCBS[@]} PCB(s):"
  for f in "${KICAD_PCBS[@]}"; do print_info "  $f"; done
fi

# Check KiCAD CLI version
print_header "KiCAD Version"
kicad-cli version

OVERALL_STATUS=0
TEMPLATE_BRANCH=""
# Track files modified by template replacement so we can restore them
TEMPLATE_MODIFIED_FILES=()

# shellcheck disable=SC2329 # cleanup is invoked indirectly via trap
cleanup() {
  # Restore template-modified files to their original content
  if [[ ${#TEMPLATE_MODIFIED_FILES[@]} -gt 0 ]]; then
    pushd "$PROJECT_DIR" > /dev/null
    for f in "${TEMPLATE_MODIFIED_FILES[@]}"; do
      git checkout HEAD -- "$f" 2>/dev/null || print_warning "Could not restore $f"
    done
    popd > /dev/null
    print_success "Restored template-modified files to original content"
  fi

  # Delete temporary CI branch if it still exists
  if [[ -n "$TEMPLATE_BRANCH" ]]; then
    pushd "$PROJECT_DIR" > /dev/null
    if git rev-parse --verify "refs/heads/$TEMPLATE_BRANCH" >/dev/null 2>&1; then
      git branch -D "$TEMPLATE_BRANCH" >/dev/null 2>&1 || print_warning "Could not delete branch $TEMPLATE_BRANCH"
      print_success "Deleted temporary branch $TEMPLATE_BRANCH"
    fi
    popd > /dev/null
  fi
}

trap cleanup EXIT

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

  # Apply templating to all PCBs
  for KICAD_PCB in "${KICAD_PCBS[@]}"; do
    PCB_STEM=$(basename "${KICAD_PCB%.kicad_pcb}")
    print_info "Processing PCB: $KICAD_PCB"
    if kicad-template "$KICAD_PCB" "${TEMPLATE_ARGS[@]}" 2>&1 | tee "$OUTPUT_DIR/$(outname "$PCB_STEM" template-pcb log)"; then
      print_success "PCB template replacement completed: $PCB_STEM"
      TEMPLATE_MODIFIED_FILES+=("$KICAD_PCB")
    else
      print_warning "PCB template replacement had issues"
    fi
  done

  # Apply templating to all schematics
  for KICAD_SCH in "${KICAD_SCHS[@]}"; do
    SCH_STEM=$(basename "${KICAD_SCH%.kicad_sch}")
    print_info "Processing schematic: $KICAD_SCH"
    if kicad-template "$KICAD_SCH" "${TEMPLATE_ARGS[@]}" 2>&1 | tee "$OUTPUT_DIR/$(outname "$SCH_STEM" template-sch log)"; then
      print_success "Schematic template replacement completed: $SCH_STEM"
      TEMPLATE_MODIFIED_FILES+=("$KICAD_SCH")
    else
      print_warning "Schematic template replacement had issues"
    fi
  done

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
      for f in "${KICAD_PCBS[@]}" "${KICAD_SCHS[@]}"; do
        if [[ -n "$f" ]]; then git add "$f" 2>/dev/null || print_warning "Could not stage $f"; fi
      done

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
      for f in "${KICAD_PCBS[@]}" "${KICAD_SCHS[@]}"; do
        if [[ -n "$f" ]]; then git restore --staged "$f" 2>/dev/null || print_warning "Could not unstage $f"; fi
      done

      print_success "Template changes committed to $TEMPLATE_BRANCH (current branch unchanged)"
      print_info "kidiff will compare against HEAD on $TEMPLATE_BRANCH"
    fi

    popd > /dev/null
  else
    print_warning "Project directory is not in a git repository - skipping template commit"
  fi
fi

# Run ERC (Electrical Rules Check)
if [[ "$SKIP_ERC" == false ]] && [[ ${#KICAD_SCHS[@]} -gt 0 ]]; then
  print_header "Running Electrical Rules Check (ERC)"

  for KICAD_SCH in "${KICAD_SCHS[@]}"; do
    SCH_STEM=$(basename "${KICAD_SCH%.kicad_sch}")
    ERC_OUTPUT="$OUTPUT_DIR/$(outname "$SCH_STEM" erc-report json)"
    print_info "Running ERC on: $KICAD_SCH"

    if kicad-cli sch erc \
      --format json \
      --output "$ERC_OUTPUT" \
      --exit-code-violations \
      "$KICAD_SCH" 2>&1 | tee "$OUTPUT_DIR/$(outname "$SCH_STEM" erc log)"; then
      print_success "ERC passed: $SCH_STEM"
    else
      ERC_EXIT_CODE=$?
      print_error "ERC failed for $SCH_STEM (exit code $ERC_EXIT_CODE)"
      OVERALL_STATUS=1

      if [[ -f "$ERC_OUTPUT" ]]; then
        VIOLATION_COUNT=$(jq '.sheets[].violations | length' "$ERC_OUTPUT" 2>/dev/null | awk '{s+=$1} END {print s}')
        if [[ -n "$VIOLATION_COUNT" ]] && [[ "$VIOLATION_COUNT" -gt 0 ]]; then
          print_warning "Found $VIOLATION_COUNT ERC violation(s) in $SCH_STEM"
          print_info "See detailed report: $ERC_OUTPUT"
        fi
      fi

      if [[ "$EXIT_ON_ERROR" == true ]]; then
        exit 1
      fi
    fi
  done
elif [[ "$SKIP_ERC" == false ]]; then
  print_warning "Skipping ERC: No schematic files found"
fi

# Run DRC (Design Rules Check)
if [[ "$SKIP_DRC" == false ]] && [[ ${#KICAD_PCBS[@]} -gt 0 ]]; then
  print_header "Running Design Rules Check (DRC)"

  for KICAD_PCB in "${KICAD_PCBS[@]}"; do
    PCB_STEM=$(basename "${KICAD_PCB%.kicad_pcb}")
    DRC_OUTPUT="$OUTPUT_DIR/$(outname "$PCB_STEM" drc-report json)"
    print_info "Running DRC on: $KICAD_PCB"

    if kicad-cli pcb drc \
      --format json \
      --output "$DRC_OUTPUT" \
      --exit-code-violations \
      "$KICAD_PCB" 2>&1 | tee "$OUTPUT_DIR/$(outname "$PCB_STEM" drc log)"; then
      print_success "DRC passed: $PCB_STEM"
    else
      DRC_EXIT_CODE=$?
      print_error "DRC failed for $PCB_STEM (exit code $DRC_EXIT_CODE)"
      OVERALL_STATUS=1

      if [[ -f "$DRC_OUTPUT" ]]; then
        VIOLATION_COUNT=$(jq '[.violations, .unconnected_items, .schematic_parity] | map(length) | add' "$DRC_OUTPUT" 2>/dev/null)
        if [[ -n "$VIOLATION_COUNT" ]] && [[ "$VIOLATION_COUNT" -gt 0 ]]; then
          print_warning "Found $VIOLATION_COUNT DRC violation(s) in $PCB_STEM"
          print_info "See detailed report: $DRC_OUTPUT"
        fi
      fi

      if [[ "$EXIT_ON_ERROR" == true ]]; then
        exit 1
      fi
    fi
  done
elif [[ "$SKIP_DRC" == false ]]; then
  print_warning "Skipping DRC: No PCB files found"
fi

# Export ODB++
if [[ "$SKIP_ODB" == false ]] && [[ ${#KICAD_PCBS[@]} -gt 0 ]]; then
  print_header "Exporting ODB++"

  for KICAD_PCB in "${KICAD_PCBS[@]}"; do
    PCB_STEM=$(basename "${KICAD_PCB%.kicad_pcb}")
    ODB_OUTPUT="$OUTPUT_DIR/$(outname "$PCB_STEM" odb zip)"
    print_info "Exporting ODB++ for: $KICAD_PCB"

    if kicad-cli pcb export odb \
      --output "$ODB_OUTPUT" \
      "$KICAD_PCB" 2>&1 | tee "$OUTPUT_DIR/$(outname "$PCB_STEM" odb log)"; then
      print_success "ODB++ export completed: $PCB_STEM"
      print_info "Output: $ODB_OUTPUT"
    else
      print_error "ODB++ export failed for $PCB_STEM"
      OVERALL_STATUS=1

      if [[ "$EXIT_ON_ERROR" == true ]]; then
        exit 1
      fi
    fi
  done
elif [[ "$SKIP_ODB" == false ]]; then
  print_warning "Skipping ODB++ export: No PCB files found"
fi

# Export schematic and PCB PDFs
if [[ "$SKIP_PLOTS" == false ]]; then
  if [[ ${#KICAD_SCHS[@]} -gt 0 ]]; then
    print_header "Exporting Schematic PDFs"

    for KICAD_SCH in "${KICAD_SCHS[@]}"; do
      SCH_STEM=$(basename "${KICAD_SCH%.kicad_sch}")
      SCH_PDF="$OUTPUT_DIR/$(outname "$SCH_STEM" schematic pdf)"
      print_info "Exporting schematic PDF for: $KICAD_SCH"

      if kicad-cli sch export pdf \
        --output "$SCH_PDF" \
        --black-and-white \
        "$KICAD_SCH" 2>&1 | tee "$OUTPUT_DIR/$(outname "$SCH_STEM" schematic-pdf log)"; then
        print_success "Schematic PDF export completed: $SCH_STEM"
        print_info "Output: $SCH_PDF"
      else
        print_error "Schematic PDF export failed for $SCH_STEM"
        OVERALL_STATUS=1

        if [[ "$EXIT_ON_ERROR" == true ]]; then
          exit 1
        fi
      fi
    done
  else
    print_warning "Skipping schematic PDF export: No schematic files found"
  fi

  if [[ ${#KICAD_PCBS[@]} -gt 0 ]]; then
    print_header "Exporting PCB PDFs"

    for KICAD_PCB in "${KICAD_PCBS[@]}"; do
      PCB_STEM=$(basename "${KICAD_PCB%.kicad_pcb}")
      PCB_PDF="$OUTPUT_DIR/$(outname "$PCB_STEM" pcb pdf)"
      print_info "Exporting PCB PDF for: $KICAD_PCB"

      if kicad-cli pcb export pdf \
        --output "$PCB_PDF" \
        --layers "F.Cu,B.Cu,F.Silkscreen,B.Silkscreen,Edge.Cuts" \
        --include-border-title \
        "$KICAD_PCB" 2>&1 | tee "$OUTPUT_DIR/$(outname "$PCB_STEM" pcb-pdf log)"; then
        print_success "PCB PDF export completed: $PCB_STEM"
        print_info "Output: $PCB_PDF"
      else
        print_error "PCB PDF export failed for $PCB_STEM"
        OVERALL_STATUS=1

        if [[ "$EXIT_ON_ERROR" == true ]]; then
          exit 1
        fi
      fi
    done
  else
    print_warning "Skipping PCB PDF export: No PCB files found"
  fi
fi

# Run kicad-diff
if [[ "$SKIP_DIFF" == false ]] && [[ ${#KICAD_PCBS[@]} -gt 0 ]] && [[ -n "$COMPARE_REF" ]]; then
  print_header "Generating Visual Diffs"

  # If we made a CI branch with template substitutions applied, diff against
  # that branch's tip so kidiff sees the rendered values. Otherwise use HEAD.
  DIFF_NEW_REF="${TEMPLATE_BRANCH:-HEAD}"

  for KICAD_PCB in "${KICAD_PCBS[@]}"; do
    PCB_STEM=$(basename "${KICAD_PCB%.kicad_pcb}")
    DIFF_OUTPUT="$OUTPUT_DIR/diff-${PCB_STEM}"
    mkdir -p "$DIFF_OUTPUT"

    print_info "Generating diff for: $PCB_STEM"

    # Run kidiff from project directory
    pushd "$PROJECT_DIR" > /dev/null

    DIFF_LOG="$OUTPUT_DIR/$(outname "$PCB_STEM" diff log)"
    DIFF_SUCCESS=false

    if kidiff \
      -o "$DIFF_OUTPUT" \
      -a "$DIFF_NEW_REF" \
      -b "$COMPARE_REF" \
      --webserver-disable \
      "$(basename "$KICAD_PCB")" 2>&1 | tee "$DIFF_LOG"; then
      print_success "Visual diff generated: $PCB_STEM"
      print_info "Output: $DIFF_OUTPUT"
      DIFF_SUCCESS=true
    else
      DIFF_EXIT_CODE=$?
      if grep -q "There is no difference" "$DIFF_LOG" 2>/dev/null; then
        print_warning "No changes detected in $PCB_STEM between $COMPARE_REF and $DIFF_NEW_REF"
      else
        print_error "Visual diff generation failed for $PCB_STEM (exit code $DIFF_EXIT_CODE)"
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
      print_header "Generating PDF Artifacts for $PCB_STEM"
      ARTIFACTS_OUTPUT="$OUTPUT_DIR/artifacts-${PCB_STEM}"

      if generate-diff-artifacts "$DIFF_OUTPUT" -o "$ARTIFACTS_OUTPUT" 2>&1 | tee "$OUTPUT_DIR/$(outname "$PCB_STEM" artifacts log)"; then
        print_success "PDF artifacts generated: $PCB_STEM"
        print_info "Triptych SVGs: $ARTIFACTS_OUTPUT/triptych-svgs/"

        # Rename final PDFs with prefix
        if [[ -f "$ARTIFACTS_OUTPUT/pcb-diff.pdf" ]]; then
          mv "$ARTIFACTS_OUTPUT/pcb-diff.pdf" "$OUTPUT_DIR/$(outname "$PCB_STEM" pcb-diff pdf)"
          print_info "PCB PDF: $(outname "$PCB_STEM" pcb-diff pdf)"
        fi
        if [[ -f "$ARTIFACTS_OUTPUT/schematic-diff.pdf" ]]; then
          mv "$ARTIFACTS_OUTPUT/schematic-diff.pdf" "$OUTPUT_DIR/$(outname "$PCB_STEM" schematic-diff pdf)"
          print_info "Schematic PDF: $(outname "$PCB_STEM" schematic-diff pdf)"
        fi
      else
        print_warning "PDF artifact generation had issues for $PCB_STEM"
        print_info "Triptych SVGs may still be available in: $ARTIFACTS_OUTPUT/triptych-svgs/"
      fi
    fi
  done
elif [[ "$SKIP_DIFF" == false ]] && [[ -z "$COMPARE_REF" ]]; then
  print_warning "Skipping visual diff: No comparison reference specified (use -c/--compare)"
elif [[ "$SKIP_DIFF" == false ]]; then
  print_warning "Skipping visual diff: No PCB files found"
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
