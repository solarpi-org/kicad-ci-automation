#!/usr/bin/env python3
"""
Generate PDF artifacts from KiCAD diff output using the triptych method.

This script takes the SVG outputs from kidiff and creates:
1. Combined triptych SVGs showing old (purple), new (green), and overlay
2. PDF files combining all layers (one for PCB, one for schematic)
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
import subprocess
import glob

try:
    from PIL import ImageColor
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def parse_css_color(color_str):
    """
    Parse any valid CSS color string and return RGB tuple (0-255).

    Uses PIL's ImageColor parser which supports all CSS color formats:
    hex, rgb(), rgba(), hsl(), hsla(), named colors, etc.

    Args:
        color_str: Any valid CSS color string

    Returns:
        Tuple of (r, g, b) values in 0-255 range
    """
    if HAS_PIL:
        # PIL's ImageColor.getrgb handles all CSS color formats
        rgb = ImageColor.getrgb(color_str)
        # Handle RGBA by discarding alpha
        return rgb[:3] if len(rgb) >= 3 else rgb
    else:
        # Fallback to basic hex parsing if PIL not available
        color_str = color_str.strip()
        if color_str.startswith('#'):
            hex_clean = color_str.lstrip('#')
            if len(hex_clean) == 3:
                hex_clean = ''.join([c*2 for c in hex_clean])
            if len(hex_clean) == 6:
                r = int(hex_clean[0:2], 16)
                g = int(hex_clean[2:4], 16)
                b = int(hex_clean[4:6], 16)
                return (r, g, b)
        raise ImportError("Pillow (PIL) is required for CSS color parsing.")


def hsl_to_rgb(h, s, l):
    """
    Convert HSL to RGB.

    Args:
        h: Hue in degrees (0-360)
        s: Saturation (0-1)
        l: Lightness (0-1)

    Returns:
        Tuple of (r, g, b) values in 0-255 range
    """
    h = h / 360.0  # Normalize to 0-1

    if s == 0:
        r = g = b = l
    else:
        def hue_to_rgb(p, q, t):
            if t < 0: t += 1
            if t > 1: t -= 1
            if t < 1/6: return p + (q - p) * 6 * t
            if t < 1/2: return q
            if t < 2/3: return p + (q - p) * (2/3 - t) * 6
            return p

        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        r = hue_to_rgb(p, q, h + 1/3)
        g = hue_to_rgb(p, q, h)
        b = hue_to_rgb(p, q, h - 1/3)

    return (int(r * 255), int(g * 255), int(b * 255))


def rgb_to_hsl(r, g, b):
    """
    Convert RGB to HSL.

    Args:
        r, g, b: RGB values in 0-255 range

    Returns:
        Tuple of (h, s, l) where h is 0-360, s and l are 0-1
    """
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    max_val = max(r, g, b)
    min_val = min(r, g, b)
    l = (max_val + min_val) / 2

    if max_val == min_val:
        h = s = 0  # achromatic
    else:
        d = max_val - min_val
        s = d / (2 - max_val - min_val) if l > 0.5 else d / (max_val + min_val)

        if max_val == r:
            h = (g - b) / d + (6 if g < b else 0)
        elif max_val == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        h /= 6

    return (h * 360, s, l)


def calculate_complementary_color(color_str):
    """
    Calculate the complementary color in HSL space (hue + 180°).

    Args:
        color_str: CSS color string (hex, rgb, hsl, or named)

    Returns:
        Complementary color as hex string
    """
    # Parse input color to RGB
    r, g, b = parse_css_color(color_str)

    # Convert to HSL
    h, s, l = rgb_to_hsl(r, g, b)

    # Rotate hue by 180 degrees for complementary color
    h_comp = (h + 180) % 360

    # Convert back to RGB
    r_comp, g_comp, b_comp = hsl_to_rgb(h_comp, s, l)

    return f'#{r_comp:02x}{g_comp:02x}{b_comp:02x}'


# Tint colors for diff visualization (complementary colors)
# TINT_COLOR_NEW accepts any valid CSS color format:
#   - Hex: '#1ce33d' or '#1e3'
#   - RGB: 'rgb(28, 227, 61)'
#   - HSL: 'hsl(133, 79%, 50%)'
#   - Named: 'green', 'lime', etc.
# Requires Pillow (PIL) for full CSS color support

TINT_COLOR_NEW = 'hsl(133, 85%, 45%)'  # Green for new/added content
# TINT_COLOR_NEW = 'hsl(192.1, 88.2%, 53.5%)' # Blue for new/added content
TINT_COLOR_OLD = calculate_complementary_color(TINT_COLOR_NEW)  # Automatically calculated complementary color


def strip_namespace(tag):
    """Remove namespace from XML tag."""
    if '}' in tag:
        return tag.split('}', 1)[1]
    return tag


def apply_color_tint(color_str, tint_type):
    """
    Apply a color tint directly to a color value using complementary colors.

    Args:
        color_str: Color string (e.g., '#000000', 'rgb(0,0,0)', 'black')
        tint_type: 'old' for complementary tint, 'new' for primary tint

    Returns:
        Modified color string
    """
    if not color_str or color_str in ['none', 'transparent']:
        return color_str

    # Parse original color (only handle hex in SVGs for now)
    if color_str.startswith('#'):
        try:
            hex_color = color_str.lstrip('#')
            if len(hex_color) == 3:
                hex_color = ''.join([c*2 for c in hex_color])
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
        except ValueError:
            raise ValueError(f"Invalid hex color format: {color_str}")
    else:
        # For non-hex colors in SVG, skip tinting
        return color_str

    # Get tint color based on type and parse using CSS color parser
    tint_color_str = TINT_COLOR_OLD if tint_type == 'old' else TINT_COLOR_NEW
    tint_r, tint_g, tint_b = parse_css_color(tint_color_str)

    # Convert tint to 0-1 range
    tint_r = tint_r / 255.0
    tint_g = tint_g / 255.0
    tint_b = tint_b / 255.0

    # Apply additive tint (add tint color to original, clamped to 1.0)
    r_new = min(1.0, r + tint_r)
    g_new = min(1.0, g + tint_g)
    b_new = min(1.0, b + tint_b)

    # Convert back to hex
    r_int = int(r_new * 255)
    g_int = int(g_new * 255)
    b_int = int(b_new * 255)

    return f'#{r_int:02x}{g_int:02x}{b_int:02x}'


def copy_element_recursive(element, parent, svg_ns, tint_type=None):
    """
    Recursively copy an element and all its children, preserving vector data.
    Optionally applies color tinting to stroke/fill attributes.

    Args:
        element: Source element to copy
        parent: Parent element to attach to
        svg_ns: SVG namespace
        tint_type: 'old' or 'new' for color tinting
    """
    # Create new element with same tag
    tag = strip_namespace(element.tag)
    attribs = element.attrib.copy()

    # Apply color tinting to fill and stroke attributes
    if tint_type:
        if 'fill' in attribs and attribs['fill'] not in ['none', 'transparent']:
            attribs['fill'] = apply_color_tint(attribs['fill'], tint_type)

        if 'stroke' in attribs and attribs['stroke'] not in ['none', 'transparent']:
            attribs['stroke'] = apply_color_tint(attribs['stroke'], tint_type)

        # Also handle style attribute
        if 'style' in attribs:
            style = attribs['style']
            style_parts = []

            for part in style.split(';'):
                if ':' in part:
                    key, value = part.split(':', 1)
                    key = key.strip()
                    value = value.strip()

                    if key == 'fill' and value not in ['none', 'transparent']:
                        value = apply_color_tint(value, tint_type)
                    elif key == 'stroke' and value not in ['none', 'transparent']:
                        value = apply_color_tint(value, tint_type)

                    style_parts.append(f'{key}:{value}')
                elif part.strip():
                    style_parts.append(part.strip())

            attribs['style'] = ';'.join(style_parts)

    new_elem = ET.SubElement(parent, f'{{{svg_ns}}}{tag}', attribs)

    # Copy text content
    if element.text:
        new_elem.text = element.text
    if element.tail:
        new_elem.tail = element.tail

    # Recursively copy children
    for child in element:
        copy_element_recursive(child, new_elem, svg_ns, tint_type)

    return new_elem


def create_triptych_svg(old_svg_path, new_svg_path, output_svg_path, title=""):
    """
    Create a triptych SVG that combines old and new versions with color tinting.
    Embeds the actual SVG content (not as raster images) to preserve vectors.

    Colors are tinted directly at the element level (not via SVG filters) to ensure
    vector content is preserved when converting to PDF. Complementary colors are used:
    - Old version: Purple tint (#CC33B1) - removed/old content
    - New version: Green tint (#33CC4E) - added/new content with 50% opacity at GROUP level

    Opacity is applied at the group level (not individual elements) to prevent
    overlapping elements from compounding opacity. Modern PDF converters like
    Inkscape properly preserve group-level opacity as vectors.

    Args:
        old_svg_path: Path to the old version SVG
        new_svg_path: Path to the new version SVG
        output_svg_path: Path to save the combined triptych SVG
        title: Title to display on the SVG
    """
    svg_ns = "http://www.w3.org/2000/svg"
    xlink_ns = "http://www.w3.org/1999/xlink"

    ET.register_namespace('', svg_ns)
    ET.register_namespace('xlink', xlink_ns)

    # Parse old and new SVG files
    try:
        old_tree = ET.parse(old_svg_path)
        old_root = old_tree.getroot()

        new_tree = ET.parse(new_svg_path)
        new_root = new_tree.getroot()
    except Exception as e:
        print(f"Error parsing SVG files: {e}")
        return

    # Get dimensions from old SVG
    viewbox = old_root.get('viewBox')
    if viewbox:
        vb_parts = viewbox.split()
        width, height = vb_parts[2], vb_parts[3]
        viewbox_attr = viewbox
    else:
        width = old_root.get('width', '1000').rstrip('px').rstrip('mm')
        height = old_root.get('height', '1000').rstrip('px').rstrip('mm')
        viewbox_attr = f'0 0 {width} {height}'

    # Create root SVG element
    svg = ET.Element(f'{{{svg_ns}}}svg', {
        'xmlns': svg_ns,
        'xmlns:xlink': xlink_ns,
        'viewBox': viewbox_attr,
        'width': width,
        'height': height,
        'version': '1.1'
    })

    # Add title if provided
    if title:
        title_elem = ET.SubElement(svg, f'{{{svg_ns}}}title')
        title_elem.text = title

    # Create defs for filters and copy any defs from source SVGs
    defs = ET.SubElement(svg, f'{{{svg_ns}}}defs')

    # Copy defs from old SVG (gradients, patterns, etc.)
    for old_defs in old_root.findall(f'.//{{{svg_ns}}}defs'):
        for child in old_defs:
            copy_element_recursive(child, defs, svg_ns, tint_type=None)

    # Copy defs from new SVG
    for new_defs in new_root.findall(f'.//{{{svg_ns}}}defs'):
        for child in new_defs:
            # Avoid duplicates by checking id
            child_id = child.get('id')
            if child_id:
                existing = defs.find(f'.//*[@id="{child_id}"]')
                if existing is None:
                    copy_element_recursive(child, defs, svg_ns, tint_type=None)
            else:
                copy_element_recursive(child, defs, svg_ns, tint_type=None)

    # Create group for old version with purple tint applied directly to colors
    old_group = ET.SubElement(svg, f'{{{svg_ns}}}g', {
        'id': 'old-version'
    })

    # Copy all children from old SVG root with purple tinting
    for child in old_root:
        tag = strip_namespace(child.tag)
        if tag not in ['defs', 'title', 'metadata']:
            copy_element_recursive(child, old_group, svg_ns, tint_type='old')

    # Create group for new version with green tint and 50% opacity at GROUP level
    # This ensures overlapping elements don't compound opacity
    new_group = ET.SubElement(svg, f'{{{svg_ns}}}g', {
        'id': 'new-version',
        'opacity': '0.5'
    })

    # Copy all children from new SVG root with green tinting
    for child in new_root:
        tag = strip_namespace(child.tag)
        if tag not in ['defs', 'title', 'metadata']:
            copy_element_recursive(child, new_group, svg_ns, tint_type='new')

    # Write output SVG
    tree = ET.ElementTree(svg)
    ET.indent(tree, space='  ')
    tree.write(output_svg_path, encoding='utf-8', xml_declaration=True)
    print(f"  Created: {output_svg_path}")


def find_svg_pairs(diff_output_dir):
    """
    Find pairs of SVG files (old and new versions) in the kidiff output directory.

    Returns:
        dict: Dictionary with keys 'pcb' and 'sch', each containing lists of (old, new, name) tuples
    """
    # Find the two commit hash directories
    subdirs = [d for d in Path(diff_output_dir).iterdir() if d.is_dir() and not d.name.startswith('.')]
    if len(subdirs) < 2:
        print(f"Error: Expected 2 commit directories in {diff_output_dir}, found {len(subdirs)}")
        return {'pcb': [], 'sch': []}

    # Put HEAD first (new version), then the other (old version)
    old_dir = [ d for d in subdirs if d.name != 'HEAD' ][0]
    new_dir = [ d for d in subdirs if d.name == 'HEAD' ][0]
    # old_dir, new_dir = subdirs[0], subdirs[1]

    print(f"Old version: {old_dir.name}")
    print(f"New version: {new_dir.name}")

    pairs = {'pcb': [], 'sch': []}

    # Find PCB layer SVGs
    pcb_old_dir = old_dir / 'pcb'
    pcb_new_dir = new_dir / 'pcb'

    if pcb_old_dir.exists() and pcb_new_dir.exists():
        old_svgs = {f.name: f for f in pcb_old_dir.glob('*.svg')}
        new_svgs = {f.name: f for f in pcb_new_dir.glob('*.svg')}

        # Match pairs
        common_names = set(old_svgs.keys()) & set(new_svgs.keys())
        for name in sorted(common_names):
            pairs['pcb'].append((old_svgs[name], new_svgs[name], name))

    # Find schematic SVGs
    sch_old_dir = old_dir / 'sch'
    sch_new_dir = new_dir / 'sch'

    if sch_old_dir.exists() and sch_new_dir.exists():
        old_svgs = {f.name: f for f in sch_old_dir.glob('*.svg')}
        new_svgs = {f.name: f for f in sch_new_dir.glob('*.svg')}

        common_names = set(old_svgs.keys()) & set(new_svgs.keys())
        for name in sorted(common_names):
            pairs['sch'].append((old_svgs[name], new_svgs[name], name))

    return pairs


def svg_to_pdf(svg_path, pdf_path):
    """
    Convert a single SVG to PDF preserving vector content and group opacity.

    Inkscape is tried first as it has excellent support for group-level opacity
    while maintaining full vector quality.
    """
    # Try inkscape first - excellent at preserving vectors and group opacity
    try:
        result = subprocess.run([
            'inkscape',
            '--export-type=pdf',
            '--export-text-to-path',  # Convert text to paths for compatibility
            '--export-area-page',  # Use page area
            f'--export-filename={pdf_path}',
            str(svg_path)
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            return True
        else:
            print(f"  Inkscape failed for {svg_path.name}: {result.stderr.strip()}")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"  Inkscape error for {svg_path.name}: {e}")

    # Try svglib + reportlab (good for simple vectors, may not handle group opacity)
    # try:
    #     from svglib.svglib import svg2rlg
    #     from reportlab.graphics import renderPDF

    #     drawing = svg2rlg(str(svg_path))
    #     if drawing:
    #         renderPDF.drawToFile(drawing, str(pdf_path))
    #         return True
    # except (ImportError, Exception) as e:
    #     # svglib can fail on complex SVGs or unsupported features
    #     pass

    # # Try rsvg-convert with Cairo backend
    # try:
    #     result = subprocess.run([
    #         'rsvg-convert',
    #         '-f', 'pdf',
    #         '-o', str(pdf_path),
    #         str(svg_path)
    #     ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    #     if result.returncode == 0:
    #         return True
    #     else:
    #         print(f"  rsvg-convert failed for {svg_path.name}: {result.stderr.strip()}")
    # except FileNotFoundError:
    #     pass
    # except Exception as e:
    #     print(f"  rsvg-convert error for {svg_path.name}: {e}")

    # # Try cairosvg as last resort
    # try:
    #     import cairosvg
    #     cairosvg.svg2pdf(url=str(svg_path), write_to=str(pdf_path))
    #     return True
    # except (ImportError, Exception) as e:
    #     print(f"  cairosvg failed for {svg_path.name}: {e}")

    return False


def get_pdf_content_bbox(pdf_path):
    """
    Get the bounding box of actual content in a PDF using ghostscript.

    Args:
        pdf_path: Path to PDF file

    Returns:
        tuple: (llx, lly, urx, ury) bounding box or None
    """
    try:
        result = subprocess.run([
            'gs',
            '-q',
            '-dNOPAUSE',
            '-dBATCH',
            '-sDEVICE=bbox',
            str(pdf_path)
        ], capture_output=True, text=True)

        # Parse bbox from stderr (gs outputs bbox info there)
        for line in result.stderr.split('\n'):
            if line.startswith('%%BoundingBox:'):
                parts = line.split(':')[1].strip().split()
                if len(parts) == 4:
                    return tuple(float(x) for x in parts)
    except Exception as e:
        print(f"  Error getting bbox for {pdf_path.name}: {e}")

    return None


def add_footer_to_pdf(pdf_path, footer_text):
    """
    Add a footer text to a PDF file with proportional font size.

    Args:
        pdf_path: Path to PDF file
        footer_text: Text to display in footer
    """
    try:
        from PyPDF2 import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas
        from reportlab.lib.colors import black
        import io
    except ImportError:
        print(f"  Warning: Cannot add footer, missing dependencies")
        return False

    try:
        reader = PdfReader(str(pdf_path))
        writer = PdfWriter()

        for page in reader.pages:
            # Get the actual bounding box from mediabox
            llx = float(page.mediabox.lower_left[0])
            lly = float(page.mediabox.lower_left[1])
            urx = float(page.mediabox.upper_right[0])
            ury = float(page.mediabox.upper_right[1])

            # Calculate actual width and height
            page_width = urx - llx
            page_height = ury - lly

            # Calculate proportional font size (3% of page height, clamped between 4-10pt)
            font_size = max(4, min(10, page_height * 0.03))

            # Create a canvas that matches the full coordinate space
            # We need to use the upper_right corner to get the full extent
            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=(urx, ury))

            # Set font, size, and color
            can.setFont("Helvetica", font_size)
            can.setFillColor(black)

            # Calculate text position (centered horizontally, at bottom with margin)
            text_width = can.stringWidth(footer_text, "Helvetica", font_size)
            x_pos = llx + (page_width - text_width) / 2
            y_pos = lly + 2  # 2 points from bottom edge

            # Draw the text
            can.drawString(x_pos, y_pos, footer_text)
            can.save()

            # Move to the beginning of the BytesIO buffer
            packet.seek(0)
            footer_pdf = PdfReader(packet)
            footer_page = footer_pdf.pages[0]

            # Merge the footer onto the page
            page.merge_page(footer_page)
            writer.add_page(page)

        # Write to temporary file
        tmp_path = pdf_path.with_suffix('.tmp.pdf')
        with open(str(tmp_path), 'wb') as output_file:
            writer.write(output_file)

        # Replace original
        tmp_path.replace(pdf_path)
        return True

    except Exception as e:
        print(f"  Error adding footer to {pdf_path.name}: {e}")
        return False


def crop_pdfs_uniform(pdf_files, margin=5, add_footer_space=False):
    """
    Crop all PDF files to the same bounding box (size of biggest content).

    Uses ghostscript to detect content bounds, then PyPDF2 to apply uniform cropping.
    Maximum size is capped at 297x210 points.

    Args:
        pdf_files: List of PDF file paths to crop in-place
        margin: Margin to add around content in points (default: 5)
        add_footer_space: If True, add proportional space at bottom for footer (default: False)
    """
    if not pdf_files:
        return

    try:
        from PyPDF2 import PdfReader, PdfWriter
        from PyPDF2.generic import RectangleObject
    except ImportError:
        print("  Warning: PyPDF2 not available, skipping PDF cropping")
        return

    # Maximum dimensions in points
    MAX_WIDTH = 297
    MAX_HEIGHT = 210

    print("  Analyzing content bounds...")

    # First pass: get bounding box for each PDF
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

    # Find the maximum bounding box that encompasses all content
    min_llx = min(bbox[0] for _, bbox in bboxes)
    min_lly = min(bbox[1] for _, bbox in bboxes)
    max_urx = max(bbox[2] for _, bbox in bboxes)
    max_ury = max(bbox[3] for _, bbox in bboxes)

    # Calculate footer margin proportionally if needed (10% of content height, min 10pt)
    content_height_raw = max_ury - min_lly
    footer_margin = max(10, content_height_raw * 0.10) if add_footer_space else 0

    # Add margin (extra space at bottom for footer)
    min_llx -= margin
    min_lly -= (margin + footer_margin)  # Extra space at bottom for footer
    max_urx += margin
    max_ury += margin

    content_width = max_urx - min_llx
    content_height = max_ury - min_lly

    # Cap at maximum size
    if content_width > MAX_WIDTH:
        print(f"  Warning: Content width ({content_width:.1f}pt) exceeds max, capping to {MAX_WIDTH:.1f}pt")
        center_x = (min_llx + max_urx) / 2
        min_llx = center_x - MAX_WIDTH / 2
        max_urx = center_x + MAX_WIDTH / 2
        content_width = MAX_WIDTH

    if content_height > MAX_HEIGHT:
        print(f"  Warning: Content height ({content_height:.1f}pt) exceeds max, capping to {MAX_HEIGHT:.1f}pt")
        center_y = (min_lly + max_ury) / 2
        min_lly = center_y - MAX_HEIGHT / 2
        max_ury = center_y + MAX_HEIGHT / 2
        content_height = MAX_HEIGHT

    print(f"  Unified crop area: {content_width:.1f} x {content_height:.1f} points")

    # Second pass: apply uniform crop to all PDFs
    for pdf_path, bbox in bboxes:
        try:
            reader = PdfReader(str(pdf_path))
            writer = PdfWriter()

            for page in reader.pages:
                # Set the crop box (what's visible)
                page.cropbox = RectangleObject([
                    min_llx,
                    min_lly,
                    max_urx,
                    max_ury
                ])

                # Also set mediabox to the crop box for clean output
                page.mediabox = RectangleObject([
                    min_llx,
                    min_lly,
                    max_urx,
                    max_ury
                ])

                writer.add_page(page)

            # Write back to original file
            tmp_path = pdf_path.with_suffix('.tmp.pdf')
            with open(str(tmp_path), 'wb') as output_file:
                writer.write(output_file)

            # Replace original
            tmp_path.replace(pdf_path)

        except Exception as e:
            print(f"  Error cropping {pdf_path.name}: {e}")

    print(f"  ✓ Applied uniform crop to all PDFs")


def combine_pdfs(pdf_files, output_pdf):
    """Combine multiple PDF files into one using ghostscript or pdfunite."""
    if not pdf_files:
        return False

    # Try pdfunite first (simpler)
    try:
        cmd = ['pdfunite'] + [str(f) for f in pdf_files] + [str(output_pdf)]
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Fall back to ghostscript
    # try:
    #     cmd = ['gs', '-dBATCH', '-dNOPAUSE', '-q', '-sDEVICE=pdfwrite',
    #            f'-sOutputFile={output_pdf}'] + [str(f) for f in pdf_files]
    #     subprocess.run(cmd, check=True, capture_output=True)
    #     return True
    # except (subprocess.CalledProcessError, FileNotFoundError):
    #     pass

    return False


def main():
    parser = argparse.ArgumentParser(
        description='Generate PDF artifacts from KiCAD diff output'
    )
    parser.add_argument(
        'diff_dir',
        help='Path to kidiff output directory containing commit hash subdirectories'
    )
    parser.add_argument(
        '-o', '--output',
        default='.',
        help='Output directory for generated artifacts (default: current directory)'
    )
    parser.add_argument(
        '--no-pdf',
        action='store_true',
        help='Skip PDF generation, only create triptych SVGs'
    )

    args = parser.parse_args()

    diff_dir = Path(args.diff_dir)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not diff_dir.exists():
        print(f"Error: Diff directory does not exist: {diff_dir}")
        return 1

    # Create output subdirectories
    triptych_dir = output_dir / 'triptych-svgs'
    triptych_dir.mkdir(exist_ok=True)

    print("Finding SVG pairs...")
    pairs = find_svg_pairs(diff_dir)

    if not pairs['pcb'] and not pairs['sch']:
        print("No SVG pairs found!")
        return 1

    print(f"\nFound {len(pairs['pcb'])} PCB layers and {len(pairs['sch'])} schematic pages")

    # Generate triptych SVGs
    print("\nGenerating triptych SVGs...")

    pcb_triptychs = []
    if pairs['pcb']:
        print(f"\nPCB layers ({len(pairs['pcb'])}):")
        for old_svg, new_svg, name in pairs['pcb']:
            output_svg = triptych_dir / f'pcb-{name}'
            create_triptych_svg(old_svg, new_svg, output_svg, f"PCB: {name}")
            pcb_triptychs.append(output_svg)

    sch_triptychs = []
    if pairs['sch']:
        print(f"\nSchematic pages ({len(pairs['sch'])}):")
        for old_svg, new_svg, name in pairs['sch']:
            output_svg = triptych_dir / f'sch-{name}'
            create_triptych_svg(old_svg, new_svg, output_svg, f"Schematic: {name}")
            sch_triptychs.append(output_svg)

    if args.no_pdf:
        print("\nSkipping PDF generation (--no-pdf specified)")
        return 0

    # Convert SVGs to PDFs and combine
    print("\nGenerating PDFs...")

    pdf_dir = output_dir / 'pdfs'
    pdf_dir.mkdir(exist_ok=True)

    # Process PCB
    if pcb_triptychs:
        print(f"\nConverting {len(pcb_triptychs)} PCB SVGs to PDF...")
        pcb_pdfs = []
        for svg in pcb_triptychs:
            pdf = pdf_dir / svg.with_suffix('.pdf').name
            if svg_to_pdf(svg, pdf):
                pcb_pdfs.append(pdf)
                print(f"  ✓ {pdf.name}")
            else:
                print(f"  ✗ Failed to convert {svg.name}")

        if pcb_pdfs:
            print(f"\nCropping {len(pcb_pdfs)} PCB PDFs to uniform size...")
            crop_pdfs_uniform(pcb_pdfs, margin=5, add_footer_space=True)

            print(f"\nAdding layer labels to {len(pcb_pdfs)} PCB PDFs...")
            for pdf in pcb_pdfs:
                # Extract layer name from filename (e.g., 'pcb-F.Cu.svg.pdf' -> 'F.Cu')
                layer_name = pdf.stem.replace('pcb-', '', 1).replace('.svg', '')
                footer_text = f"Layer: {layer_name}"
                if add_footer_to_pdf(pdf, footer_text):
                    print(f"  ✓ Added footer to {pdf.name}")
                else:
                    print(f"  ✗ Failed to add footer to {pdf.name}")

            combined_pcb = output_dir / 'pcb-diff.pdf'
            if combine_pdfs(pcb_pdfs, combined_pcb):
                print(f"\n✓ Created combined PCB PDF: {combined_pcb}")
            else:
                print(f"\n✗ Failed to combine PCB PDFs")
                print(f"  Individual PDFs available in: {pdf_dir}")

    # Process Schematic
    if sch_triptychs:
        print(f"\nConverting {len(sch_triptychs)} schematic SVGs to PDF...")
        sch_pdfs = []
        for svg in sch_triptychs:
            pdf = pdf_dir / svg.with_suffix('.pdf').name
            if svg_to_pdf(svg, pdf):
                sch_pdfs.append(pdf)
                print(f"  ✓ {pdf.name}")
            else:
                print(f"  ✗ Failed to convert {svg.name}")

        if sch_pdfs:
            print(f"\nCropping {len(sch_pdfs)} schematic PDFs to uniform size...")
            crop_pdfs_uniform(sch_pdfs, margin=5, add_footer_space=False)

            combined_sch = output_dir / 'schematic-diff.pdf'
            if combine_pdfs(sch_pdfs, combined_sch):
                print(f"\n✓ Created combined schematic PDF: {combined_sch}")
            else:
                print(f"\n✗ Failed to combine schematic PDFs")
                print(f"  Individual PDFs available in: {pdf_dir}")

    print(f"\nAll artifacts saved to: {output_dir}")
    print(f"  Triptych SVGs: {triptych_dir}")
    if not args.no_pdf:
        print(f"  PDFs: {output_dir}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
