"""Color math utilities for diff tinting.

Provides CSS color parsing, complementary color calculation, and additive
tinting used by the triptych SVG generator.
"""

import colorsys
from PIL import ImageColor


def parse_css_color(color_str):
    """Parse any valid CSS color string and return RGB tuple (0-255).

    Supports hex, rgb(), rgba(), hsl(), hsla(), named colors, etc.
    """
    rgb = ImageColor.getrgb(color_str)
    return rgb[:3] if len(rgb) >= 3 else rgb


def _complementary_color(color_str):
    """Calculate the complementary color (hue + 180°) as a hex string."""
    r, g, b = (c / 255.0 for c in parse_css_color(color_str))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    r2, g2, b2 = colorsys.hls_to_rgb((h + 0.5) % 1.0, l, s)
    return f'#{int(r2 * 255):02x}{int(g2 * 255):02x}{int(b2 * 255):02x}'


# Tint colors for diff visualization (complementary pair).
TINT_COLOR_NEW = 'hsl(133, 85%, 45%)'  # Green for new/added content
TINT_COLOR_OLD = _complementary_color(TINT_COLOR_NEW)


def apply_color_tint(color_str, tint_type):
    """Apply an additive color tint to a hex color value.

    Args:
        color_str: Hex color from SVG; non-hex values are returned as-is.
        tint_type: 'old' for complementary tint, 'new' for primary tint

    Returns:
        Modified hex color string
    """
    if not color_str or color_str in ('none', 'transparent'):
        return color_str

    if not color_str.startswith('#'):
        return color_str

    hex_color = color_str.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join(c * 2 for c in hex_color)

    try:
        r = int(hex_color[0:2], 16) / 255.0
        g = int(hex_color[2:4], 16) / 255.0
        b = int(hex_color[4:6], 16) / 255.0
    except ValueError:
        raise ValueError(f"Invalid hex color format: {color_str}")

    tint = parse_css_color(TINT_COLOR_OLD if tint_type == 'old' else TINT_COLOR_NEW)
    tr, tg, tb = (c / 255.0 for c in tint)

    return '#{:02x}{:02x}{:02x}'.format(
        min(255, int((r + tr) * 255)),
        min(255, int((g + tg) * 255)),
        min(255, int((b + tb) * 255)),
    )
