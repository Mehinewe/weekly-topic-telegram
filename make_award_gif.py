"""
Animated award badge ("flip card")
==================================

Builds a short looping GIF that flips between the award badge and the winner's
own photo inside a circular frame — like the original KODJO English award:

    [ badge graphic ]  --flip-->  [ winner's photo in the ring ]  --flip-->  ...

`build_flip_gif()` takes the static badge image (the "front") and the winner's
profile photo (a PIL image), and writes the animated GIF. If no photo is
available the caller should just send the static badge instead.

Only depends on Pillow.
"""

import math

from PIL import Image, ImageDraw, ImageOps

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # very old Pillow
    RESAMPLE = Image.LANCZOS

# Output width (height follows the badge's aspect ratio). Kept modest so the
# GIF stays a reasonable size for Telegram.
OUTPUT_WIDTH = 480

# Geometry of the circular photo window, as fractions of the badge size. Tuned
# to sit roughly where the badge art's own circle is (upper-middle).
CIRCLE_DIAMETER_FRAC = 0.72
CIRCLE_CENTER_Y_FRAC = 0.42
RING_FRAC = 0.022

FLIP_STEPS = 8        # intermediate frames per half-flip
HOLD_MS = 1300        # how long each face is shown
FLIP_MS = 35          # per intermediate flip frame


def _circular(img, size):
    """Return an RGBA copy of `img` cropped to a centred circle of `size`px."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, (size, size), method=RESAMPLE, centering=(0.5, 0.5))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGBA", (size, size))
    out.paste(img, (0, 0))
    out.putalpha(mask)
    return out


def _photo_card(front, photo):
    """Build the "back" face: the winner's photo in a white ring on a
    background colour sampled from the badge, matching the badge's size."""
    w, h = front.size
    bg = front.convert("RGB").getpixel((max(1, w // 40), max(1, h // 40)))
    card = Image.new("RGB", (w, h), bg)

    diameter = int(w * CIRCLE_DIAMETER_FRAC)
    ring = max(2, int(w * RING_FRAC))
    cx, cy = w // 2, int(h * CIRCLE_CENTER_Y_FRAC)

    draw = ImageDraw.Draw(card)
    r = diameter // 2 + ring
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill="white")  # ring

    disc = _circular(photo, diameter)
    card.paste(disc, (cx - diameter // 2, cy - diameter // 2), disc)
    return card


def _flip(face_a, face_b, bg):
    """Frames morphing face_a -> face_b by squashing width (a 3D-flip illusion)."""
    w, h = face_a.size
    frames = []

    def squashed(face, scale):
        fw = max(2, int(w * scale))
        canvas = Image.new("RGB", (w, h), bg)
        canvas.paste(face.resize((fw, h), RESAMPLE), ((w - fw) // 2, 0))
        return canvas

    # face_a closing: width 1 -> 0
    for i in range(1, FLIP_STEPS + 1):
        frames.append(squashed(face_a, math.cos((math.pi / 2) * (i / FLIP_STEPS))))
    # face_b opening: width 0 -> 1
    for i in range(1, FLIP_STEPS + 1):
        frames.append(squashed(face_b, math.sin((math.pi / 2) * (i / FLIP_STEPS))))
    return frames


def build_flip_gif(front_path, photo, out_path):
    """Write an animated flip GIF to `out_path`.

    front_path : path to the static badge image (the front face)
    photo      : a PIL.Image of the winner's profile photo (the back face)
    """
    front = Image.open(front_path).convert("RGB")
    w, h = front.size
    scale = OUTPUT_WIDTH / w
    front = front.resize((OUTPUT_WIDTH, int(h * scale)), RESAMPLE)

    bg = front.getpixel((max(1, front.width // 40), max(1, front.height // 40)))
    back = _photo_card(front, photo)

    frames = [front]
    durations = [HOLD_MS]
    for f in _flip(front, back, bg):
        frames.append(f)
        durations.append(FLIP_MS)
    frames.append(back)
    durations.append(HOLD_MS)
    for f in _flip(back, front, bg):
        frames.append(f)
        durations.append(FLIP_MS)

    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    return out_path
