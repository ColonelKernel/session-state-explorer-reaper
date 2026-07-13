"""Streamlit application for Session State Explorer v0.

Run from the repository root::

    streamlit run src/session_state_explorer/app.py

The app parses a REAPER ``.rpp`` into an interpretable DAW-state graph, optionally
extracts audio descriptors for resolvable media files, surfaces explainable
heuristic recommendations, and exports everything to JSON. Every section is robust to
missing data: the app stays useful with only a ``.rpp`` and no audio.
"""

from __future__ import annotations

import os
import sys
import tempfile
from typing import List, Optional

# Allow ``streamlit run src/session_state_explorer/app.py`` without installation by
# ensuring the package's parent (``src``) is importable.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_THIS_DIR)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from session_state_explorer import __version__
from session_state_explorer.audio_descriptors import (
    LIBROSA_AVAILABLE,
    PYLOUDNORM_AVAILABLE,
    extract_descriptors,
    resolve_audio_path,
)
from session_state_explorer.export import (
    build_export,
    descriptors_export,
    graph_export,
    recommendations_export,
    to_json_bytes,
)
from session_state_explorer.fingerprint import (
    compare_fingerprints,
    compute_session_fingerprint,
)
from session_state_explorer.graph_builder import build_graph
from session_state_explorer.mixer import build_console, render_console_html
from session_state_explorer.models import AudioDescriptorSet
from session_state_explorer.recommendations import generate_recommendations
from session_state_explorer.rpp_parser import parse_rpp
from session_state_explorer.visualization import (
    LEGEND,
    PYVIS_AVAILABLE,
    GraphFilters,
    filter_graph,
    render_plotly_figure,
    render_pyvis_html,
)

REPO_ROOT = os.path.dirname(_SRC_DIR)
EXAMPLE_RPP = os.path.join(REPO_ROOT, "data", "examples", "example_project.rpp")
EXAMPLE_DIR = os.path.join(REPO_ROOT, "data", "examples")

SEVERITY_ICON = {"info": "ℹ️", "suggestion": "💡", "warning": "⚠️"}


def _ensure_example_audio() -> None:
    """Synthesise the git-ignored example stems if they are missing.

    The bundled ``.rpp`` is committed but its audio is generated and git-ignored, so a
    fresh checkout — notably a Streamlit Community Cloud deploy — ships without stems.
    We create them on demand from the committed generator so the example's descriptors
    and grounded recommendations populate on first load. Audio is optional: any failure
    (missing soundfile, read-only FS) degrades silently to the graph-only experience.
    """

    try:
        import importlib.util

        gen_path = os.path.join(EXAMPLE_DIR, "make_example_data.py")
        spec = importlib.util.spec_from_file_location("_sse_example_data", gen_path)
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ensure_audio(EXAMPLE_DIR)
    except Exception:  # pragma: no cover - audio is an optional enhancement
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tracks_dataframe(project) -> pd.DataFrame:
    rows = []
    for t in project.tracks:
        rows.append(
            {
                "#": t.index + 1,
                "name": t.name,
                "role": t.role,
                "volume (dB)": t.volume_db,
                "pan": t.pan,
                "mute": t.mute,
                "solo": t.solo,
                "color": t.color,
                "items": len(t.media_items),
                "fx": len(t.fx),
            }
        )
    return pd.DataFrame(rows)


def _items_dataframe(project) -> pd.DataFrame:
    rows = []
    for t in project.tracks:
        for item in t.media_items:
            rows.append(
                {
                    "track": t.name or t.id,
                    "name": item.name,
                    "position (s)": item.position,
                    "length (s)": item.length,
                    "source_type": item.source_type,
                    "source_file": item.source_file,
                }
            )
    return pd.DataFrame(rows)


def _fx_dataframe(project) -> pd.DataFrame:
    rows = []
    for t in project.tracks:
        for fx in t.fx:
            rows.append(
                {
                    "track": t.name or t.id,
                    "slot": fx.index + 1,
                    "name": fx.name,
                    "family": fx.family,
                    "type": fx.fx_type,
                    "enabled": fx.enabled,
                    "preset": fx.preset,
                }
            )
    return pd.DataFrame(rows)


_SEND_MODE_LABELS = {
    0: "post-fader",
    1: "pre-FX",
    2: "post-FX (deprecated)",
    3: "post-FX",
}


