#!/usr/bin/env python3
"""Generate self-contained example data for Session State Explorer.

This script writes two things into ``data/examples/``:

1. ``example_project.rpp`` — a small, well-formed REAPER project that deliberately
   exercises the parser and several recommendation rules (an under-processed vocal
   track, a deliberately dense FX chain, individual ambience FX without a shared
   return, a real drum-group bus with sends, and one intentionally unresolved
   send to demonstrate partial observability).
2. ``audio/*.wav`` — a handful of very short, synthetic mono stems whose levels
   differ on purpose so the descriptor-based level-imbalance rule can fire. These
   are generated from code (sine tones / filtered noise), contain no copyrighted
   material, and are git-ignored.

Run it with::

    python data/examples/make_example_data.py

The ``.rpp`` is committed to the repository so the graph demo works even before the
audio is generated; re-running this script regenerates both.
"""

from __future__ import annotations

import os
from typing import List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIRNAME = "audio"
SR = 44100


# ---------------------------------------------------------------------------
# Project description (single source of truth for both the .rpp and the audio)
# ---------------------------------------------------------------------------
# Each track: (name, color_int, audio_file_or_None, [fx_display_names])
TRACKS: List[Tuple[str, int, str, List[str]]] = [
    # Under-processed vocal: a single EQ -> triggers the vocal-chain rule.
    ("Lead Vox", 0x0040C0, "lead_vox.wav", ["VST: ReaEQ (Cockos)"]),
    # Backing vox with its own private reverb -> contributes to the ambience rule.
    ("BGV", 0x0060C0, "bgv.wav", ["VST: ReaEQ (Cockos)", "VST: ReaVerbate (Cockos)"]),
    ("Kick", 0xC08000, "kick.wav", ["VST: ReaEQ (Cockos)", "VST: ReaComp (Cockos)"]),
    # Snare with its own plate reverb -> ambience rule.
    ("Snare", 0xC0A000, "snare.wav",
     ["VST: ReaEQ (Cockos)", "VST: ReaComp (Cockos)", "Plate Reverb"]),
    ("Bass", 0x800040, "bass.wav", ["VST: ReaEQ (Cockos)", "VST: ReaComp (Cockos)"]),
    # Guitar with its own slap delay -> ambience rule.
    ("Guitar", 0x008060, "guitar.wav",
     ["VST: ReaEQ (Cockos)", "VST: ReaDelay (Cockos)"]),
    # Deliberately dense chain (7 processors) -> dense-FX rule.
    ("Synth Pad", 0x4040C0, None,
     ["VST: ReaEQ (Cockos)", "VST: ReaComp (Cockos)", "VST: ReaVerbate (Cockos)",
      "VST: ReaDelay (Cockos)", "Tape Saturation", "VST: ReaXcomp (Cockos)",
      "Stereo Width Utility"]),
    # Percussion with a room reverb of its own -> ambience rule.
    ("Perc", 0xC06000, "perc.wav", ["VST: ReaEQ (Cockos)", "Room Reverb"]),
    # A real group bus that receives the drum tracks (resolved sends) + one
    # intentionally unresolved receive (source index out of range).
    ("Drum Bus", 0x606060, None, ["VST: ReaComp (Cockos)"]),
]

# Sends to place on the Drum Bus track as AUXRECV lines: (source_track_index).
# Kick=2, Snare=3, Perc=7 feed the Drum Bus. 99 is an intentionally invalid index
# to demonstrate an unresolved / partially observable route.
DRUM_BUS_INDEX = 8
DRUM_BUS_RECEIVES = [2, 3, 7, 99]

# Per-stem synthesis recipe: (filename, kind, freq_hz, gain). One stem (bass) is
# intentionally much louder so the level-imbalance descriptor rule fires.
STEMS = [
    ("lead_vox.wav", "tone", 220.0, 0.25),
    ("bgv.wav", "tone", 330.0, 0.20),
    ("kick.wav", "noise_low", 0.0, 0.35),
    ("snare.wav", "noise", 0.0, 0.30),
    ("bass.wav", "tone", 55.0, 0.90),   # deliberately hot
    ("guitar.wav", "tone", 440.0, 0.22),
    ("perc.wav", "noise", 0.0, 0.18),
]


# ---------------------------------------------------------------------------
# .rpp generation (no third-party dependencies needed)
# ---------------------------------------------------------------------------

