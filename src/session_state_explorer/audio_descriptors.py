"""Audio descriptor extraction.

By default this uses ``librosa`` to compute a small, interpretable set of acoustic
descriptors per audio file. Everything here is *optional and graceful*: if librosa or
soundfile is unavailable, or a file cannot be read, the function returns an
:class:`AudioDescriptorSet` with ``available=False`` and a human-readable reason
instead of raising. The rest of the pipeline (parsing, graph, structural
recommendations) does not depend on audio being present.

The descriptors are intentionally modest. We do not claim mastering-grade loudness
analysis; integrated loudness (LUFS) is computed only when the optional
``pyloudnorm`` package is installed, and is otherwise left unset.
"""

from __future__ import annotations

import math
import os
from typing import List, Optional

from .models import AudioDescriptorSet

# --- optional backends, imported defensively --------------------------------
try:  # pragma: no cover - exercised implicitly by environment
    import librosa
    import numpy as np

    LIBROSA_AVAILABLE = True
    LIBROSA_IMPORT_ERROR: Optional[str] = None
except Exception as exc:  # pragma: no cover - environment dependent
    LIBROSA_AVAILABLE = False
    LIBROSA_IMPORT_ERROR = str(exc)

try:  # pragma: no cover - environment dependent
    import pyloudnorm as _pyln

    PYLOUDNORM_AVAILABLE = True
except Exception:  # pragma: no cover
    PYLOUDNORM_AVAILABLE = False

AUDIO_EXTENSIONS = {".wav", ".aif", ".aiff", ".flac", ".ogg", ".mp3", ".m4a"}


def resolve_audio_path(
    source_file: Optional[str],
    rpp_dir: Optional[str] = None,
    base_dir: Optional[str] = None,
) -> Optional[str]:
    """Resolve a media source path to a real, existing file if possible.

    Resolution order (first hit wins):

    1. an absolute path that exists on disk;
    2. relative to the directory of the ``.rpp`` file (when known);
    3. relative to a user-supplied base directory;
    4. base directory + just the file's basename (handles relocated stems).

    Returns ``None`` when nothing resolves, leaving the caller to record a warning.
    """

    if not source_file:
        return None

    candidate = source_file.replace("\\", "/")

    if os.path.isabs(candidate) and os.path.isfile(candidate):
        return candidate

    search_roots = [d for d in (rpp_dir, base_dir) if d]
    for root in search_roots:
        joined = os.path.join(root, candidate)
        if os.path.isfile(joined):
            return joined

    basename = os.path.basename(candidate)
    for root in search_roots:
        joined = os.path.join(root, basename)
        if os.path.isfile(joined):
            return joined

    if os.path.isfile(candidate):
        return candidate

    return None


def extract_descriptors(
    path: str, node_id: Optional[str] = None
) -> AudioDescriptorSet:
    """Compute descriptors for a single audio file.

    Always returns an :class:`AudioDescriptorSet`; never raises. When the audio
    backend is missing or the file is unreadable, ``available`` is ``False`` and
    ``unavailable_reason`` explains why.
    """

    result = AudioDescriptorSet(node_id=node_id, file_path=path)

    if not LIBROSA_AVAILABLE:
        result.unavailable_reason = (
            "librosa is not installed; install the 'audio' extra to enable "
            f"descriptor extraction. ({LIBROSA_IMPORT_ERROR})"
        )
        return result

    if not os.path.isfile(path):
        result.unavailable_reason = "Audio file path not found."
        return result

    try:
        signal, sr = librosa.load(path, sr=None, mono=True)
    except Exception as exc:
        result.unavailable_reason = f"Could not read audio file: {exc}"
        return result

    if signal is None or signal.size == 0:
        result.unavailable_reason = "Audio file is empty."
        return result

    try:
        result.available = True
        result.sample_rate = int(sr)
        result.duration = float(librosa.get_duration(y=signal, sr=sr))

        rms = librosa.feature.rms(y=signal)[0]
        result.rms_mean = _f(np.mean(rms))
        result.rms_std = _f(np.std(rms))

        centroid = librosa.feature.spectral_centroid(y=signal, sr=sr)[0]
        result.spectral_centroid_mean = _f(np.mean(centroid))

        bandwidth = librosa.feature.spectral_bandwidth(y=signal, sr=sr)[0]
        result.spectral_bandwidth_mean = _f(np.mean(bandwidth))

        rolloff = librosa.feature.spectral_rolloff(y=signal, sr=sr)[0]
        result.spectral_rolloff_mean = _f(np.mean(rolloff))

        zcr = librosa.feature.zero_crossing_rate(y=signal)[0]
        result.zero_crossing_rate_mean = _f(np.mean(zcr))

        onset_env = librosa.onset.onset_strength(y=signal, sr=sr)
        result.onset_strength_mean = _f(np.mean(onset_env))

        try:
            tempo = librosa.feature.rhythm.tempo(onset_envelope=onset_env, sr=sr)
            result.tempo_estimate = _f(np.atleast_1d(tempo)[0])
        except Exception:
            # Tempo estimation can be unstable on very short / tonal stems.
            result.tempo_estimate = None

        peak = float(np.max(np.abs(signal)))
        result.peak_amplitude = round(peak, 6)
        result.dynamic_range_db = _approx_dynamic_range_db(signal)

        if PYLOUDNORM_AVAILABLE:
            result.integrated_loudness_lufs = _integrated_loudness(signal, sr)
    except Exception as exc:  # pragma: no cover - defensive
        result.unavailable_reason = f"Descriptor computation failed: {exc}"
        # Keep whatever we managed to compute; mark partial via the reason field.

    return result


def extract_many(items: List[tuple]) -> List[AudioDescriptorSet]:
    """Convenience: extract for a list of ``(path, node_id)`` tuples."""

    return [extract_descriptors(path, node_id) for path, node_id in items]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _f(value) -> Optional[float]:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _approx_dynamic_range_db(signal) -> Optional[float]:
    """Rough crest-style dynamic range: peak vs. a low RMS percentile, in dB."""

    try:
        frame = 2048
        hop = 512
        rms = librosa.feature.rms(y=signal, frame_length=frame, hop_length=hop)[0]
        rms = rms[rms > 0]
        if rms.size == 0:
            return None
        loud = float(np.percentile(rms, 95))
        quiet = float(np.percentile(rms, 10))
        if quiet <= 0 or loud <= 0:
            return None
        return round(20.0 * np.log10(loud / quiet), 2)
    except Exception:  # pragma: no cover - defensive
        return None


def _integrated_loudness(signal, sr) -> Optional[float]:
    try:  # pragma: no cover - optional dependency
        meter = _pyln.Meter(sr)
        loudness = float(meter.integrated_loudness(signal))
        # Digital silence yields -inf per block and an empty gated set, so pyloudnorm
        # returns NaN (not -inf) via np.mean([]). Reject every non-finite result so a
        # silent stem leaves loudness unset instead of leaking NaN into the JSON export.
        if not math.isfinite(loudness):
            return None
        return round(loudness, 2)
    except Exception:
        return None
