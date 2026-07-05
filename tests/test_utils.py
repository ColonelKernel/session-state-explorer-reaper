"""Tests for the heuristic classifiers, grounded in real-session track names."""

from __future__ import annotations

from session_state_explorer.utils import classify_fx_family, classify_track_role


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