def _routes_dataframe(project) -> pd.DataFrame:
    rows = []
    id_to_name = {t.id: (t.name or t.id) for t in project.tracks}
    for r in project.routes:
        rows.append(
            {
                "source": id_to_name.get(r.source_track_id) or r.source_name or "—",
                "target": id_to_name.get(r.target_track_id) or r.target_name or "—",
                "type": r.route_type,
                "mode": _SEND_MODE_LABELS.get(r.send_mode, r.send_mode),
                "volume (dB)": r.volume_db,
                "mute": r.mute,
                "raw_line": (r.raw_line or "").strip(),
            }
        )
    return pd.DataFrame(rows)


def _descriptors_dataframe(descriptors: List[AudioDescriptorSet]) -> pd.DataFrame:
    rows = []
    for d in descriptors:
        rows.append(
            {
                "file": os.path.basename(d.file_path) if d.file_path else d.node_id,
                "available": d.available,
                "duration (s)": d.duration,
                "sr": d.sample_rate,
                "rms_mean": d.rms_mean,
                "centroid (Hz)": d.spectral_centroid_mean,
                "rolloff (Hz)": d.spectral_rolloff_mean,
                "zcr": d.zero_crossing_rate_mean,
                "tempo": d.tempo_estimate,
                "dyn range (dB)": d.dynamic_range_db,
                "peak": d.peak_amplitude,
                "LUFS": d.integrated_loudness_lufs,
                "note": d.unavailable_reason,
            }
        )
    return pd.DataFrame(rows)


def _extract_audio_descriptors(
    graph, rpp_dir: Optional[str], base_dir: Optional[str], uploaded_dir: Optional[str]
) -> tuple:
    """Resolve and analyse every audio_file node. Returns (descriptors, warnings)."""

    descriptors: List[AudioDescriptorSet] = []
    warnings: List[str] = []
    audio_nodes = [
        (nid, data)
        for nid, data in graph.nodes(data=True)
        if data.get("type") == "audio_file"
    ]
    for node_id, data in audio_nodes:
        source = data.get("path")
        resolved = resolve_audio_path(source, rpp_dir=rpp_dir, base_dir=base_dir)
        if resolved is None and uploaded_dir:
            resolved = resolve_audio_path(source, rpp_dir=uploaded_dir)
        if resolved is None:
            warnings.append(
                f"Audio file path not found relative to the selected base directory: "
                f"{source}"
            )
            descriptors.append(
                AudioDescriptorSet(
                    node_id=node_id,
                    file_path=source,
                    available=False,
                    unavailable_reason="Audio file path not found relative to selected "
                    "base directory.",
                )
            )
            continue
        descriptors.append(extract_descriptors(resolved, node_id=node_id))
    return descriptors, warnings


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Session State Explorer v0",
        page_icon="🎚️",
        layout="wide",
    )

    st.title("Session State Explorer v0")
    st.caption(
        "Interpretable DAW-state graphs for AI-assisted music production research"
    )

    _sidebar()

    rpp_text: Optional[str] = st.session_state.get("rpp_text")
    source_file: Optional[str] = st.session_state.get("source_file")

    if not rpp_text:
        _landing()
        return

    project = parse_rpp(rpp_text, source_file=source_file)
    graph = build_graph(project)

    # --- audio descriptors (optional, gated) --------------------------------
    descriptors: List[AudioDescriptorSet] = []
    audio_warnings: List[str] = []
    if st.session_state.get("analyze_audio"):
        base_dir = st.session_state.get("base_dir") or None
        rpp_dir = os.path.dirname(source_file) if source_file and os.path.isfile(source_file) else None
        uploaded_dir = st.session_state.get("uploaded_audio_dir")
        with st.spinner("Extracting audio descriptors with librosa…"):
            descriptors, audio_warnings = _extract_audio_descriptors(
                graph, rpp_dir, base_dir, uploaded_dir
            )
        # Standalone uploaded mixdown/stem descriptors (not tied to a graph node).
        for path in st.session_state.get("standalone_audio", []):
            descriptors.append(
                extract_descriptors(path, node_id=f"uploaded:{os.path.basename(path)}")
            )

    for warning in audio_warnings:
        if warning not in project.warnings:
            project.warnings.append(warning)

    recommendations = generate_recommendations(project, graph, descriptors)

    _overview_band(project, graph, recommendations)

    mixer_tab, flow_tab, notes_tab, data_tab = st.tabs(
        ["🎚 Mixer", "🔀 Signal flow", "📝 Mix notes", "🔬 Data & research"]
    )
    with mixer_tab:
        _mixer_section(project, descriptors)
    with flow_tab:
        _graph_section(graph, project)
    with notes_tab:
        _recommendations_section(recommendations, project)
    with data_tab:
        _tables_section(project)
        _descriptors_section(descriptors)
        _export_section(project, graph, descriptors, recommendations)
        _fingerprint_section(project, descriptors)
        _framing_section()


