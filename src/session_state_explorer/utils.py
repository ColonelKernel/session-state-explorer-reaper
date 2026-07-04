"""Small, dependency-free helpers shared across the prototype.

This module deliberately avoids heavy imports so it can be used from tests and from
the parser without pulling in audio or visualization libraries. It provides:

* keyword-based FX-family and track-role classification (heuristic metadata only);
* conversions for REAPER's stored values (linear gain <-> dB, packed colour ints);
* a couple of defensive parsing helpers.

All classification here is *heuristic*. It is intended to support reflection and
graph-level reasoning, not to make authoritative claims about a producer's intent.
"""

from __future__ import annotations

import math
import re
from typing import List, Optional

# ---------------------------------------------------------------------------
# Keyword taxonomies
# ---------------------------------------------------------------------------
# Order matters: families/roles are checked top-to-bottom and the first match wins.
# Keywords are matched case-insensitively as substrings of the name.

FX_FAMILY_KEYWORDS: List[tuple[str, List[str]]] = [
    ("EQ", ["pro-q", "channel eq", "equalizer", "equaliser", "eq"]),
    (
        "Dynamics",
        [
            "de-esser",
            "deesser",
            "compressor",
            "comp",
            "limiter",
            "gate",
            "expander",
            "dynamics",
        ],
    ),
    (
        "Ambience",
        ["reverb", "delay", "echo", "room", "hall", "plate", "space", "verb"],
    ),
    (
        "Saturation",
        ["saturat", "distortion", "overdrive", "tape", "tube", "drive", "crunch"],
    ),
    ("Modulation", ["chorus", "flanger", "phaser", "tremolo", "ensemble"]),
    ("Pitch", ["pitch", "autotune", "auto-tune", "melodyne", "harmonizer", "harmoniser"]),
    ("Utility", ["gain", "trim", "meter", "analyzer", "analyser", "utility"]),
]

TRACK_ROLE_KEYWORDS: List[tuple[str, List[str]]] = [
    # Buses first: a "vocal bus" should read as a Bus, not a Vocal track.
    ("Bus", ["bus", "group", "aux", "return", "submix", "verb", "delay"]),
    ("Vocal", ["lead vox", "bgv", "vocal", "vox", "voice"]),
    (
        "Drums",
        ["drum", "kick", "snare", "hat", "tom", "perc", "percussion", "cymbal", "overhead"],
    ),
    ("Bass", ["bass", "sub", "808"]),
    ("Guitar", ["guitar", "gtr"]),
    ("Keys", ["keys", "piano", "rhodes", "organ", "synth", "pad", "nord", "mellotron"]),
    ("FX", ["riser", "impact", "noise", "sweep", "whoosh", "fx"]),
]

# Short/ambiguous role keywords that must match a whole token, not a substring
# ("oh" for drum overheads would otherwise match inside "john"). Checked only
# after the substring pass above finds nothing.
TRACK_ROLE_TOKEN_KEYWORDS: List[tuple[str, List[str]]] = [
    ("Drums", ["oh"]),
]

_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")

# Families considered "ambience-like" and "dynamics-like" / "eq-like" for the
# recommendation engine and session fingerprint.
AMBIENCE_FAMILIES = {"Ambience"}
DYNAMICS_FAMILIES = {"Dynamics"}
EQ_FAMILIES = {"EQ"}

VOCAL_ROLE_KEYWORDS = ["vocal", "vox", "voice", "bgv", "lead vox"]


def classify_fx_family(name: Optional[str]) -> str:
    """Return a coarse FX family for a processor name (``"Unknown"`` if no match)."""

    if not name:
        return "Unknown"
    lowered = name.lower()
    for family, keywords in FX_FAMILY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return family
    return "Unknown"


def classify_track_role(name: Optional[str]) -> str:
    """Return a coarse production role for a track name (``"Unknown"`` if no match)."""

    if not name:
        return "Unknown"
    lowered = name.lower()
    for role, keywords in TRACK_ROLE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return role
    tokens = set(_TOKEN_SPLIT_RE.split(lowered))
    for role, keywords in TRACK_ROLE_TOKEN_KEYWORDS:
        if any(keyword in tokens for keyword in keywords):
            return role
    return "Unknown"


def is_ambience_fx(name: Optional[str]) -> bool:
    """True when a processor name reads as ambience (reverb/delay/echo/...)."""

    return classify_fx_family(name) in AMBIENCE_FAMILIES


def is_vocal_name(name: Optional[str]) -> bool:
    """True when a track name reads as a vocal role."""

    if not name:
        return False
    lowered = name.lower()
    return any(keyword in lowered for keyword in VOCAL_ROLE_KEYWORDS)


# ---------------------------------------------------------------------------
# REAPER value conversions
# ---------------------------------------------------------------------------

def linear_to_db(value: Optional[float]) -> Optional[float]:
    """Convert a linear gain (REAPER's VOLPAN volume) to dB.

    Returns ``None`` for non-positive or missing values (``-inf`` is not useful in a
    table). Unity gain (1.0) maps to 0 dB.
    """

    if value is None or value <= 0:
        return None
    return round(20.0 * math.log10(value), 2)


def decode_color(packed: Optional[int], swell_order: bool = False) -> Optional[str]:
    """Decode a REAPER packed colour integer into ``#rrggbb``.

    REAPER stores custom colours as an OS-native integer OR-ed with the
    0x1000000 "custom colour in use" flag (SDK ``I_CUSTOMCOLOR``: "If you do not
    |0x1000000, then it will not be used, but will store the color"). A value
    without that flag therefore means *no custom colour*, and we return ``None``
    — this also makes black-in-use (exactly 0x1000000) decode to ``#000000``.

    The byte order of the low three bytes depends on the OS the project was
    authored on (SDK ``ColorToNative``: "OS dependent color ... e.g. RGB() macro
    on Windows"): Windows COLORREF puts R in the low byte, while SWELL
    (macOS/Linux) puts R in bits 16-23. Pass ``swell_order=True`` for
    non-Windows-authored projects; the default assumes the Windows layout.
    """

    if packed is None:
        return None
    try:
        value = int(packed)
    except (TypeError, ValueError):
        return None
    if not (value & 0x1000000):
        return None  # colour stored but not in use (SDK: I_CUSTOMCOLOR)
    value &= 0xFFFFFF  # drop the custom-colour flag bit
    if swell_order:
        red = (value >> 16) & 0xFF
        green = (value >> 8) & 0xFF
        blue = value & 0xFF
    else:
        red = value & 0xFF
        green = (value >> 8) & 0xFF
        blue = (value >> 16) & 0xFF
    return f"#{red:02x}{green:02x}{blue:02x}"


# ---------------------------------------------------------------------------
# Defensive parsing helpers
# ---------------------------------------------------------------------------

def safe_float(token: Optional[str]) -> Optional[float]:
    """Parse a float, returning ``None`` instead of raising on bad input."""

    if token is None:
        return None
    try:
        return float(token)
    except (TypeError, ValueError):
        return None


def safe_int(token: Optional[str]) -> Optional[int]:
    """Parse an int (tolerating float-formatted text), returning ``None`` on failure."""

    if token is None:
        return None
    try:
        return int(token)
    except (TypeError, ValueError):
        parsed = safe_float(token)
        return int(parsed) if parsed is not None else None


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: Optional[str], fallback: str = "item") -> str:
    """Lowercase, hyphenated slug suitable for ids and filenames."""

    if not text:
        return fallback
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return slug or fallback
