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
    ("EQ", ["pro-q", "channel eq", "equalizer", "equaliser"]),
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
    ("Metering", ["meter", "analyzer", "analyser", "scope", "spectrograph"]),
    ("Utility", ["gain", "trim", "utility"]),
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

# Short/ambiguous keywords that must match a whole token, not a substring
# ("oh" for drum overheads would otherwise match inside "john"; "eq" would
# match inside "frequency"). Checked only after the substring pass finds
# nothing.
TRACK_ROLE_TOKEN_KEYWORDS: List[tuple[str, List[str]]] = [
    ("Drums", ["oh"]),
]

FX_FAMILY_TOKEN_KEYWORDS: List[tuple[str, List[str]]] = [
    ("EQ", ["eq"]),
]

_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")

# Families considered "ambience-like" and "dynamics-like" / "eq-like" for the
# recommendation engine and session fingerprint.
AMBIENCE_FAMILIES = {"Ambience"}
DYNAMICS_FAMILIES = {"Dynamics"}
EQ_FAMILIES = {"EQ"}

VOCAL_ROLE_KEYWORDS = ["vocal", "vox", "voice", "bgv", "lead vox"]


def classify_fx_family(name: Optional[str]) -> str:
    """Return a coarse FX family for a processor name (``"Unknown"`` if no match).

    Stock REAPER processors are identified authoritatively via the guide-derived
    knowledge table; everything else falls back to keyword heuristics.
    """

    if not name:
        return "Unknown"
    from .reaper_fx_knowledge import lookup_stock_fx

    stock = lookup_stock_fx(name)
    if stock is not None:
        return stock.family
    lowered = name.lower()
    for family, keywords in FX_FAMILY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return family
    tokens = set(_TOKEN_SPLIT_RE.split(lowered))
    for family, keywords in FX_FAMILY_TOKEN_KEYWORDS:
        if any(keyword in tokens for keyword in keywords):
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


def swell_platform(header: Optional[str]) -> Optional[bool]:
    """Classify the project-header platform token for colour byte order.

    Returns ``True`` for SWELL platforms (macOS/Linux, R in the high byte),
    ``False`` for Windows (R in the low byte), ``None`` when unknown.
    """

    if not header:
        return None
    lowered = header.lower()
    # SWELL tokens are checked first: "darwin" contains the substring "win",
    # so the Windows check must not run before it.
    if any(token in lowered for token in ("osx", "macos", "darwin", "linux")):
        return True
    # "x64" covers legacy Windows headers (e.g. "5.983/x64"); macOS builds of
    # that era wrote "OSX64", which the SWELL check above already caught.
    if "win" in lowered or "x64" in lowered:
        return False
    return None


# Send-channel bitfields (SDK ``GetSetTrackSendInfo``): the low 10 bits of a
# packed channel value are the first channel index; the bits above select the
# width. Applies to the AUXRECV source/destination channel tokens.
_SEND_CHANNEL_INDEX_MASK = 0x3FF
_SEND_DST_MONO_FLAG = 1024


def decode_send_src_channels(packed: Optional[int]) -> Optional[List[int]]:
    """Decode a packed send source-channel value into 0-based channel indices.

    SDK ``I_SRCCHAN`` semantics: ``-1`` means *no audio* (a MIDI-only send);
    otherwise the low 10 bits are the first source channel index and the value
    shifted right by 10 selects the width — ``0`` = stereo pair, ``1`` = mono,
    ``n >= 2`` = ``2*n`` channels. Returns ``None`` for missing values and for
    audio-disabled sends.
    """

    if packed is None or packed < 0:
        return None
    start = packed & _SEND_CHANNEL_INDEX_MASK
    mode = packed >> 10
    if mode == 0:
        count = 2
    elif mode == 1:
        count = 1
    else:
        count = 2 * mode
    return list(range(start, start + count))


def decode_send_dst_channels(
    packed: Optional[int], source_count: Optional[int] = None
) -> Optional[List[int]]:
    """Decode a packed send destination-channel value into 0-based indices.

    SDK ``I_DSTCHAN`` semantics: the low 10 bits are the first destination
    channel index; ``&1024`` marks a mono (downmixed) destination, otherwise
    the send lands on a stereo pair — or on ``source_count`` channels when the
    source picks up more than two. Returns ``None`` for missing values.
    """

    if packed is None or packed < 0:
        return None
    start = packed & _SEND_CHANNEL_INDEX_MASK
    if packed & _SEND_DST_MONO_FLAG:
        return [start]
    count = source_count if (source_count is not None and source_count > 2) else 2
    return list(range(start, start + count))


def decode_send_midi_flags(packed: Optional[int]) -> Optional[dict]:
    """Decode a send's packed MIDI flags into a small dict.

    SDK ``I_MIDIFLAGS`` semantics: the low 5 bits are the MIDI source channel
    (``0`` = all, ``1``-``16`` a single channel, ``31`` = MIDI disabled); the
    next 5 bits are the destination channel (``0`` = keep the source channel).
    Higher bits (MIDI bus selection, fader-controls-MIDI) are not decoded.
    Returns ``None`` for missing values, ``{"enabled": False}`` when the send
    carries no MIDI, else the source/target channel mapping.
    """

    if packed is None:
        return None
    if packed < 0 or (packed & 31) == 31:
        return {"enabled": False}
    source = packed & 31
    target = (packed >> 5) & 31
    return {
        "enabled": True,
        "source_channel": "all" if source == 0 else source,
        "target_channel": "source" if target == 0 else target,
    }


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
