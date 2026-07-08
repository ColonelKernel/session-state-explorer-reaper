"""Tests for the REAPER .rpp parser."""

from __future__ import annotations

from session_state_explorer.rpp_parser import parse_rpp

FAKE_RPP = """<REAPER_PROJECT 0.1 "7.0/win64" 1700000000
  TEMPO 124 4 4
  SAMPLERATE 48000 0 0
  <TRACK {GUID-0}
    NAME "Lead Vox"
    PEAKCOL 16793792
    VOLPAN 1 -0.2 -1 -1 1
    MUTESOLO 0 0 0
    <ITEM
      POSITION 0
      LENGTH 4.5
      NAME "vox_take1"
      <SOURCE WAVE
        FILE "audio/vox.wav"
      >
    >
    <FXCHAIN
      BYPASS 0 0 0
      <VST "VST3: Pro-Q 3 (FabFilter)" ProQ3.vst3 0 "" 1
        ZmFrZWNodW5r
      >
      PRESETNAME "Vocal Bright"
      WAK 0 0
    >
  >
  <TRACK {GUID-1}
    NAME "Reverb Bus"
    VOLPAN 1 0 -1 -1 1
    MUTESOLO 0 0 0
    AUXRECV 0 0 1 0 0 0 0
  >
>
"""


def test_tracks_are_parsed():
    project = parse_rpp(FAKE_RPP, source_file="test.rpp")
    assert len(project.tracks) == 2
    assert project.tracks[0].name == "Lead Vox"
    assert project.tracks[1].name == "Reverb Bus"
    assert project.tempo == 124.0
    assert project.sample_rate == 48000


def test_track_attributes_are_parsed():
    project = parse_rpp(FAKE_RPP, source_file="test.rpp")
    vox = project.tracks[0]
    assert vox.role == "Vocal"
    assert vox.pan == -0.2
    assert vox.volume_db == 0.0  # unity gain
    assert vox.color is not None and vox.color.startswith("#")
    assert vox.mute is False


def test_media_item_is_parsed():
    project = parse_rpp(FAKE_RPP, source_file="test.rpp")
    items = project.media_items
    assert len(items) == 1
    item = items[0]
    assert item.name == "vox_take1"
    assert item.position == 0.0
    assert item.length == 4.5
    assert item.source_file == "audio/vox.wav"
    assert item.source_type == "WAVE"


def test_fx_is_parsed_with_family_and_preset():
    project = parse_rpp(FAKE_RPP, source_file="test.rpp")
    fx = project.tracks[0].fx
    assert len(fx) == 1
    assert "Pro-Q" in fx[0].name
    assert fx[0].family == "EQ"
    assert fx[0].fx_type == "VST"
    assert fx[0].enabled is True
    assert fx[0].preset == "Vocal Bright"
    assert fx[0].raw_line  # traceability preserved


def test_bypassed_fx_marked_disabled():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Gtr"
    <FXCHAIN
      BYPASS 1 0 0
      <VST "VST: ReaDelay (Cockos)" readelay.dll 0 "" 0
      >
    >
  >
>
"""
    project = parse_rpp(rpp)
    fx = project.tracks[0].fx
    assert len(fx) == 1
    assert fx[0].enabled is False
    assert fx[0].family == "Ambience"


def test_send_is_parsed():
    project = parse_rpp(FAKE_RPP, source_file="test.rpp")
    assert len(project.routes) == 1
    route = project.routes[0]
    # AUXRECV 0 on track index 1 => track 0 sends into track 1.
    assert route.source_track_id == "track-0"
    assert route.target_track_id == "track-1"
    assert route.route_type == "send"
    # Per-send parameters from "AUXRECV 0 0 1 0 0 ...".
    assert route.send_mode == 0
    assert route.volume == 1.0
    assert route.volume_db == 0.0
    assert route.pan == 0.0
    assert route.mute is False


def test_unresolved_send_records_warning():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Bus"
    AUXRECV 99 0 1 0 0 0 0
  >
>
"""
    project = parse_rpp(rpp)
    assert len(project.routes) == 1
    route = project.routes[0]
    assert route.route_type == "unresolved"
    # The receiving track is real and remains the target; the unknown end is
    # the source, so edge direction still matches signal flow.
    assert route.target_track_id == "track-0"
    assert route.source_track_id is None
    assert route.source_name is not None and "99" in route.source_name
    assert any("AUXRECV" in w for w in project.warnings)