def _sidebar() -> None:
    with st.sidebar:
        st.header("1 · Input")
        uploaded = st.file_uploader("REAPER project (.rpp)", type=["rpp"])
        if uploaded is not None:
            st.session_state["rpp_text"] = uploaded.getvalue().decode(
                "utf-8", errors="replace"
            )
            # Uploaded files have no on-disk path; record the name only.
            st.session_state["source_file"] = uploaded.name

        if st.button("Load bundled example project", use_container_width=True):
            if os.path.isfile(EXAMPLE_RPP):
                _ensure_example_audio()  # self-heal stems on a fresh (cloud) checkout
                with open(EXAMPLE_RPP, "r", encoding="utf-8") as handle:
                    st.session_state["rpp_text"] = handle.read()
                st.session_state["source_file"] = EXAMPLE_RPP
                st.session_state["base_dir"] = EXAMPLE_DIR
                st.toast("Loaded the bundled example project.")
            else:
                st.warning(
                    "Example project not found. Generate it with: "
                    "`python data/examples/make_example_data.py`"
                )

        local_path = st.text_input(
            "…or load from a local .rpp path",
            value="",
            help=(
                "Absolute path to a REAPER project on this machine. Unlike a browser "
                "upload, this keeps the project-folder context, so audio files resolve "
                "relative to the .rpp automatically."
            ),
        )
        if st.button("Load from local path", use_container_width=True):
            if os.path.isfile(local_path) and local_path.lower().endswith(".rpp"):
                with open(local_path, "r", encoding="utf-8", errors="replace") as handle:
                    st.session_state["rpp_text"] = handle.read()
                st.session_state["source_file"] = local_path
                st.session_state["base_dir"] = os.path.dirname(local_path)
                st.toast("Loaded project from local path.")
            else:
                st.warning("Path not found or not a `.rpp` file.")

        st.divider()
        st.header("2 · Audio (optional)")
        st.caption(
            "When a `.rpp` is uploaded, its original folder is unknown to the browser. "
            "Provide a base directory where the audio files live, or upload stems/a "
            "mixdown directly."
        )
        st.session_state["base_dir"] = st.text_input(
            "Base audio directory (local path)",
            value=st.session_state.get("base_dir", ""),
            help="Audio source paths in the .rpp are resolved relative to this folder.",
        )

        standalone = st.file_uploader(
            "Upload stem / mixdown audio",
            type=["wav", "aif", "aiff", "flac", "ogg", "mp3", "m4a"],
            accept_multiple_files=True,
        )
        if standalone:
            tmp_dir = tempfile.mkdtemp(prefix="sse_audio_")
            paths = []
            for file in standalone:
                dest = os.path.join(tmp_dir, file.name)
                with open(dest, "wb") as handle:
                    handle.write(file.getvalue())
                paths.append(dest)
            st.session_state["uploaded_audio_dir"] = tmp_dir
            st.session_state["standalone_audio"] = paths

        st.session_state["analyze_audio"] = st.checkbox(
            "Extract audio descriptors",
            value=st.session_state.get("analyze_audio", False),
            disabled=not LIBROSA_AVAILABLE,
            help=None if LIBROSA_AVAILABLE else "Install the 'audio' extra (librosa).",
        )
        if not LIBROSA_AVAILABLE:
            st.info("librosa is not installed — audio descriptors are disabled.")
        elif not PYLOUDNORM_AVAILABLE:
            st.caption("pyloudnorm not installed → integrated loudness (LUFS) skipped.")

        st.divider()
        st.caption(f"Session State Explorer v{__version__}")
        st.caption(
            "Renderer: " + ("PyVis" if PYVIS_AVAILABLE else "Plotly (PyVis not installed)")
        )


def _landing() -> None:
    st.info(
        "Upload a REAPER `.rpp` file in the sidebar, or click **Load bundled example "
        "project** to explore a synthetic session."
    )
    st.markdown(
        """
This research prototype parses a REAPER project into an **interpretable, partially
observable DAW-state graph**, extracts simple **audio descriptors**, and produces
**explainable heuristic recommendations**. It does not attempt to reconstruct a
complete session or to replace the producer — it demonstrates how accessible
DAW-state elements can be represented, inspected, and used for explainable
assistance.
"""
    )
    _framing_section()


