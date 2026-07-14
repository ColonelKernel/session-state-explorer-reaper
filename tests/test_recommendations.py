"""Tests for the heuristic recommendation engine."""

from __future__ import annotations

from session_state_explorer.graph_builder import build_graph
from session_state_explorer.models import AudioDescriptorSet
from session_state_explorer.recommendations import generate_recommendations
from session_state_explorer.rpp_parser import parse_rpp


def _ids(recs):
    return {r.id for r in recs}


def test_vocal_without_fx_produces_vocal_chain_recommendation():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Lead Vox"
  >
>
"""
    project = parse_rpp(rpp)
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, [])
    assert any(r.id.startswith("rec-vocal-chain") for r in recs)
    # Every recommendation must carry a caveat (producer agency).
    assert all(r.caveat for r in recs)


def test_many_tracks_without_routes_produces_bus_recommendation():
    tracks = "\n".join(
        f'  <TRACK\n    NAME "Track {i}"\n  >' for i in range(9)
    )
    rpp = f'<REAPER_PROJECT 0.1 "x" 0\n{tracks}\n>\n'
    project = parse_rpp(rpp)
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, [])
    assert "rec-missing-bus" in _ids(recs)


def test_ambience_fx_without_shared_send_produces_ambience_bus_recommendation():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Snare"
    <FXCHAIN
      BYPASS 0 0 0
      <VST "VST: ReaVerbate (Cockos)" v.dll 0 "" 0
      >
    >
  >
  <TRACK
    NAME "Guitar"
    <FXCHAIN
      BYPASS 0 0 0
      <VST "VST: ReaDelay (Cockos)" d.dll 0 "" 0
      >
    >
  >
>
"""
    project = parse_rpp(rpp)
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, [])
    assert "rec-ambience-bus" in _ids(recs)


def test_dense_fx_chain_recommendation():
    fx_lines = "\n".join(
        '      BYPASS 0 0 0\n'
        f'      <VST "VST: Plug{i} (X)" p.dll 0 "" 0\n      >'
        for i in range(7)
    )
    rpp = f"""<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Synth"
    <FXCHAIN
{fx_lines}
    >
  >
>
"""
    project = parse_rpp(rpp)
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, [])
    assert any(r.id.startswith("rec-dense-fx") for r in recs)


def test_level_imbalance_recommendation():
    descriptors = [
        AudioDescriptorSet(node_id="audio-0", file_path="a.wav", available=True,
                           rms_mean=0.1, peak_amplitude=0.2),
        AudioDescriptorSet(node_id="audio-1", file_path="b.wav", available=True,
                           rms_mean=0.1, peak_amplitude=0.2),
        AudioDescriptorSet(node_id="audio-2", file_path="hot.wav", available=True,
                           rms_mean=0.9, peak_amplitude=0.95),
    ]
    # Minimal project; the rule only needs the descriptors.
    project = parse_rpp('<REAPER_PROJECT 0.1 "x" 0\n>\n')
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, descriptors)
    imbalance = [r for r in recs if r.id.startswith("rec-level-imbalance")]
    assert len(imbalance) == 1
    assert imbalance[0].related_node_ids == ["audio-2"]


def test_level_imbalance_aggregates_multiple_hot_files():
    # Several hot stems must yield ONE aggregated recommendation, not one card
    # per file (observed as recommendation spam on a real 23-stem session).
    descriptors = [
        AudioDescriptorSet(node_id=f"audio-{i}", file_path=f"q{i}.wav", available=True,
                           rms_mean=0.1, peak_amplitude=0.2)
        for i in range(3)
    ] + [
        AudioDescriptorSet(node_id="audio-hot1", file_path="hot1.wav", available=True,
                           rms_mean=0.9, peak_amplitude=0.95),
        AudioDescriptorSet(node_id="audio-hot2", file_path="hot2.wav", available=True,
                           rms_mean=0.8, peak_amplitude=0.9),
    ]
    project = parse_rpp('<REAPER_PROJECT 0.1 "x" 0\n>\n')
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, descriptors)
    imbalance = [r for r in recs if r.id.startswith("rec-level-imbalance")]
    assert len(imbalance) == 1
    assert set(imbalance[0].related_node_ids) == {"audio-hot1", "audio-hot2"}
    assert "2 audio items" in imbalance[0].explanation


def test_well_structured_session_produces_no_false_positives():
    # A vocal with a full chain, an ambience return that receives a send, few tracks.
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Lead Vox"
    <FXCHAIN
      BYPASS 0 0 0
      <VST "VST: ReaEQ (Cockos)" e.dll 0 "" 0
      >
      BYPASS 0 0 0
      <VST "VST: ReaComp (Cockos)" c.dll 0 "" 0
      >
    >
    AUXRECV 1 0 1 0 0 0 0
  >
  <TRACK
    NAME "Reverb Return"
    <FXCHAIN
      BYPASS 0 0 0
      <VST "VST: ReaVerbate (Cockos)" v.dll 0 "" 0
      >
    >
  >
