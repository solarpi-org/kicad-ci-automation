#!/usr/bin/env python3
"""CLI entrypoint for generating diff artifacts from kidiff output.

Creates triptych overlay SVGs and combined per-layer PDFs for PCB and
schematic diffs.
"""

import argparse
import sys
from pathlib import Path

from kicad_ci.triptych import find_svg_pairs, create_triptych_svg
from kicad_ci.pdf import (
    svg_to_pdf,
    crop_pdfs_uniform,
    calculate_optimal_footer_font_size,
    add_footer_to_pdf,
    combine_pdfs,
)


def _process_category(label, triptychs, pdf_dir, output_dir, add_footers=False):
    """Convert triptych SVGs → individual PDFs → cropped → combined PDF.

    Args:
        label: Human label ('PCB' or 'Schematic')
        triptychs: List of triptych SVG paths
        pdf_dir: Directory for individual PDFs
        output_dir: Directory for the combined PDF
        add_footers: Whether to stamp layer labels on each page
    """
    if not triptychs:
        return

    print(f"\nConverting {len(triptychs)} {label} SVGs to PDF...")
    pdfs = []
    for svg in triptychs:
        pdf = pdf_dir / svg.with_suffix('.pdf').name
        if svg_to_pdf(svg, pdf):
            pdfs.append(pdf)
            print(f"  ✓ {pdf.name}")
        else:
            print(f"  ✗ Failed to convert {svg.name}")

    if not pdfs:
        return

    footer_font_size = 6 if add_footers else None
    print(f"\nCropping {len(pdfs)} {label} PDFs to uniform size...")
    crop_pdfs_uniform(pdfs, margin=5, footer_font_size=footer_font_size)

    if add_footers:
        footer_texts = []
        for pdf in pdfs:
            layer_name = '-'.join(pdf.stem.replace('.svg', '').split('-')[-2:])
            footer_texts.append(f"Layer: {layer_name}")

        optimal_size = calculate_optimal_footer_font_size(pdfs, footer_texts)
        if optimal_size:
            print(f"  Using font size: {optimal_size:.1f}pt (fits longest layer name)")

        print(f"\nAdding layer labels to {len(pdfs)} {label} PDFs...")
        for pdf, text in zip(pdfs, footer_texts):
            if add_footer_to_pdf(pdf, text, font_size=optimal_size):
                print(f"  ✓ Added footer to {pdf.name}")
            else:
                print(f"  ✗ Failed to add footer to {pdf.name}")

    slug = label.lower().replace(' ', '-')
    combined = output_dir / f'{slug}-diff.pdf'
    if combine_pdfs(pdfs, combined):
        print(f"\n✓ Created combined {label} PDF: {combined}")
    else:
        print(f"\n✗ Failed to combine {label} PDFs")
        print(f"  Individual PDFs available in: {pdf_dir}")


def main():
    parser = argparse.ArgumentParser(
        description='Generate PDF artifacts from KiCAD diff output',
    )
    parser.add_argument(
        'diff_dir',
        help='Path to kidiff output directory containing commit hash subdirectories',
    )
    parser.add_argument(
        '-o', '--output', default='.',
        help='Output directory for generated artifacts (default: .)',
    )
    parser.add_argument(
        '--no-pdf', action='store_true',
        help='Skip PDF generation, only create triptych SVGs',
    )
    parser.add_argument(
        '--new-ref', type=str, default=None,
        help='Directory name of the new (PR head) commit in kidiff output',
    )
    parser.add_argument(
        '--old-ref', type=str, default=None,
        help='Directory name of the old (base) commit in kidiff output',
    )
    args = parser.parse_args()

    diff_dir = Path(args.diff_dir)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not diff_dir.exists():
        print(f"Error: Diff directory does not exist: {diff_dir}")
        return 1

    triptych_dir = output_dir / 'triptych-svgs'
    triptych_dir.mkdir(exist_ok=True)

    print("Finding SVG pairs...")
    pairs = find_svg_pairs(diff_dir, new_ref=args.new_ref, old_ref=args.old_ref)

    if not pairs['pcb'] and not pairs['sch']:
        print("No SVG pairs found!")
        return 1

    print(f"\nFound {len(pairs['pcb'])} PCB layers and {len(pairs['sch'])} schematic pages")
    print("\nGenerating triptych SVGs...")

    pcb_triptychs = []
    if pairs['pcb']:
        print(f"\nPCB layers ({len(pairs['pcb'])}):")
        for old_svg, new_svg, name in pairs['pcb']:
            out = triptych_dir / f'pcb-{name}'
            create_triptych_svg(old_svg, new_svg, out, f"PCB: {name}")
            pcb_triptychs.append(out)

    sch_triptychs = []
    if pairs['sch']:
        print(f"\nSchematic pages ({len(pairs['sch'])}):")
        for old_svg, new_svg, name in pairs['sch']:
            out = triptych_dir / f'sch-{name}'
            create_triptych_svg(old_svg, new_svg, out, f"Schematic: {name}")
            sch_triptychs.append(out)

    if args.no_pdf:
        print("\nSkipping PDF generation (--no-pdf specified)")
        return 0

    print("\nGenerating PDFs...")
    pdf_dir = output_dir / 'pdfs'
    pdf_dir.mkdir(exist_ok=True)

    _process_category('pcb', pcb_triptychs, pdf_dir, output_dir, add_footers=True)
    _process_category('schematic', sch_triptychs, pdf_dir, output_dir, add_footers=False)

    print(f"\nAll artifacts saved to: {output_dir}")
    print(f"  Triptych SVGs: {triptych_dir}")
    if not args.no_pdf:
        print(f"  PDFs: {output_dir}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