def _overview_band(project, graph, recommendations) -> None:
    """Compact at-a-glance header of the metrics a mixing engineer cares about."""

    meta = graph.graph
    n_buses = sum(1 for t in project.tracks if (t.role or "") == "Bus")
    tempo = f"{project.tempo:g}" if project.tempo else "—"
    if project.tempo and project.time_sig_num and project.time_sig_denom:
        tempo = f"{project.tempo:g} · {project.time_sig_num}/{project.time_sig_denom}"
    n_warn = sum(1 for r in recommendations if r.severity == "warning")

    cols = st.columns(6)
    cols[0].metric("Tracks", meta.get("n_tracks", 0))
    cols[1].metric("Buses", n_buses)
    cols[2].metric("Sends", meta.get("n_routes", 0))
    cols[3].metric("FX", meta.get("n_fx", 0))
    cols[4].metric("Tempo", tempo)
    cols[5].metric(
        "Flags",
        n_warn,
        help="Warning-level mix notes (see the Mix notes tab).",
        delta=None,
    )

    chips = []
    if meta.get("n_unresolved"):
        chips.append(f"🟤 {meta['n_unresolved']} uncertain element(s)")
    if project.warnings:
        chips.append(f"⚠️ {len(project.warnings)} parser warning(s)")
    if chips:
        with st.expander(" · ".join(chips), expanded=False):
            for warning in project.warnings:
                st.write(f"- {warning}")


def _mixer_section(project, descriptors) -> None:
    if not project.tracks:
        st.info("No tracks parsed — nothing to show on the console.")
        return
    st.caption(
        "Channel-strip console — level, pan, mute/solo, the insert rack (top→bottom in "
        "chain order), and sends. Scroll horizontally for more channels."
    )
    console = build_console(project)
    st.markdown(render_console_html(console), unsafe_allow_html=True)

    # Per-track inspector (native widgets, so it can show richer detail on demand).
    with st.expander("Inspect a channel", expanded=False):
        by_name = {s.name: s for s in console.strips}
        chosen = st.selectbox("Track", list(by_name.keys()), key="mixer_inspect")
        strip = by_name[chosen]
        c1, c2, c3 = st.columns(3)
        c1.metric("Volume", strip.volume_db_label)
        c2.metric("Pan", strip.pan_label)
        c3.metric("Inserts", len(strip.fx))
        st.markdown(
            "**Roles:** " + ", ".join(strip.roles)
            + (f" · receives {strip.receives} send(s)" if strip.receives else "")
        )
        if strip.fx:
            st.markdown("**Insert chain (in order):**")
            for i, fx in enumerate(strip.fx, start=1):
                state = "" if fx.enabled and not fx.offline else f" _({fx.state_label})_"
                line = f"{i}. `{fx.family}` {fx.name}{state}"
                if fx.purpose:
                    line += f" — {fx.purpose}"
                st.markdown(line)
        if strip.sends:
            st.markdown("**Sends:**")
            for send in strip.sends:
                db = "" if send.volume_db is None else f", {send.volume_db:+.1f} dB"
                flag = " ⚠️ unresolved" if send.unresolved else (" (muted)" if send.muted else "")
                st.markdown(f"- → {send.target} ({send.mode}{db}){flag}")
        # That track's audio descriptors, if any resolved to its media.
        track_audio = [
            d for d in descriptors
            if d.available and d.file_path
            and any(
                (item.source_file and os.path.basename(item.source_file) == os.path.basename(d.file_path))
                for t in project.tracks if t.id == strip.track_id
                for item in t.media_items
            )
        ]
        if track_audio:
            st.markdown("**Audio (this channel):**")
            st.dataframe(
                _descriptors_dataframe(track_audio),
                use_container_width=True,
                hide_index=True,
            )


# Graph resolutions: each is a named lens over the same graph. Routing and Processing
# use a layered left-to-right layout (signal flow); Detail keeps the physics view.
_GRAPH_RESOLUTIONS = {
    "Routing — tracks, buses & sends": {
        "filters": dict(show_media_items=False, show_audio_files=False, show_fx=False, show_routes=True),
        "hierarchical": True,
    },
    "Processing — tracks & FX": {
        "filters": dict(show_media_items=False, show_audio_files=False, show_fx=True, show_routes=False),
        "hierarchical": True,
    },
    "Detail — everything": {
        "filters": dict(show_media_items=True, show_audio_files=True, show_fx=True, show_routes=True),
        "hierarchical": False,
    },
}