def build_rpp_text() -> str:
    lines: List[str] = []
    # The platform token ("win64") pins the OS-dependent colour byte order so the
    # parser can decode PEAKCOL deterministically and without a caveat warning.
    lines.append('<REAPER_PROJECT 0.1 "7.0/win64" 1700000000')
    lines.append("  TEMPO 120 4 4")
    lines.append("  SAMPLERATE 44100 0 0")

    for index, (name, color, audio_file, fx_names) in enumerate(TRACKS):
        lines.append(f"  <TRACK {{GUID-{index:02d}}}")
        lines.append(f'    NAME "{name}"')
        # REAPER only treats a colour as "in use" when OR-ed with 0x1000000
        # (SDK I_CUSTOMCOLOR); an unflagged value is stored but ignored.
        lines.append(f"    PEAKCOL {color | 0x1000000}")
        lines.append("    VOLPAN 1 0 -1 -1 1")
        lines.append("    MUTESOLO 0 0 0")

        if audio_file is not None:
            lines.append("    <ITEM")
            lines.append("      POSITION 0")
            lines.append("      LENGTH 2.0")
            lines.append(f'      NAME "{name} take"')
            lines.append("      <SOURCE WAVE")
            lines.append(f'        FILE "{AUDIO_DIRNAME}/{audio_file}"')
            lines.append("      >")
            lines.append("    >")

        if fx_names:
            lines.append("    <FXCHAIN")
            for fx_name in fx_names:
                lines.append("      BYPASS 0 0 0")
                lines.append(f'      <VST "{fx_name}" plugin.dll 0 "" 0')
                lines.append("        ZmFrZWNodW5r")
                lines.append("      >")
                lines.append("      WAK 0 0")
            lines.append("    >")

        # Drum-bus receives (sends from other tracks into this bus).
        if index == DRUM_BUS_INDEX:
            for src in DRUM_BUS_RECEIVES:
                lines.append(f"    AUXRECV {src} 0 1 0 0 0 0 0 0")

        lines.append("  >")

    lines.append(">")
    return "\n".join(lines) + "\n"


def write_rpp(target_dir: str = HERE) -> str:
    path = os.path.join(target_dir, "example_project.rpp")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(build_rpp_text())
    return path


# ---------------------------------------------------------------------------
# Audio generation (requires numpy + soundfile; imported lazily)
# ---------------------------------------------------------------------------

def write_audio(target_dir: str = HERE, duration: float = 2.0) -> List[str]:
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "Audio generation needs numpy and soundfile. Install them with:\n"
            "    pip install numpy soundfile\n"
            f"(import error: {exc})"
        )

    audio_dir = os.path.join(target_dir, AUDIO_DIRNAME)
    os.makedirs(audio_dir, exist_ok=True)
    n = int(SR * duration)
    t = np.linspace(0.0, duration, n, endpoint=False)
    rng = np.random.default_rng(7)  # fixed seed -> reproducible stems
    written: List[str] = []

    for filename, kind, freq, gain in STEMS:
        if kind == "tone":
            signal = np.sin(2 * np.pi * freq * t)
            # Gentle exponential decay so it reads as a musical note, not a drone.
            signal *= np.exp(-2.0 * t)
        elif kind == "noise_low":
            raw = rng.standard_normal(n)
            # Cheap one-pole low-pass for a "kick"-ish thump.
            signal = np.zeros(n)
            alpha = 0.02
            for i in range(1, n):
                signal[i] = alpha * raw[i] + (1 - alpha) * signal[i - 1]
            signal *= np.exp(-12.0 * t)
        else:  # "noise"
            signal = rng.standard_normal(n) * np.exp(-8.0 * t)

        peak = float(np.max(np.abs(signal))) or 1.0
        signal = (signal / peak) * gain
        path = os.path.join(audio_dir, filename)
        sf.write(path, signal.astype("float32"), SR)
        written.append(path)

    return written


def main() -> None:
    rpp_path = write_rpp()
    print(f"Wrote project: {rpp_path}")
    audio_paths = write_audio()
    print(f"Wrote {len(audio_paths)} audio stems into {os.path.join(HERE, AUDIO_DIRNAME)}/")
    for path in audio_paths:
        print(f"  - {os.path.basename(path)}")


if __name__ == "__main__":
    main()
