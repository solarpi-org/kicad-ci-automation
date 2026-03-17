"""Color math utilities for diff tinting.

Provides HSL/RGB conversion, CSS color parsing, complementary color
calculation, and additive tinting used by the triptych SVG generator.
"""

from PIL import ImageColor


def parse_css_color(color_str):
    """Parse any valid CSS color string and return RGB tuple (0-255).

    Supports hex, rgb(), rgba(), hsl(), hsla(), named colors, etc.
    """
    rgb = ImageColor.getrgb(color_str)
    return rgb[:3] if len(rgb) >= 3 else rgb


def hsl_to_rgb(h, s, l):
    """Convert HSL to RGB.

    Args:
        h: Hue in degrees (0-360)
        s: Saturation (0-1)
        l: Lightness (0-1)

    Returns:
        Tuple of (r, g, b) values in 0-255 range
    """
    h = h / 360.0

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
    """Convert RGB to HSL.

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
        h = s = 0
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
    """Calculate the complementary color in HSL space (hue + 180°).

    Args:
        color_str: CSS color string (hex, rgb, hsl, or named)

    Returns:
        Complementary color as hex string
    """
    r, g, b = parse_css_color(color_str)
    h, s, l = rgb_to_hsl(r, g, b)
    h_comp = (h + 180) % 360
    r_comp, g_comp, b_comp = hsl_to_rgb(h_comp, s, l)
    return f'#{r_comp:02x}{g_comp:02x}{b_comp:02x}'


# Tint colors for diff visualization (complementary pair).
# TINT_COLOR_NEW accepts any valid CSS color format (requires Pillow for
# anything beyond hex).
TINT_COLOR_NEW = 'hsl(133, 85%, 45%)'  # Green for new/added content
TINT_COLOR_OLD = calculate_complementary_color(TINT_COLOR_NEW)


def apply_color_tint(color_str, tint_type):
    """Apply an additive color tint to a hex color value.

    Args:
        color_str: Color string (hex only in SVG context; non-hex is returned as-is)
        tint_type: 'old' for complementary tint, 'new' for primary tint

    Returns:
        Modified hex color string, or original if not hex
    """
    if not color_str or color_str in ('none', 'transparent'):
        return color_str

    if not color_str.startswith('#'):
        return color_str

    hex_color = color_str.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join([c*2 for c in hex_color])

    try:
        r = int(hex_color[0:2], 16) / 255.0
        g = int(hex_color[2:4], 16) / 255.0
        b = int(hex_color[4:6], 16) / 255.0
    except ValueError:
        raise ValueError(f"Invalid hex color format: {color_str}")

    tint_color_str = TINT_COLOR_OLD if tint_type == 'old' else TINT_COLOR_NEW
    tint_r, tint_g, tint_b = (c / 255.0 for c in parse_css_color(tint_color_str))

    r_new = min(1.0, r + tint_r)
    g_new = min(1.0, g + tint_g)
    b_new = min(1.0, b + tint_b)

    return f'#{int(r_new * 255):02x}{int(g_new * 255):02x}{int(b_new * 255):02x}'