def test_parser_is_robust_to_garbage():
    # Malformed / truncated input must not raise.
    project = parse_rpp("<REAPER_PROJECT\n  <TRACK\n    NAME \"x\n  garbage line ]]\n")
    assert isinstance(project.warnings, list)
    # It should still have found the one track.
    assert len(project.tracks) == 1


def test_empty_input_warns_no_tracks():
    project = parse_rpp("")
    assert project.tracks == []
    assert any("No tracks" in w for w in project.warnings)


# ---------------------------------------------------------------------------
# SDK-grounded semantics (cross-checked against the REAPER extension SDK)
# ---------------------------------------------------------------------------

def _single_track(header: str, *track_lines: str) -> str:
    body = "\n".join(f"    {line}" for line in track_lines)
    return f'<REAPER_PROJECT 0.1 "{header}" 0\n  <TRACK\n{body}\n  >\n>\n'


def test_color_requires_in_use_flag():
    # SDK I_CUSTOMCOLOR: a colour without |0x1000000 is stored but NOT used.
    project = parse_rpp(_single_track("7.0/win64", 'NAME "A"', "PEAKCOL 16576"))
    assert project.tracks[0].color is None

    flagged = 16576 | 0x1000000
    project = parse_rpp(_single_track("7.0/win64", 'NAME "A"', f"PEAKCOL {flagged}"))
    assert project.tracks[0].color == "#c04000"  # 0x40C0: R low byte on Windows


def test_color_byte_order_follows_platform():
    flagged = 0x0000C0 | 0x1000000  # blue on Windows, red on SWELL platforms
    win = parse_rpp(_single_track("7.0/win64", 'NAME "A"', f"PEAKCOL {flagged}"))
    mac = parse_rpp(_single_track("7.0/OSX64", 'NAME "A"', f"PEAKCOL {flagged}"))
    assert win.tracks[0].color == "#c00000"
    assert mac.tracks[0].color == "#0000c0"


def test_color_unknown_platform_warns_once():
    rpp = (
        '<REAPER_PROJECT 0.1 "7.0/mystery" 0\n'
        "  <TRACK\n    PEAKCOL 16793792\n  >\n"
        "  <TRACK\n    PEAKCOL 16793792\n  >\n>\n"
    )
    project = parse_rpp(rpp)
    byte_order_warnings = [w for w in project.warnings if "byte order" in w]
    assert len(byte_order_warnings) == 1
    # Colour is still decoded (Windows layout assumed), just caveated.
    assert project.tracks[0].color is not None


def test_solo_mode_and_defeat_preserved():
    # SDK I_SOLO: 2 = soloed in place; still projects to solo=True.
    project = parse_rpp(_single_track("7.0/win64", 'NAME "A"', "MUTESOLO 1 2 1"))
    track = project.tracks[0]
    assert track.mute is True
    assert track.solo is True
    assert track.solo_mode == 2
    assert track.solo_defeat is True


def test_pan_law_width_and_pan_mode():
    project = parse_rpp(
        _single_track("7.0/win64", 'NAME "A"', "VOLPAN 0.5 -0.2 1 -1 0.75", "PANMODE 6")
    )
    track = project.tracks[0]
    assert track.volume_db == -6.02
    assert track.pan == -0.2
    assert track.pan_law == 1.0
    assert track.width == 0.75
    assert track.pan_mode == 6


def test_mainsend_flag_parsed():
    on = parse_rpp(_single_track("7.0/win64", 'NAME "A"', "MAINSEND 1 0"))
    off = parse_rpp(_single_track("7.0/win64", 'NAME "A"', "MAINSEND 0 0"))
    assert on.tracks[0].main_send is True
    assert off.tracks[0].main_send is False


def test_hwout_warns_but_creates_no_route():
    project = parse_rpp(_single_track("7.0/win64", 'NAME "Master-ish"', "HWOUT 0 0 1 0 0 0 0 -1"))
    assert project.routes == []
    assert any("HWOUT" in w for w in project.warnings)


def test_tempo_time_signature_and_samplerate_flag():
    rpp = '<REAPER_PROJECT 0.1 "7.0/win64" 0\n  TEMPO 93.5 6 8\n  SAMPLERATE 96000 1 0\n  <TRACK\n  >\n>\n'
    project = parse_rpp(rpp)
    assert project.tempo == 93.5
    assert project.time_sig_num == 6
    assert project.time_sig_denom == 8
    assert project.sample_rate == 96000
    assert project.sample_rate_use is True


