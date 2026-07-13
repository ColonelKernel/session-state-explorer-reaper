"""The bundled example self-heals its git-ignored audio on a fresh checkout.

Guards the Streamlit Community Cloud path: a bare clone ships the committed ``.rpp``
and generator but no stems, and ``ensure_audio()`` must (re)generate them so the
example's descriptors and grounded recommendations populate on first load.
"""

from __future__ import annotations

import importlib.util
import os
import shutil

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE_DIR = os.path.join(REPO_ROOT, "data", "examples")


def _load_generator(gen_dir: str):
    """Load make_example_data.py by path, exactly as the app does on a fresh clone."""
    gen_path = os.path.join(gen_dir, "make_example_data.py")
    spec = importlib.util.spec_from_file_location("_sse_example_data_test", gen_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ensure_audio_regenerates_missing_stems(tmp_path):
    pytest.importorskip("soundfile")
    pytest.importorskip("numpy")
    # Simulate a fresh clone: committed .rpp + generator, but no audio/ directory.
    shutil.copy(os.path.join(EXAMPLE_DIR, "example_project.rpp"), tmp_path)
    shutil.copy(os.path.join(EXAMPLE_DIR, "make_example_data.py"), tmp_path)
    gen = _load_generator(str(tmp_path))

    assert not os.path.isdir(os.path.join(tmp_path, "audio"))
    written = gen.ensure_audio(str(tmp_path))
    wavs = [f for f in os.listdir(os.path.join(tmp_path, "audio")) if f.endswith(".wav")]
    assert len(wavs) == len(gen.STEMS)
    assert written and all(os.path.getsize(p) > 0 for p in written)


def test_ensure_audio_is_idempotent(tmp_path):
    pytest.importorskip("soundfile")
    shutil.copy(os.path.join(EXAMPLE_DIR, "make_example_data.py"), tmp_path)
    gen = _load_generator(str(tmp_path))

    first = gen.ensure_audio(str(tmp_path))
    mtimes = {p: os.path.getmtime(p) for p in first}
    # A second call must not raise, must return the same set, and must not rewrite.
    second = gen.ensure_audio(str(tmp_path))
    assert sorted(second) == sorted(first)
    assert all(os.path.getmtime(p) == mtimes[p] for p in second)