def _graph_section(graph, project) -> None:
    st.caption(
        "The session as a signal-flow graph. **Routing** and **Processing** read "
        "left→right like a console; **Detail** is the full force-directed view."
    )

    controls, legend = st.columns([3, 1])
    with controls:
        resolution = st.radio(
            "Resolution",
            list(_GRAPH_RESOLUTIONS.keys()),
            index=0,
            horizontal=True,
        )
        track_options = ["(all tracks)"] + [t.name or t.id for t in project.tracks]
        chosen = st.selectbox("Focus on a single track", track_options, index=0)
        only_track = None
        if chosen != "(all tracks)":
            for t in project.tracks:
                if (t.name or t.id) == chosen:
                    only_track = t.id
                    break

    with legend:
        st.caption("Legend")
        for label, color in LEGEND:
            st.markdown(
                f"<span style='display:inline-block;width:12px;height:12px;"
                f"background:{color};border-radius:2px;margin-right:6px;'></span>"
                f"{label}",
                unsafe_allow_html=True,
            )

    spec = _GRAPH_RESOLUTIONS[resolution]
    filters = GraphFilters(only_track=only_track, **spec["filters"])
    view = filter_graph(graph, filters)

    if view.number_of_nodes() == 0:
        st.info("No nodes to display at this resolution.")
        return

    if PYVIS_AVAILABLE:
        try:
            html = render_pyvis_html(view, hierarchical=spec["hierarchical"])
            components.html(html, height=660, scrolling=True)
            return
        except Exception as exc:  # pragma: no cover - defensive UI fallback
            st.warning(f"PyVis rendering failed ({exc}); showing Plotly fallback.")
    st.plotly_chart(render_plotly_figure(view), use_container_width=True)


