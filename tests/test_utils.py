"""Tests for the heuristic classifiers and REAPER value conversions.

Classification cases are grounded in real-session track names. The colour,
platform, and knowledge-hook tests were merged back from the analyzer repo's
``tests/drivers/reaper/test_colors_and_classification.py``
(origin ``SessionStateExplorer@041f529``).
"""

from __future__ import annotations

from session_state_explorer.utils import (
    classify_fx_family,
    classify_track_role,
    decode_color,
    decode_send_dst_channels,
    decode_send_midi_flags,
    decode_send_src_channels,
    swell_platform,
)


def test_fx_metering_family():
    assert classify_fx_family("JS: analysis/loudness_meter") == "Metering"
    assert classify_fx_family("Frequency Analyzer") == "Metering"
    assert classify_fx_family("SPAN Spectrum Analyzer") == "Metering"


def test_fx_eq_keyword_matches_tokens_not_substrings():
    # "eq" inside "frequency" must not classify as EQ...
    assert classify_fx_family("Frequency Shifter Thing") != "EQ"
    # ...but a real bare "EQ" token still does, and stock names stay stable.
    assert classify_fx_family("SSL EQ") == "EQ"
    assert classify_fx_family("VST: ReaEQ (Cockos)") == "EQ"
    assert classify_fx_family("VST3: Pro-Q 3 (FabFilter)") == "EQ"


def test_real_session_names_classify():
    # Names observed in a real REAPER 7 multitrack session.
    assert classify_track_role("Nord L_Ride_5_Step") == "Keys"
    assert classify_track_role("OH L_Ride_5_Step") == "Drums"
    assert classify_track_role("OH R_Ride_5_Step") == "Drums"
    assert classify_track_role("Snare Top_Ride_5_Step") == "Drums"
    assert classify_track_role("Cristian Bass") == "Bass"


def test_short_tokens_do_not_match_inside_words():
    # "oh" must only match as a whole token, never inside a word.
    assert classify_track_role("John Vocal") == "Vocal"
    assert classify_track_role("Johnny Lead") == "Unknown"


def test_section_labels_do_not_leak_into_roles():
    # Take/section suffixes like "_Ride_5_Step" appear on EVERY track of a real
    # session; "ride" therefore must not be a drums keyword.
    assert classify_track_role("Spirals of Doubt_v6 Guitar_Ride_5_Step") == "Guitar"
    assert classify_track_role("Zach Bass_Ride_5_Step") == "Bass"


def test_precedence_is_preserved():
    # Earlier families win: a mellotron guitar patch reads as Guitar (Guitar is
    # checked before Keys), and a vocal bus reads as Bus.
    assert classify_track_role("Mellotron Guitar") == "Guitar"
    assert classify_track_role("Mellotron") == "Keys"
    assert classify_track_role("Vocal Bus") == "Bus"


def test_stock_fx_classified_via_knowledge_hook():
    # Bare stock names resolve through lookup_stock_fx, not keyword luck:
    # "ReaInsert" carries no routing keyword, only the knowledge table knows it.
    assert classify_fx_family("VST: ReaEQ (Cockos)") == "EQ"
    assert classify_fx_family("VST: ReaVerbate (Cockos)") == "Ambience"
    assert classify_fx_family("reacomp") == "Dynamics"
    assert classify_fx_family("VST: ReaInsert (Cockos)") == "Routing"
    assert classify_fx_family("JS: analysis/gfxspectrograph") == "Metering"


# ---------------------------------------------------------------------------
# Colour decoding (SDK I_CUSTOMCOLOR / ColorToNative semantics)
# ---------------------------------------------------------------------------

_IN_USE = 0x1000000


def test_color_without_in_use_flag_is_none():
    # A colour stored without |0x1000000 is stored but NOT used.
    assert decode_color(0x0040C0) is None
    assert decode_color(0) is None


def test_black_in_use_decodes_to_black():
    assert decode_color(_IN_USE) == "#000000"


def test_windows_layout_puts_red_in_the_low_byte():
    assert decode_color(0x0040C0 | _IN_USE) == "#c04000"
    assert decode_color(0x0000C0 | _IN_USE) == "#c00000"


def test_swell_layout_puts_red_in_the_high_byte():
    assert decode_color(0x0000C0 | _IN_USE, swell_order=True) == "#0000c0"
    assert decode_color(0xC00000 | _IN_USE, swell_order=True) == "#c00000"


def test_decode_color_tolerates_bad_input():
    assert decode_color(None) is None
    assert decode_color("not-an-int") is None


def test_swell_platform_classification():
    assert swell_platform("7.0/OSX64") is True
    assert swell_platform("7.0/darwin-arm64") is True  # "darwin" contains "win"
    assert swell_platform("7.0/linux-x86_64") is True
    assert swell_platform("7.0/win64") is False
    assert swell_platform("5.983/x64") is False  # legacy Windows header
    assert swell_platform("7.0/mystery") is None
    assert swell_platform(None) is None


# ---------------------------------------------------------------------------
# Send-channel bitfield decoding (SDK GetSetTrackSendInfo semantics)
# ---------------------------------------------------------------------------

def test_src_channel_stereo_and_offset():
    # Mode 0 (value >> 10 == 0): a stereo pair starting at the low-bits index.
    assert decode_send_src_channels(0) == [0, 1]
    assert decode_send_src_channels(2) == [2, 3]


def test_src_channel_mono():
    # &1024 (mode 1): a single mono channel.
    assert decode_send_src_channels(1024) == [0]
    assert decode_send_src_channels(1024 | 2) == [2]


def test_src_channel_multichannel():
    # Mode n >= 2: 2*n channels from the start index.
    assert decode_send_src_channels(2 << 10) == [0, 1, 2, 3]
    assert decode_send_src_channels((3 << 10) | 2) == [2, 3, 4, 5, 6, 7]


def test_src_channel_none_and_audio_disabled():
    assert decode_send_src_channels(None) is None
    assert decode_send_src_channels(-1) is None  # MIDI-only send


def test_dst_channel_stereo_mono_and_wide():
    assert decode_send_dst_channels(0) == [0, 1]
    assert decode_send_dst_channels(4) == [4, 5]
    assert decode_send_dst_channels(1024 | 5) == [5]  # mono (downmixed) dest
    # A >2-channel source lands on as many destination channels.
    assert decode_send_dst_channels(0, source_count=4) == [0, 1, 2, 3]
    # A mono source still feeds a stereo destination pair unless dst is mono.
    assert decode_send_dst_channels(0, source_count=1) == [0, 1]
    assert decode_send_dst_channels(None) is None


def test_midi_flags_decoding():
    assert decode_send_midi_flags(None) is None
    assert decode_send_midi_flags(31) == {"enabled": False}  # low 5 bits = 31: none
    assert decode_send_midi_flags(-1) == {"enabled": False}
    assert decode_send_midi_flags(0) == {
        "enabled": True,
        "source_channel": "all",
        "target_channel": "source",
    }
    assert decode_send_midi_flags(3 | (5 << 5)) == {
        "enabled": True,
        "source_channel": 3,
        "target_channel": 5,
    }
