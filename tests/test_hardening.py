"""Robustness / hardening regression tests.

These guard the fixes from the adversarial hardening pass: malformed or hostile ``.rpp``
tokens (non-finite floats, absurd send-channel widths, Unicode line separators) must
degrade gracefully — they must never crash a render, abort the parse and silently drop
later tracks, or make the JSON export emit the non-standard ``NaN``/``Infinity`` tokens
that strict consumers reject.
"""

from __future__ import annotations

import json

import pytest

from session_state_explorer import utils
from session_state_explorer.export import to_json_str
from session_state_explorer.graph_builder import build_graph
from session_state_explorer.mixer import format_db, format_pan
from session_state_explorer.recommendations import generate_recommendations
from session_state_explorer.rpp_parser import parse_rpp

NON_FINITE_TOKENS = ["nan", "inf", "-inf", "1e400", "1e999"]


def _strict_loads(text: str):
    """``json.loads`` that rejects the non-standard NaN/Infinity constants."""

    def _reject(token):  # pragma: no cover - only hit on regression
        raise ValueError(f"non-standard JSON token: {token}")

    return json.loads(text, parse_constant=_reject)


# --- Fix A: non-finite tokens never enter the model -------------------------

def test_safe_float_rejects_non_finite_tokens():
    for tok in NON_FINITE_TOKENS:
        assert utils.safe_float(tok) is None, tok


def test_safe_float_still_parses_normal_values():
    assert utils.safe_float("3.5") == 3.5
    assert utils.safe_float("-0.2") == -0.2
    assert utils.safe_float("bogus") is None
    assert utils.safe_float(None) is None


def test_safe_int_returns_none_instead_of_raising_on_non_finite():
    # Regression: int(float("inf")) raised OverflowError (uncaught) and
    # int(float("nan")) a ValueError inside the except block — both aborting the parse.
    for tok in NON_FINITE_TOKENS:
        assert utils.safe_int(tok) is None, tok


def test_safe_int_still_parses_normal_values():
    assert utils.safe_int("42") == 42
    assert utils.safe_int("42.9") == 42
    assert utils.safe_int("bogus") is None


def test_linear_to_db_rejects_non_finite():
    assert utils.linear_to_db(float("inf")) is None
    assert utils.linear_to_db(float("nan")) is None
    assert utils.linear_to_db(1.0) == 0.0


# --- Fix F: an absurd send-channel width is bounded, not expanded ------------

def test_decode_send_src_channels_caps_absurd_width():
    # 1073741824 == 2**30 -> width nibble decodes to ~1M channels without the cap.
    channels = utils.decode_send_src_channels(1073741824)
    assert channels is not None
    assert len(channels) <= 64
    # Sane values are unchanged.
    assert utils.decode_send_src_channels(0) == [0, 1]  # stereo pair
    assert utils.decode_send_src_channels(1024) == [0]  # mono


# --- Fix B/C: the JSON export is always valid ------------------------------

def test_to_json_str_coerces_non_finite_to_null():
    payload = {
        "a": float("nan"),
        "b": float("inf"),
        "c": float("-inf"),
        "ok": 1.5,
        "nested": [float("nan"), {"x": float("inf")}],
    }
    text = to_json_str(payload)
    assert "NaN" not in text and "Infinity" not in text
    parsed = _strict_loads(text)  # must not raise
    assert parsed["a"] is None and parsed["b"] is None and parsed["c"] is None
    assert parsed["ok"] == 1.5
    assert parsed["nested"][0] is None and parsed["nested"][1]["x"] is None


def test_canonical_dump_json_coerces_non_finite_to_null():
    pytest.importorskip("canonical_snapshot")
    from session_state_explorer.canonical_export.exporter import _dump_json

    raw = _dump_json({"tempo": float("nan"), "vol": float("inf"), "ok": 2})
    assert b"NaN" not in raw and b"Infinity" not in raw
    parsed = _strict_loads(raw.decode("utf-8"))
    assert parsed["tempo"] is None and parsed["vol"] is None and parsed["ok"] == 2


# --- Fix D: the mixer formatters never crash on non-finite input ------------

def test_format_pan_handles_non_finite():
    assert format_pan(float("nan")) == "—"
    assert format_pan(float("inf")) == "—"
    assert format_pan(None) == "—"
    assert format_pan(-0.5) == "L50"
    assert format_pan(0.0) == "C"


def test_format_db_handles_non_finite():
    assert format_db(float("nan")) == "—"
    assert format_db(None) == "-∞ dB"
    assert format_db(0.0) == "0.0 dB"


# --- Fix G: the parser splits on real newlines only -------------------------

def test_unicode_line_separator_in_name_is_preserved():
    # U+2028 is a str.splitlines() boundary; splitting on it truncates "Verse<sep>Chorus".
    name = "Verse Chorus"
    rpp = (
        '<REAPER_PROJECT 0.1 "x" 0\n'
        "  <TRACK\n"
        f'    NAME "{name}"\n'
        "    VOLPAN 1 0 -1 -1 1\n"
        "  >\n"
        ">\n"
    )
    project = parse_rpp(rpp, source_file="u.rpp")
    assert project.tracks[0].name == name


def test_crlf_line_endings_still_parse():
    rpp = (
        '<REAPER_PROJECT 0.1 "x" 0\r\n'
        "  <TRACK\r\n"
        '    NAME "Gtr"\r\n'
        "  >\r\n"
        ">\r\n"
    )
    project = parse_rpp(rpp, source_file="c.rpp")
    assert [t.name for t in project.tracks] == ["Gtr"]


# --- Fix A end-to-end: a non-finite token must not abort the parse ----------

def test_non_finite_token_does_not_abort_parse():
    # PEAKCOL runs through safe_int; before the fix int(float("1e400")) raised
    # OverflowError and every track after this one was silently lost.
    rpp = (
        '<REAPER_PROJECT 0.1 "x" 0\n'
        '  <TRACK\n    NAME "First"\n    PEAKCOL 1e400\n  >\n'
        '  <TRACK\n    NAME "Second"\n    VOLPAN 1 0 -1 -1 1\n  >\n'
        ">\n"
    )
    project = parse_rpp(rpp, source_file="p.rpp")
    assert [t.name for t in project.tracks] == ["First", "Second"]
    assert not any("stopped early" in w.lower() for w in project.warnings)


# --- Fix E: Rule 9 counts distinct sources, not duplicate sends -------------

def test_manual_submix_ignores_duplicate_sends_from_one_source():
    # One track feeding a bus via two sends must not masquerade as a multi-track submix.
    rpp = (
        '<REAPER_PROJECT 0.1 "x" 0\n'
        '  <TRACK\n    NAME "Kick"\n    MAINSEND 0 0\n  >\n'
        '  <TRACK\n    NAME "Drum Bus"\n'
        "    AUXRECV 0 0 1 0 0 0 0\n"
        "    AUXRECV 0 0 1 0 0 0 0\n  >\n"
        ">\n"
    )
    project = parse_rpp(rpp, source_file="s.rpp")
    recs = generate_recommendations(project, build_graph(project), [])
    assert "rec-manual-submix" not in {r.id for r in recs}