def test_fx_offline_state_parsed():
    rpp = _single_track(
        "7.0/win64",
        'NAME "Gtr"',
        "<FXCHAIN",
        "  BYPASS 0 1 0",
        '  <VST "VST: ReaComp (Cockos)" reacomp.dll 0 "" 0',
        "  >",
        ">",
    )
    project = parse_rpp(rpp)
    fx = project.tracks[0].fx
    assert len(fx) == 1
    assert fx[0].enabled is True
    assert fx[0].offline is True


def test_record_fx_chain_tagged():
    rpp = _single_track(
        "7.0/win64",
        'NAME "Vox"',
        "<FXCHAIN_REC",
        "  BYPASS 0 0 0",
        '  <VST "VST: ReaGate (Cockos)" reagate.dll 0 "" 0',
        "  >",
        ">",
    )
    project = parse_rpp(rpp)
    fx = project.tracks[0].fx
    assert len(fx) == 1
    assert fx[0].chain == "rec"


def test_source_type_kept_verbatim():
    rpp = _single_track(
        "7.0/win64",
        'NAME "A"',
        "<ITEM",
        "  <SOURCE ReaLlm_custom",
        '    FILE "x.bin"',
        "  >",
        ">",
    )
    project = parse_rpp(rpp)
    assert project.media_items[0].source_type == "ReaLlm_custom"


def test_takefx_skip_is_warned():
    rpp = _single_track(
        "7.0/win64",
        'NAME "A"',
        "<ITEM",
        '  NAME "take1"',
        "  <TAKEFX",
        "    BYPASS 0 0 0",
        "  >",
        ">",
    )
    project = parse_rpp(rpp)
    assert any("take1" in w and "not modelled" in w for w in project.warnings)


def test_fx_container_children_keep_their_own_state():
    # REAPER v7 <CONTAINER>: real serialization is `<CONTAINER Container "<name>"`
    # (first argument is the literal word "Container", second is the user name).
    # The container consumes its own (bypassed) BYPASS state, children keep
    # theirs, and a flattening warning is emitted.
    rpp = _single_track(
        "7.0/win64",
        'NAME "Drums"',
        "<FXCHAIN",
        "  BYPASS 1 0 0",
        '  <CONTAINER Container "Parallel Crush"',
        "    BYPASS 0 0 0",
        '    <VST "VST: ReaComp (Cockos)" reacomp.dll 0 "" 0',
        "    >",
        "    BYPASS 1 0 0",
        '    <VST "VST: ReaXcomp (Cockos)" reaxcomp.dll 0 "" 0',
        "    >",
        '    PRESETNAME "Crushed"',
        "  >",
        '  <VST "VST: ReaEQ (Cockos)" reaeq.dll 0 "" 0',
        "  >",
        ">",
    )
    project = parse_rpp(rpp)
    fx = project.tracks[0].fx
    assert len(fx) == 4  # container + two children + sibling EQ
    assert fx[0].name == "Parallel Crush" and fx[0].enabled is False
    assert fx[1].enabled is True  # first child keeps its own state
    assert fx[2].enabled is False and fx[2].preset == "Crushed"
    assert fx[3].enabled is True  # sibling after the container unaffected
    assert any("container" in w.lower() for w in project.warnings)


def test_unnamed_fx_container_falls_back_to_container():
    # An unnamed container serialises as `<CONTAINER Container ""`.
    rpp = _single_track(
        "7.0/win64",
        'NAME "Drums"',
        "<FXCHAIN",
        '  <CONTAINER Container ""',
        '    <VST "VST: ReaComp (Cockos)" reacomp.dll 0 "" 0',
        "    >",
        "  >",
        ">",
    )
    project = parse_rpp(rpp)
    assert project.tracks[0].fx[0].name == "Container"


def test_darwin_platform_classified_as_swell():
    # "darwin" contains the substring "win"; it must still classify as SWELL
    # (R in the high byte), not Windows.
    flagged = 0xC00000 | 0x1000000  # red on SWELL platforms
    project = parse_rpp(_single_track("7.0/darwin-arm64", 'NAME "A"', f"PEAKCOL {flagged}"))
    assert project.tracks[0].color == "#c00000"
    assert not any("byte order" in w for w in project.warnings)


