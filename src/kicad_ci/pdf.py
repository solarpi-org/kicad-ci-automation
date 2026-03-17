"""PDF conversion, cropping, footer stamping, and combining.

Handles the SVG→PDF pipeline via Inkscape, uniform cropping via
ghostscript bbox detection + PyPDF2, and final multi-page assembly
via pdfunite.
"""

import io
import subprocess
from pathlib import Path

from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import RectangleObject
from reportlab.pdfgen import canvas
from reportlab.lib.colors import black


def svg_to_pdf(svg_path, pdf_path):
    """Convert SVG to PDF via Inkscape, preserving vectors and group opacity.

    Returns:
        True on success, False on failure
    """
    try:
        result = subprocess.run([
            'inkscape',
            '--export-type=pdf',
            '--export-text-to-path',
            '--export-area-page',
            f'--export-filename={pdf_path}',
            str(svg_path),
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            return True
        print(f"  Inkscape failed for {svg_path.name}: {result.stderr.strip()}")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"  Inkscape error for {svg_path.name}: {e}")

    return False


def get_pdf_content_bbox(pdf_path):
    """Get bounding box of actual content in a PDF using ghostscript.

    Returns:
        (llx, lly, urx, ury) tuple, or None on failure
    """
    try:
        result = subprocess.run(
            ['gs', '-q', '-dNOPAUSE', '-dBATCH', '-sDEVICE=bbox', str(pdf_path)],
            capture_output=True, text=True,
        )
        for line in result.stderr.split('\n'):
            if line.startswith('%%BoundingBox:'):
                parts = line.split(':')[1].strip().split()
                if len(parts) == 4:
                    return tuple(float(x) for x in parts)
    except Exception as e:
        print(f"  Error getting bbox for {Path(pdf_path).name}: {e}")
    return None


def calculate_optimal_footer_font_size(pdf_files, footer_texts):
    """Find the largest font size that fits the longest text in the narrowest page.

    Returns:
        Font size in points, or None on failure
    """
    if not pdf_files or not footer_texts:
        return None

    try:
        min_page_width = float('inf')
        longest_text = ""

        for pdf_path, text in zip(pdf_files, footer_texts):
            reader = PdfReader(str(pdf_path))
            for page in reader.pages:
                llx = float(page.mediabox.lower_left[0])
                urx = float(page.mediabox.upper_right[0])
                min_page_width = min(min_page_width, urx - llx)
            if len(text) > len(longest_text):
                longest_text = text

        available_width = min_page_width * 0.80
        packet = io.BytesIO()
        can = canvas.Canvas(packet)

        font_size = 1.0
        for test_tenth in range(10, 101):  # 1.0 .. 10.0
            test_size = test_tenth / 10.0
            if can.stringWidth(longest_text, "Helvetica", test_size) <= available_width:
                font_size = test_size
            else:
                break
        return font_size

    except Exception as e:
        print(f"  Warning: Could not calculate optimal font size: {e}")
        return None


def add_footer_to_pdf(pdf_path, footer_text, font_size=None):
    """Stamp a centered footer line onto every page of a PDF (in-place).

    Args:
        pdf_path: Path to PDF file
        footer_text: Text to render
        font_size: Fixed size, or None to auto-fit per page

    Returns:
        True on success
    """
    try:
        pdf_path = Path(pdf_path)
        reader = PdfReader(str(pdf_path))
        writer = PdfWriter()

        for page in reader.pages:
            llx = float(page.mediabox.lower_left[0])
            lly = float(page.mediabox.lower_left[1])
            urx = float(page.mediabox.upper_right[0])
            ury = float(page.mediabox.upper_right[1])
            page_width = urx - llx
            page_height = ury - lly

            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=(urx, ury))

            fs = font_size
            if fs is None:
                max_fs = max(4, min(10, page_height * 0.03))
                fs = 2.0
                for test_tenth in range(20, int(max_fs * 10) + 1):
                    test_size = test_tenth / 10.0
                    if can.stringWidth(footer_text, "Helvetica", test_size) <= page_width * 0.90:
                        fs = test_size
                    else:
                        break

            can.setFont("Helvetica", fs)
            can.setFillColor(black)
            text_width = can.stringWidth(footer_text, "Helvetica", fs)
            can.drawString(llx + (page_width - text_width) / 2, lly + 2, footer_text)
            can.save()

            packet.seek(0)
            page.merge_page(PdfReader(packet).pages[0])
            writer.add_page(page)

        tmp_path = pdf_path.with_suffix('.tmp.pdf')
        with open(str(tmp_path), 'wb') as f:
            writer.write(f)
        tmp_path.replace(pdf_path)
        return True

    except Exception as e:
        print(f"  Error adding footer to {pdf_path.name}: {e}")
        return False


