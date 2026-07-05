"""Tests for the channel-strip console view-model (pure builders)."""

from __future__ import annotations

from session_state_explorer.mixer import (
    build_console,
    display_fx_name,
    format_db,
    format_pan,
    fx_family_color,
    render_console_html,
)
from session_state_explorer.rpp_parser import parse_rpp


def test_format_db():
    assert format_db(None) == "-∞ dB"
    assert format_db(0.0) == "0.0 dB"
    assert format_db(0.02) == "0.0 dB"  # within unity tolerance
    assert format_db(-6.0) == "-6.0 dB"
    assert format_db(3.5) == "+3.5 dB"


def test_format_pan():
    assert format_pan(None) == "—"
    assert format_pan(0.0) == "C"
    assert format_pan(-0.2) == "L20"
    assert format_pan(0.35) == "R35"
    assert format_pan(-1.0) == "L100"


def test_display_fx_name_cleans_stock_and_third_party():
    assert display_fx_name("VST: ReaComp (Cockos)") == "ReaComp"
    assert display_fx_name("VST3: ReaEQ (Cockos)") == "ReaEQ"
    # Third-party: strip prefix + vendor, keep the product name.
    assert display_fx_name("VST3: Pro-Q 3 (FabFilter)") == "Pro-Q 3"
    assert display_fx_name("Tape Saturation") == "Tape Saturation"


def test_family_colors_are_distinct_and_have_a_default():
    assert fx_family_color("EQ") != fx_family_color("Dynamics")
    assert fx_family_color(None) == fx_family_color("Unknown")


_RPP = """<REAPER_PROJECT 0.1 "7.0/win64" 0
  TEMPO 120 4 4
  SAMPLERATE 48000 0 0
  <TRACK
    NAME "Kick"
    PEAKCOL 16793792
    VOLPAN 0.5 -0.2 -1 -1 1
    MUTESOLO 0 1 0
    <FXCHAIN
      BYPASS 0 0 0
      <VST "VST: ReaEQ (Cockos)" e.dll 0 "" 0
      >
      BYPASS 1 0 0
      <VST "VST: ReaComp (Cockos)" c.dll 0 "" 0
      >
    >
  >
  <TRACK
    NAME "Drum Bus"
    AUXRECV 0 0 1 0 0 0 0
  >
>
"""


def test_build_console_channel_strip_fields():
    project = parse_rpp(_RPP)
    console = build_console(project)
    assert len(console.strips) == 2

    kick = console.strips[0]
    assert kick.name == "Kick"
    assert kick.header_color == "#c04000"  # decoded, flagged PEAKCOL
    assert kick.volume_db_label == "-6.0 dB"  # 0.5 linear
    assert kick.pan_label == "L20"
    assert kick.soloed is True and kick.muted is False
    # Insert rack in chain order, with bypass state preserved.
    assert [f.name for f in kick.fx] == ["ReaEQ", "ReaComp"]
    assert kick.fx[0].enabled is True
    assert kick.fx[1].enabled is False  # ReaComp bypassed
    assert kick.fx[0].family == "EQ" and kick.fx[1].family == "Dynamics"
    # Outgoing send to the bus, resolved by name with a mode label.
    assert len(kick.sends) == 1
    assert kick.sends[0].target == "Drum Bus"
    assert kick.sends[0].mode == "post-fader"
    assert kick.sends[0].unresolved is False


def test_bus_shows_return_role_and_receive_count():
    project = parse_rpp(_RPP)
    console = build_console(project)
    bus = console.strips[1]
    assert bus.receives == 1
    # A "Bus"-classified track that receives does not double-badge as "return".
    assert bus.roles == ["Bus"]


def test_non_bus_receiver_gets_return_badge():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Lead Vox"
  >
  <TRACK
    NAME "Doubler"
    AUXRECV 0 0 1 0 0 0 0
  >
>
"""
    console = build_console(parse_rpp(rpp))
    doubler = console.strips[1]
    assert "return" in doubler.roles  # receives a send but isn't a bus


def test_master_strip_carries_project_transport():
    console = build_console(parse_rpp(_RPP))
    assert console.master.tempo == 120.0
    assert console.master.time_signature == "4/4"
    assert console.master.sample_rate == 48000


def test_render_console_html_is_self_contained_and_escaped():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Weird <name> & co"
  >
>
"""
    html = render_console_html(build_console(parse_rpp(rpp)))
    assert "<style>" in html and "sse-console" in html
    # The track name's angle brackets/ampersand must be escaped, not injected raw.
    assert "<name>" not in html
    assert "&lt;name&gt;" in html and "&amp;" in html
