"""Tests for the guide-grounded REAPER stock-FX knowledge table."""

from __future__ import annotations

from session_state_explorer.reaper_fx_knowledge import (
    FAMILY_STOCK_CANDIDATES,
    STOCK_FX,
    WORKFLOWS,
    lookup_stock_fx,
    workflow,
)
from session_state_explorer.utils import classify_fx_family


def test_lookup_normalizes_type_prefixes_and_vendor_suffix():
    assert lookup_stock_fx("VST: ReaComp (Cockos)").canonical_name == "ReaComp"
    assert lookup_stock_fx("VST3: ReaEQ (Cockos)").canonical_name == "ReaEQ"
    assert lookup_stock_fx("JS: analysis/loudness_meter").canonical_name == "JS Loudness Meter"
    assert lookup_stock_fx("reacomp").canonical_name == "ReaComp"


def test_lookup_returns_none_for_third_party_and_empty():
    assert lookup_stock_fx("VST3: Pro-Q 3 (FabFilter)") is None
    assert lookup_stock_fx("Tape Saturation") is None
    assert lookup_stock_fx("") is None
    assert lookup_stock_fx(None) is None


def test_nested_names_resolve_to_the_specific_entry():
    # "reaverb" is a substring of "reaverbate": table order must keep them apart.
    assert lookup_stock_fx("VST: ReaVerbate (Cockos)").canonical_name == "ReaVerbate"
    assert lookup_stock_fx("VST: ReaVerb (Cockos)").canonical_name == "ReaVerb"
    # Similar shape check for the compressor pair.
    assert lookup_stock_fx("VST: ReaXcomp (Cockos)").canonical_name == "ReaXcomp"
    assert lookup_stock_fx("VST: ReaComp (Cockos)").canonical_name == "ReaComp"


def test_table_family_is_authoritative_for_classifier():
    for entry in STOCK_FX:
        # The classifier must agree with the table for every stock entry.
        assert classify_fx_family(f"VST: {entry.canonical_name} (Cockos)") == entry.family


def test_every_entry_and_workflow_is_cited():
    for entry in STOCK_FX:
        assert entry.citations, f"{entry.canonical_name} has no citation"
        assert entry.purpose
    for wf in WORKFLOWS.values():
        assert wf.citations, f"workflow {wf.key} has no citation"
        assert wf.recipe


def test_expected_workflows_present():
    expected = {
        "fx_bus", "folder_submix", "vca_group", "sidechain_send", "parallel_fx",
        "freeze", "offline_vs_bypass", "monitoring_fx", "recovery_mode",
        "routing_matrix_audit", "default_fx_chain",
    }
    assert expected <= set(WORKFLOWS)
    assert workflow("fx_bus").title


def test_family_candidates_reference_real_entries():
    names = {fx.canonical_name for fx in STOCK_FX}
    for family, candidates in FAMILY_STOCK_CANDIDATES.items():
        for candidate in candidates:
            assert candidate in names, f"{family} candidate {candidate} not in STOCK_FX"