>
"""
    project = parse_rpp(rpp)
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, [])
    ids = _ids(recs)
    assert "rec-ambience-bus" not in ids  # a shared ambience return exists
    assert "rec-missing-bus" not in ids  # routes exist and few tracks
    assert not any(i.startswith("rec-vocal-chain") for i in ids)  # full vocal chain
    # None of the guide-grounded hygiene rules should fire on a clean session.
    for rule_id in (
        "rec-fx-all-offline",
        "rec-muted-sends",
        "rec-bypassed-fx",
        "rec-manual-submix",
        "rec-meters-in-render-path",
    ):
        assert rule_id not in ids


# ---------------------------------------------------------------------------
# Guide-grounded rules (REAPER stock plugins and workflows)
# ---------------------------------------------------------------------------

def _recs_for(rpp: str, descriptors=None):
    project = parse_rpp(rpp)
    graph = build_graph(project)
    return generate_recommendations(project, graph, descriptors or [])


def test_upgraded_rules_cite_the_guides_and_name_stock_fx():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Lead Vox"
  >
>
"""
    recs = _recs_for(rpp)
    vocal = next(r for r in recs if r.id.startswith("rec-vocal-chain"))
    assert "ReaEQ" in vocal.suggested_action
    assert "ReaComp" in vocal.suggested_action
    assert "ReaFir" in vocal.suggested_action
    assert vocal.references and all("REAPER" in ref for ref in vocal.references)


def test_all_fx_offline_fires_only_when_everything_is_offline():
    def track(name, offline):
        flag = 1 if offline else 0
        return (
            f'  <TRACK\n    NAME "{name}"\n    <FXCHAIN\n'
            f"      BYPASS 0 {flag} 0\n"
            f'      <VST "VST: ReaEQ (Cockos)" e.dll 0 "" 0\n      >\n'
            f"      BYPASS 0 {flag} 0\n"
            f'      <VST "VST: ReaComp (Cockos)" c.dll 0 "" 0\n      >\n'
            "    >\n  >"
        )

    all_offline = f'<REAPER_PROJECT 0.1 "x" 0\n{track("A", True)}\n{track("B", True)}\n>\n'
    recs = _recs_for(all_offline)
    assert "rec-fx-all-offline" in _ids(recs)

    mixed = f'<REAPER_PROJECT 0.1 "x" 0\n{track("A", True)}\n{track("B", False)}\n>\n'
    assert "rec-fx-all-offline" not in _ids(_recs_for(mixed))


def test_muted_and_near_silent_sends_aggregate_to_one_card():
    # Send tokens: AUXRECV <src> <mode> <vol> <pan> <mute>.
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Guitar"
  >
  <TRACK
    NAME "Keys"
  >
  <TRACK
    NAME "Bus"
    AUXRECV 0 0 1 0 1 0 0
    AUXRECV 1 0 0.0001 0 0 0 0
  >
>
"""
    recs = _recs_for(rpp)
    cards = [r for r in recs if r.id == "rec-muted-sends"]
    assert len(cards) == 1
    assert "2" in cards[0].title
    assert len(cards[0].related_node_ids) == 2
    assert cards[0].references


def test_live_send_does_not_trigger_muted_sends():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Guitar"
  >
  <TRACK
    NAME "Bus"
    AUXRECV 0 0 1 0 0 0 0
  >
>
"""
    assert "rec-muted-sends" not in _ids(_recs_for(rpp))


def test_bypassed_fx_accumulation_fires_at_two_per_track():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Synth"
    <FXCHAIN
      BYPASS 1 0 0
      <VST "VST: ReaEQ (Cockos)" e.dll 0 "" 0
      >
      BYPASS 1 0 0
      <VST "VST: ReaComp (Cockos)" c.dll 0 "" 0
      >
    >
  >
>
"""
    recs = _recs_for(rpp)
    assert "rec-bypassed-fx" in _ids(recs)

    single = rpp.replace(
        'BYPASS 1 0 0\n      <VST "VST: ReaComp', 'BYPASS 0 0 0\n      <VST "VST: ReaComp'
    )
    assert "rec-bypassed-fx" not in _ids(_recs_for(single))


def test_offline_fx_do_not_count_as_bypassed():
    # Offline processors are already "honestly parked" — the rule must not
    # double-flag them.
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Synth"
    <FXCHAIN
      BYPASS 1 1 0
      <VST "VST: ReaEQ (Cockos)" e.dll 0 "" 0
      >
      BYPASS 1 1 0
      <VST "VST: ReaComp (Cockos)" c.dll 0 "" 0
      >
    >
  >
>
"""
    assert "rec-bypassed-fx" not in _ids(_recs_for(rpp))


def test_manual_submix_detected_when_sources_skip_master():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Kick"
    MAINSEND 0 0
  >
  <TRACK
    NAME "Snare"
    MAINSEND 0 0
  >
  <TRACK
    NAME "Drum Bus"
    AUXRECV 0 0 1 0 0 0 0
    AUXRECV 1 0 1 0 0 0 0
  >
