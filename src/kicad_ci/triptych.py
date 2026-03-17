"""SVG triptych generation for KiCAD visual diffs.

Takes old/new SVG pairs from kidiff output and produces overlay SVGs
with color-tinted layers (purple = old, green = new at 50% opacity).
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from .color import apply_color_tint


def _strip_namespace(tag):
    """Remove XML namespace prefix from a tag."""
    if '}' in tag:
        return tag.split('}', 1)[1]
    return tag


def _copy_element_recursive(element, parent, svg_ns, tint_type=None):
    """Recursively copy an SVG element tree, optionally tinting colors.

    Tinting is applied directly to fill/stroke attributes and inline styles
    so that vector content is preserved through PDF conversion.
    """
    tag = _strip_namespace(element.tag)
    attribs = element.attrib.copy()

    if tint_type:
        for attr in ('fill', 'stroke'):
            if attr in attribs and attribs[attr] not in ('none', 'transparent'):
                attribs[attr] = apply_color_tint(attribs[attr], tint_type)

        if 'style' in attribs:
            style_parts = []
            for part in attribs['style'].split(';'):
                if ':' in part:
                    key, value = part.split(':', 1)
                    key, value = key.strip(), value.strip()
                    if key in ('fill', 'stroke') and value not in ('none', 'transparent'):
                        value = apply_color_tint(value, tint_type)
                    style_parts.append(f'{key}:{value}')
                elif part.strip():
                    style_parts.append(part.strip())
            attribs['style'] = ';'.join(style_parts)

    new_elem = ET.SubElement(parent, f'{{{svg_ns}}}{tag}', attribs)
    if element.text:
        new_elem.text = element.text
    if element.tail:
        new_elem.tail = element.tail

    for child in element:
        _copy_element_recursive(child, new_elem, svg_ns, tint_type)
    return new_elem


def create_triptych_svg(old_svg_path, new_svg_path, output_svg_path, title=""):
    """Create a triptych overlay SVG from old and new versions.

    Old content is tinted with the complementary (purple) color.
    New content is tinted green and rendered at 50% group-level opacity.
    Group-level opacity prevents overlapping elements from compounding
    and is well-supported by Inkscape's PDF export.

    Args:
        old_svg_path: Path to old version SVG
        new_svg_path: Path to new version SVG
        output_svg_path: Path to write the combined SVG
        title: Optional title embedded in the SVG
    """
    svg_ns = "http://www.w3.org/2000/svg"
    xlink_ns = "http://www.w3.org/1999/xlink"
    ET.register_namespace('', svg_ns)
    ET.register_namespace('xlink', xlink_ns)

    try:
        old_root = ET.parse(old_svg_path).getroot()
        new_root = ET.parse(new_svg_path).getroot()
    except Exception as e:
        print(f"Error parsing SVG files: {e}")
        return

    # Determine dimensions from old SVG
    viewbox = old_root.get('viewBox')
    if viewbox:
        vb_parts = viewbox.split()
        width, height = vb_parts[2], vb_parts[3]
        viewbox_attr = viewbox
    else:
        width = old_root.get('width', '1000').rstrip('px').rstrip('mm')
        height = old_root.get('height', '1000').rstrip('px').rstrip('mm')
        viewbox_attr = f'0 0 {width} {height}'

    svg = ET.Element(f'{{{svg_ns}}}svg', {
        'xmlns': svg_ns, 'xmlns:xlink': xlink_ns,
        'viewBox': viewbox_attr, 'width': width, 'height': height,
        'version': '1.1',
    })

    if title:
        t = ET.SubElement(svg, f'{{{svg_ns}}}title')
        t.text = title

    # Merge <defs> from both sources
    defs = ET.SubElement(svg, f'{{{svg_ns}}}defs')
    seen_ids = set()

    for root in (old_root, new_root):
        for defs_elem in root.findall(f'.//{{{svg_ns}}}defs'):
            for child in defs_elem:
                child_id = child.get('id')
                if child_id and child_id in seen_ids:
                    continue
                if child_id:
                    seen_ids.add(child_id)
                _copy_element_recursive(child, defs, svg_ns, tint_type=None)

    skip_tags = {'defs', 'title', 'metadata'}

    # Old version — full opacity, purple tint
    old_group = ET.SubElement(svg, f'{{{svg_ns}}}g', {'id': 'old-version'})
    for child in old_root:
        if _strip_namespace(child.tag) not in skip_tags:
            _copy_element_recursive(child, old_group, svg_ns, tint_type='old')

    # New version — 50% group opacity, green tint
    new_group = ET.SubElement(svg, f'{{{svg_ns}}}g', {
        'id': 'new-version', 'opacity': '0.5',
    })
    for child in new_root:
        if _strip_namespace(child.tag) not in skip_tags:
            _copy_element_recursive(child, new_group, svg_ns, tint_type='new')

    tree = ET.ElementTree(svg)
    ET.indent(tree, space='  ')
    tree.write(output_svg_path, encoding='utf-8', xml_declaration=True)
    print(f"  Created: {output_svg_path}")


def _is_commit_dir(name):
    """Check if a directory name looks like a git commit hash or HEAD."""
    if name == 'HEAD':
        return True
    # Full or abbreviated hex SHA
    return len(name) >= 7 and all(c in '0123456789abcdef' for c in name)


def find_svg_pairs(diff_output_dir):
    """Find matching old/new SVG pairs in a kidiff output directory.

    Args:
        diff_output_dir: Root directory containing commit-hash subdirectories

    Returns:
        Dict with 'pcb' and 'sch' keys, each a list of (old, new, name) tuples
    """
    subdirs = [d for d in Path(diff_output_dir).iterdir()
               if d.is_dir() and _is_commit_dir(d.name)]

    if len(subdirs) < 2:
        print(f"Error: Expected 2 commit directories in {diff_output_dir}, found {len(subdirs)}")
        return {'pcb': [], 'sch': []}

    old_dir = next(d for d in subdirs if d.name != 'HEAD')
    new_dir = next(d for d in subdirs if d.name == 'HEAD')
    print(f"Old version: {old_dir.name}")
    print(f"New version: {new_dir.name}")

    pairs = {'pcb': [], 'sch': []}

    for category in ('pcb', 'sch'):
        cat_old = old_dir / category
        cat_new = new_dir / category
        if not (cat_old.exists() and cat_new.exists()):
            continue
        old_svgs = {f.name: f for f in cat_old.glob('*.svg')}
        new_svgs = {f.name: f for f in cat_new.glob('*.svg')}
        for name in sorted(set(old_svgs) & set(new_svgs)):
            pairs[category].append((old_svgs[name], new_svgs[name], name))

    return pairs