def crop_pdfs_uniform(pdf_files, margin=5, footer_font_size=None):
    """Crop all PDFs to the same bounding box (union of all content bounds).

    Uses ghostscript for bbox detection and PyPDF2 for cropping.
    Dimensions are capped at 297×210 points.

    Args:
        pdf_files: List of PDF paths to crop in-place
        margin: Points of padding around content
        footer_font_size: If set, reserve extra bottom space for footers
    """
    if not pdf_files:
        return

    MAX_WIDTH, MAX_HEIGHT = 297, 210

    print("  Analyzing content bounds...")

    bboxes = []
    for pdf_path in pdf_files:
        bbox = get_pdf_content_bbox(pdf_path)
        if bbox:
            bboxes.append((pdf_path, bbox))
        else:
            print(f"  Warning: Could not get bbox for {pdf_path.name}")

    if not bboxes:
        print("  Error: Could not determine bounding boxes")
        return

    min_llx = min(bb[0] for _, bb in bboxes)
    min_lly = min(bb[1] for _, bb in bboxes)
    max_urx = max(bb[2] for _, bb in bboxes)
    max_ury = max(bb[3] for _, bb in bboxes)

    bottom_margin = margin
    if footer_font_size:
        bottom_margin = max(margin, footer_font_size * 1.1)

    min_llx -= margin
    min_lly -= bottom_margin
    max_urx += margin
    max_ury += margin

    content_width = max_urx - min_llx
    content_height = max_ury - min_lly

    if content_width > MAX_WIDTH:
        print(f"  Warning: Content width ({content_width:.1f}pt) exceeds max, capping to {MAX_WIDTH:.1f}pt")
        cx = (min_llx + max_urx) / 2
        min_llx, max_urx = cx - MAX_WIDTH / 2, cx + MAX_WIDTH / 2
        content_width = MAX_WIDTH

    if content_height > MAX_HEIGHT:
        print(f"  Warning: Content height ({content_height:.1f}pt) exceeds max, capping to {MAX_HEIGHT:.1f}pt")
        cy = (min_lly + max_ury) / 2
        min_lly, max_ury = cy - MAX_HEIGHT / 2, cy + MAX_HEIGHT / 2
        content_height = MAX_HEIGHT

    print(f"  Unified crop area: {content_width:.1f} x {content_height:.1f} points")

    rect = [min_llx, min_lly, max_urx, max_ury]
    for pdf_path, _ in bboxes:
        try:
            reader = PdfReader(str(pdf_path))
            writer = PdfWriter()
            for page in reader.pages:
                page.cropbox = RectangleObject(rect)
                page.mediabox = RectangleObject(rect)
                writer.add_page(page)
            tmp_path = pdf_path.with_suffix('.tmp.pdf')
            with open(str(tmp_path), 'wb') as f:
                writer.write(f)
            tmp_path.replace(pdf_path)
        except Exception as e:
            print(f"  Error cropping {pdf_path.name}: {e}")

    print("  ✓ Applied uniform crop to all PDFs")


def combine_pdfs(pdf_files, output_pdf):
    """Combine multiple PDFs into one via pdfunite.

    Returns:
        True on success
    """
    if not pdf_files:
        return False
    try:
        cmd = ['pdfunite'] + [str(f) for f in pdf_files] + [str(output_pdf)]
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