>
"""
    recs = _recs_for(rpp)
    cards = [r for r in recs if r.id == "rec-manual-submix"]
    assert len(cards) == 1
    assert "folder" in cards[0].suggested_action.lower()
    assert cards[0].references


def test_submix_not_flagged_when_sources_still_feed_master():
    # main_send True (or unknown) means this is a normal shared send, not the
    # other-DAW submix pattern.
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Kick"
    MAINSEND 1 0
  >
  <TRACK
    NAME "Snare"
    MAINSEND 1 0
  >
  <TRACK
    NAME "Drum Bus"
    AUXRECV 0 0 1 0 0 0 0
    AUXRECV 1 0 1 0 0 0 0
  >
>
"""
    assert "rec-manual-submix" not in _ids(_recs_for(rpp))


def test_clipping_risk_aggregates_hot_files():
    descriptors = [
        AudioDescriptorSet(node_id="audio-0", file_path="ok.wav", available=True,
                           rms_mean=0.1, peak_amplitude=0.7),
        AudioDescriptorSet(node_id="audio-1", file_path="hot1.wav", available=True,
                           rms_mean=0.2, peak_amplitude=0.999),
        AudioDescriptorSet(node_id="audio-2", file_path="hot2.wav", available=True,
                           rms_mean=0.2, peak_amplitude=1.0),
    ]
    recs = _recs_for('<REAPER_PROJECT 0.1 "x" 0\n>\n', descriptors)
    cards = [r for r in recs if r.id == "rec-clipping-risk"]
    assert len(cards) == 1
    assert set(cards[0].related_node_ids) == {"audio-1", "audio-2"}
    assert "ReaLimit" in cards[0].suggested_action


def test_meters_in_render_path_suggest_monitoring_fx():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Mix Bus"
    <FXCHAIN
      BYPASS 0 0 0
      <JS analysis/loudness_meter ""
      >
    >
  >
>
"""
    recs = _recs_for(rpp)
    cards = [r for r in recs if r.id == "rec-meters-in-render-path"]
    assert len(cards) == 1
    assert "Monitoring FX" in cards[0].suggested_action
    assert cards[0].references


# ---------------------------------------------------------------------------
# Rule 12: descriptor-triggered broadband-noise floor (ReaFir Subtract)
# ---------------------------------------------------------------------------

_EMPTY_RPP = '<REAPER_PROJECT 0.1 "x" 0\n>\n'


def _noise_desc(node_id="audio-0", file_path="hiss.wav", *, zcr, dyn):
    return AudioDescriptorSet(
        node_id=node_id,
        file_path=file_path,
        available=True,
        zero_crossing_rate_mean=zcr,
        dynamic_range_db=dyn,
    )


def test_noise_reduction_fires_on_broadband_noise_floor():
    # Steady hiss: high zero-crossing rate AND low dynamic range.
    recs = _recs_for(_EMPTY_RPP, [_noise_desc(zcr=0.50, dyn=0.4)])
    cards = [r for r in recs if r.id == "rec-noise-reduction"]
    assert len(cards) == 1
    assert cards[0].severity == "info"
    assert cards[0].related_node_ids == ["audio-0"]
    assert "Subtract" in cards[0].suggested_action
    # Grounded in the ReaEffects Guide via the ReaFir stock-FX citation.
    assert any("ReaEffects Guide" in ref for ref in cards[0].references)


def test_noise_reduction_ignores_percussion_high_zcr_wide_dynamics():
    # Snare/hats: the same high zero-crossing rate, but transients keep the
    # dynamic range wide, so this must NOT be flagged as a noise floor.
    recs = _recs_for(_EMPTY_RPP, [_noise_desc(file_path="snare.wav", zcr=0.50, dyn=65.0)])
    assert "rec-noise-reduction" not in _ids(recs)


def test_noise_reduction_ignores_tonal_low_zcr():
    # A tonal stem: low zero-crossing rate, so it never qualifies regardless of range.
    recs = _recs_for(_EMPTY_RPP, [_noise_desc(file_path="bass.wav", zcr=0.01, dyn=5.0)])
    assert "rec-noise-reduction" not in _ids(recs)


def test_noise_reduction_aggregates_and_skips_incomplete_descriptors():
    descriptors = [
        _noise_desc(node_id="audio-0", file_path="hiss1.wav", zcr=0.40, dyn=3.0),
        _noise_desc(node_id="audio-1", file_path="hiss2.wav", zcr=0.30, dyn=8.0),
        _noise_desc(file_path="perc.wav", zcr=0.50, dyn=62.0),  # excluded (wide range)
        AudioDescriptorSet(node_id="audio-3", file_path="x.wav", available=True),  # no fields
        AudioDescriptorSet(node_id="audio-4", available=False,
                           zero_crossing_rate_mean=0.4, dynamic_range_db=1.0),  # unavailable
    ]
    cards = [r for r in _recs_for(_EMPTY_RPP, descriptors) if r.id == "rec-noise-reduction"]
    assert len(cards) == 1
    assert set(cards[0].related_node_ids) == {"audio-0", "audio-1"}