def test_legacy_x64_header_is_windows_without_warning():
    flagged = 0x0000C0 | 0x1000000  # red in the Windows layout
    project = parse_rpp(_single_track("5.983/x64", 'NAME "A"', f"PEAKCOL {flagged}"))
    assert project.tracks[0].color == "#c00000"
    assert not any("byte order" in w for w in project.warnings)


def test_auxrecv_channel_fields_parsed_verbatim():
    # AUXRECV <src> <mode> <vol> <pan> <mute> <monosum> <phase> <srcchan>
    # <dstchan> <panlaw> <midiflags> ... — the packed channel bitfields are
    # kept verbatim (decoding is downstream, utils.decode_send_*).
    rpp = (
        '<REAPER_PROJECT 0.1 "7.0/win64" 0\n'
        "  <TRACK\n    NAME \"Src\"\n  >\n"
        "  <TRACK\n    NAME \"Dst\"\n"
        "    AUXRECV 0 0 1 0 0 0 0 2 4 -1:U 31 -1 ''\n"
        "  >\n>\n"
    )
    project = parse_rpp(rpp)
    route = project.routes[0]
    assert route.src_channel == 2
    assert route.dst_channel == 4
    assert route.midi_flags == 31


def test_auxrecv_without_channel_fields_leaves_them_none():
    # Short AUXRECV lines (no channel tokens) stay honest: nothing invented.
    project = parse_rpp(FAKE_RPP, source_file="test.rpp")
    route = project.routes[0]
    assert route.src_channel is None
    assert route.dst_channel is None
    assert route.midi_flags is None


def test_folder_hierarchy_resolved_from_isbus():
    # Folder layout: A(+1) contains [B, C(+1) contains [D(-2 closes both)]],
    # then E is back at the top level.
    rpp = (
        '<REAPER_PROJECT 0.1 "7.0/win64" 0\n'
        "  <TRACK\n    NAME \"A\"\n    ISBUS 1 1\n  >\n"
        "  <TRACK\n    NAME \"B\"\n    ISBUS 0 0\n  >\n"
        "  <TRACK\n    NAME \"C\"\n    ISBUS 1 1\n  >\n"
        "  <TRACK\n    NAME \"D\"\n    ISBUS 2 -2\n  >\n"
        "  <TRACK\n    NAME \"E\"\n  >\n>\n"
    )
    project = parse_rpp(rpp)
    a, b, c, d, e = project.tracks
    assert (a.folder_state, a.folder_depth) == (1, 1)
    assert a.parent_track_id is None
    assert b.parent_track_id == a.id
    assert c.parent_track_id == a.id  # nested folder parent is itself a child
    assert d.parent_track_id == c.id
    assert (d.folder_state, d.folder_depth) == (2, -2)
    assert e.parent_track_id is None  # -2 closed both levels
    assert e.folder_state is None  # no ISBUS line at all: nothing invented


def test_folder_depth_underflow_warns_but_does_not_raise():
    rpp = (
        '<REAPER_PROJECT 0.1 "7.0/win64" 0\n'
        "  <TRACK\n    NAME \"A\"\n    ISBUS 2 -1\n  >\n"
        "  <TRACK\n    NAME \"B\"\n  >\n>\n"
    )
    project = parse_rpp(rpp)
    assert project.tracks[1].parent_track_id is None
    assert any("underflow" in w for w in project.warnings)


def test_unclosed_folder_ends_with_the_project():
    # A folder parent as the last track: REAPER tolerates it; so do we.
    rpp = (
        '<REAPER_PROJECT 0.1 "7.0/win64" 0\n'
        "  <TRACK\n    NAME \"A\"\n    ISBUS 1 1\n  >\n"
        "  <TRACK\n    NAME \"B\"\n  >\n>\n"
    )
    project = parse_rpp(rpp)
    assert project.tracks[1].parent_track_id == project.tracks[0].id
    assert not any("underflow" in w for w in project.warnings)


def test_spaced_project_header_does_not_abort_parse():
    # Crafted input: whitespace between '<' and the tag, no header arguments.
    # Must not raise mid-parse (the never-raise guarantee) and must still
    # parse the rest of the file.
    rpp = '< REAPER_PROJECT\n  <TRACK\n    NAME "Still here"\n  >\n>\n'
    project = parse_rpp(rpp)
    assert not any("stopped early" in w for w in project.warnings)
    assert len(project.tracks) == 1
    assert project.tracks[0].name == "Still here"