def _tables_section(project) -> None:
    st.subheader("Tables")
    tabs = st.tabs(["Tracks", "Media items", "FX", "Routes"])
    with tabs[0]:
        st.dataframe(_tracks_dataframe(project), use_container_width=True, hide_index=True)
    with tabs[1]:
        df = _items_dataframe(project)
        if df.empty:
            st.caption("No media items parsed.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
    with tabs[2]:
        df = _fx_dataframe(project)
        if df.empty:
            st.caption("No FX parsed.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
    with tabs[3]:
        df = _routes_dataframe(project)
        if df.empty:
            st.caption("No routes/sends detected.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)


def _descriptors_section(descriptors: List[AudioDescriptorSet]) -> None:
    st.subheader("Audio descriptors")
    if not descriptors:
        st.caption(
            "No audio analysed. Tick **Extract audio descriptors** in the sidebar and "
            "provide a base directory or upload audio."
        )
        return
    st.dataframe(
        _descriptors_dataframe(descriptors), use_container_width=True, hide_index=True
    )
    n_ok = sum(1 for d in descriptors if d.available)
    st.caption(
        f"{n_ok}/{len(descriptors)} audio file(s) analysed. Descriptors are simple, "
        "interpretable summaries — not mastering-grade measurements."
    )


_SEVERITY_ORDER = {"warning": 0, "suggestion": 1, "info": 2}


def _recommendations_section(recommendations, project=None) -> None:
    if not recommendations:
        st.success("No mix notes triggered — nothing flagged on this session.")
        return

    counts = {"warning": 0, "suggestion": 0, "info": 0}
    for rec in recommendations:
        counts[rec.severity] = counts.get(rec.severity, 0) + 1
    summary = ", ".join(
        f"{counts[s]} {label}"
        for s, label in (("warning", "warnings"), ("suggestion", "suggestions"), ("info", "notes"))
        if counts.get(s)
    )
    st.caption(
        f"Mix review — {summary}. Heuristic, graph-level suggestions with REAPER-native "
        "actions and page citations. Support for reflection, not automation."
    )

    # Map track node ids -> names so notes can say which channels they concern.
    name_by_id = {}
    if project is not None:
        name_by_id = {t.id: (t.name or t.id) for t in project.tracks}

    ordered = sorted(
        recommendations, key=lambda r: (_SEVERITY_ORDER.get(r.severity, 9), -r.confidence)
    )
    for rec in ordered:
        icon = SEVERITY_ICON.get(rec.severity, "•")
        tracks = [name_by_id[nid] for nid in rec.related_node_ids if nid in name_by_id]
        where = f"  ·  {', '.join(tracks[:4])}" if tracks else ""
        with st.expander(f"{icon} {rec.title}  ·  {rec.confidence:.0%}{where}"):
            st.markdown(f"**Why:** {rec.explanation}")
            st.markdown(f"**Suggested action:** {rec.suggested_action}")
            st.markdown(f"**Caveat:** _{rec.caveat}_")
            if rec.references:
                st.caption("Grounding: " + "; ".join(rec.references))
            if tracks:
                st.caption("Channels: " + ", ".join(tracks))


def _export_section(project, graph, descriptors, recommendations) -> None:
    st.subheader("Export")
    st.caption("Download the parsed state for reuse in future research or comparison.")
    full = build_export(project, graph, descriptors, recommendations)
    c1, c2, c3, c4 = st.columns(4)
    c1.download_button(
        "Full export JSON",
        data=to_json_bytes(full),
        file_name="session_export.json",
        mime="application/json",
        use_container_width=True,
    )
    c2.download_button(
        "Graph JSON",
        data=to_json_bytes(graph_export(graph)),
        file_name="graph.json",
        mime="application/json",
        use_container_width=True,
    )
    c3.download_button(
        "Descriptors JSON",
        data=to_json_bytes(descriptors_export(descriptors)),
        file_name="descriptors.json",
        mime="application/json",
        use_container_width=True,
    )
    c4.download_button(
        "Recommendations JSON",
        data=to_json_bytes(recommendations_export(recommendations)),
        file_name="recommendations.json",
        mime="application/json",
        use_container_width=True,
    )


def _fingerprint_section(project, descriptors) -> None:
    st.subheader("Session fingerprint & comparison")
    fingerprint = compute_session_fingerprint(project, descriptors)
    with st.expander("Structural fingerprint of this session"):
        st.json(fingerprint)

    other = st.file_uploader(
        "Compare against another exported session (full export JSON)",
        type=["json"],
        key="compare_upload",
    )
    if other is not None:
        import json

        try:
            payload = json.loads(other.getvalue().decode("utf-8", errors="replace"))
            other_fp = payload.get("fingerprint")
            if other_fp is None and "project" in payload:
                # Older export without an embedded fingerprint: reconstruct it.
                from session_state_explorer.models import ProjectState

                other_project = ProjectState.model_validate(payload["project"])
                other_fp = compute_session_fingerprint(other_project, [])
            if other_fp is None:
                st.warning("Could not find a fingerprint or project in that file.")
            else:
                similarity = compare_fingerprints(fingerprint, other_fp)
                st.metric("Structural similarity", f"{similarity:.0%}")
                st.caption(
                    "Cosine similarity over structural counts (track roles, FX families, "
                    "routing). A stretch, illustrative measure — not a validated metric."
                )
        except Exception as exc:
            st.warning(f"Could not read that file as a session export: {exc}")


def _framing_section() -> None:
    with st.expander("Uncertainty and limitations", expanded=False):
        st.markdown(
            """
- **`.rpp` parsing is partial.** This prototype extracts the accessible, human-meaningful
  surface of a session (tracks, items, sources, FX names, sends). It does not decode
  plug-in-private parameter state.
- **Plug-in state may be opaque.** FX are identified by name and coarse family, not by
  their internal settings.
- **Missing plug-ins or audio files** may prevent full reconstruction; unresolved
  elements are flagged rather than hidden.
- **Recommendations are heuristic.** They are meant to support reflection and preserve
  producer agency — not to automate mixing decisions.
"""
        )
    with st.expander("Research framing — relationship to the PhD proposal", expanded=False):
        st.markdown(
            """
This prototype is a *proof-of-fit* for research on **interpretable DAW-state graphs for
human-centered AI-assisted music production**. It demonstrates, end to end, that:

1. a session can be parsed into a **typed, partially observable state**;
2. that state can be represented as an **interpretable graph** of tracks, items, audio
   files, FX and routing;
3. structure can be **linked to acoustic descriptors** of the underlying audio; and
4. the graph can drive **explainable, caveated recommendations** that keep the producer
   in control.

These are exactly the building blocks needed to study DAW-state representations that
*support* creative practice rather than replace it.
"""
        )


if __name__ == "__main__":
    main()
