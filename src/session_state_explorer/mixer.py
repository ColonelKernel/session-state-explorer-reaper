"""Channel-strip console view-model for the mixing-engineer UI.

This module turns a parsed :class:`~session_state_explorer.models.ProjectState` into a
mixer's mental model — a row of channel strips, each with a level readout, pan, mute/solo,
an ordered insert rack, and sends — and renders that model to a self-contained HTML block.

The builders here are deliberately **Streamlit-free and pure** so they can be unit-tested
directly; only the ``render_*`` helpers emit markup, and even those return plain strings.
All the data a strip needs is already parsed upstream (track volume/pan/mute/solo/colour/
role, FX family/enabled/offline in chain order, and routes with send mode/level/target).
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import ProjectState, RouteState, TrackState
from .reaper_fx_knowledge import lookup_stock_fx

_FX_TYPE_PREFIXES = ("VST3:", "VST:", "JS:", "AU:", "AUFX:", "CLAP:", "LV2:", "DX:")


def display_fx_name(name: str) -> str:
    """Clean an FX name for the insert rack: canonical stock name, else strip the
    type prefix and a trailing vendor parenthetical."""

    stock = lookup_stock_fx(name)
    if stock is not None:
        return stock.canonical_name
    cleaned = name.strip()
    for prefix in _FX_TYPE_PREFIXES:
        if cleaned.upper().startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    if cleaned.endswith(")") and "(" in cleaned:
        cleaned = cleaned[: cleaned.rfind("(")].strip()
    return cleaned or name


def fx_purpose(name: str) -> Optional[str]:
    """One-line stock-FX purpose for a tooltip, or ``None`` for third-party FX."""

    stock = lookup_stock_fx(name)
    return stock.purpose if stock is not None else None

# ---------------------------------------------------------------------------
# Visual language
# ---------------------------------------------------------------------------
# FX-family chip colours. Kept close to the graph's node palette but assigned per
# processing family so an engineer can read a chain's makeup at a glance.
FAMILY_COLORS: Dict[str, str] = {
    "EQ": "#4c78a8",
    "Dynamics": "#e45756",
    "Ambience": "#72b7b2",
    "Saturation": "#f58518",
    "Modulation": "#b279a2",
    "Pitch": "#54a24b",
    "Utility": "#9d755d",
    "Metering": "#bab0ac",
    "Unknown": "#8c8c8c",
}
_DEFAULT_CHIP = "#8c8c8c"
_DEFAULT_HEADER = "#3a3f4b"  # neutral header when a track has no custom colour


# ---------------------------------------------------------------------------
# View-model
# ---------------------------------------------------------------------------

@dataclass
class FxChip:
    name: str  # cleaned display name (canonical stock name where known)
    family: str
    color: str
    enabled: bool  # False when bypassed
    offline: bool  # True when the plug-in is unloaded
    purpose: Optional[str] = None  # stock-FX one-liner for a tooltip

    @property
    def state_label(self) -> str:
        if self.offline:
            return "offline"
        if not self.enabled:
            return "bypassed"
        return "active"


@dataclass
class SendLine:
    target: str  # resolved target name (or a description of the unresolved end)
    mode: str  # human label: post-fader / pre-FX / post-FX
    volume_db: Optional[float]
    muted: bool
    unresolved: bool


@dataclass
class ChannelStrip:
    track_id: str
    index: int
    name: str
    header_color: str
    roles: List[str]
    volume_db_label: str
    pan_label: str
    muted: bool
    soloed: bool
    fx: List[FxChip] = field(default_factory=list)
    sends: List[SendLine] = field(default_factory=list)
    n_items: int = 0
    receives: int = 0  # number of sends arriving at this track


@dataclass
class MasterStrip:
    tempo: Optional[float]
    time_signature: Optional[str]
    sample_rate: Optional[int]
    note: str = "Master-track FX are not parsed from the .rpp yet."


@dataclass
class ConsoleModel:
    strips: List[ChannelStrip]
    master: MasterStrip


# ---------------------------------------------------------------------------
# Formatting helpers (pure)
# ---------------------------------------------------------------------------

_SEND_MODE_LABELS = {0: "post-fader", 1: "pre-FX", 2: "post-FX", 3: "post-FX"}


def format_db(volume_db: Optional[float]) -> str:
    """Fader readout. ``None`` means REAPER stored a non-positive gain (-inf)."""

    if volume_db is None:
        return "-∞ dB"
    if abs(volume_db) < 0.05:
        return "0.0 dB"  # unity
    return f"{volume_db:+.1f} dB"


def format_pan(pan: Optional[float]) -> str:
    """REAPER pan is -1..+1. Render as C / L<n> / R<n> (percent off-centre)."""

    if pan is None:
        return "—"
    if abs(pan) < 0.005:
        return "C"
    side = "L" if pan < 0 else "R"
    return f"{side}{round(abs(pan) * 100)}"


def fx_family_color(family: Optional[str]) -> str:
    return FAMILY_COLORS.get(family or "Unknown", _DEFAULT_CHIP)


def _roles_for(track: TrackState, receives: int) -> List[str]:
    """Functional role chips for a strip.

    REAPER tracks are multi-role: a strip may be both a classified instrument role
    *and* a return. We surface the classified role plus a derived "return" badge when
    the track receives sends (and is not already labelled a bus), so the console shows
    that flexibility rather than forcing one type.
    """

    roles: List[str] = []
    role = track.role
    if role and role != "Unknown":
        roles.append(role)
    if receives > 0 and role != "Bus":
        roles.append("return")
    if not roles:
        roles.append("track")
    return roles


# ---------------------------------------------------------------------------
# Builders (pure)
# ---------------------------------------------------------------------------

def build_channel_strip(
    track: TrackState,
    outgoing: List[RouteState],
    name_by_id: Dict[str, str],
    receives: int,
) -> ChannelStrip:
    fx = [
        FxChip(
            name=display_fx_name(f.name),
            family=f.family or "Unknown",
            color=fx_family_color(f.family),
            enabled=f.enabled is not False,
            offline=f.offline is True,
            purpose=fx_purpose(f.name),
        )
        for f in track.fx
    ]
    sends = [
        SendLine(
            target=(
                name_by_id.get(r.target_track_id or "", "")
                or r.target_name
                or (r.source_name or "unresolved")
            ),
            mode=_SEND_MODE_LABELS.get(r.send_mode, "send"),
            volume_db=r.volume_db,
            muted=r.mute is True,
            unresolved=(r.route_type == "unresolved" or r.target_track_id is None),
        )
        for r in outgoing
    ]
    return ChannelStrip(
        track_id=track.id,
        index=track.index,
        name=track.name or f"Track {track.index + 1}",
        header_color=track.color or _DEFAULT_HEADER,
        roles=_roles_for(track, receives),
        volume_db_label=format_db(track.volume_db),
        pan_label=format_pan(track.pan),
        muted=track.mute is True,
        soloed=track.solo is True,
        fx=fx,
        sends=sends,
        n_items=len(track.media_items),
        receives=receives,
    )


def build_console(project: ProjectState) -> ConsoleModel:
    name_by_id = {t.id: (t.name or f"Track {t.index + 1}") for t in project.tracks}

    outgoing_by_source: Dict[str, List[RouteState]] = {}
    receives_by_target: Dict[str, int] = {}
    for route in project.routes:
        if route.source_track_id:
            outgoing_by_source.setdefault(route.source_track_id, []).append(route)
        if route.target_track_id:
            receives_by_target[route.target_track_id] = (
                receives_by_target.get(route.target_track_id, 0) + 1
            )

    strips = [
        build_channel_strip(
            track,
            outgoing_by_source.get(track.id, []),
            name_by_id,
            receives_by_target.get(track.id, 0),
        )
        for track in project.tracks
    ]

    ts = None
    if project.time_sig_num and project.time_sig_denom:
        ts = f"{project.time_sig_num}/{project.time_sig_denom}"
    master = MasterStrip(
        tempo=project.tempo,
        time_signature=ts,
        sample_rate=project.sample_rate,
    )
    return ConsoleModel(strips=strips, master=master)


# ---------------------------------------------------------------------------
# HTML rendering (returns strings; no Streamlit)
# ---------------------------------------------------------------------------

CONSOLE_CSS = """
<style>
.sse-console { display: flex; gap: 10px; overflow-x: auto; padding: 6px 2px 14px 2px; }
.sse-strip {
  flex: 0 0 172px; border: 1px solid rgba(128,128,128,0.35); border-radius: 8px;
  background: rgba(128,128,128,0.06); display: flex; flex-direction: column;
  font-size: 12px; line-height: 1.35; overflow: hidden;
}
.sse-strip__hd { padding: 6px 8px; color: #fff; font-weight: 600;
  text-shadow: 0 1px 2px rgba(0,0,0,0.45); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.sse-strip__body { padding: 8px; display: flex; flex-direction: column; gap: 6px; }
.sse-roles { display: flex; flex-wrap: wrap; gap: 3px; }
.sse-chip { display: inline-block; padding: 1px 6px; border-radius: 999px;
  font-size: 10px; background: rgba(128,128,128,0.22); }
.sse-meter { display: flex; align-items: baseline; justify-content: space-between; }
.sse-db { font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums; }
.sse-pan { font-size: 11px; opacity: 0.75; }
.sse-ms { display: flex; gap: 5px; }
.sse-badge { padding: 1px 7px; border-radius: 4px; font-size: 10px; font-weight: 700;
  border: 1px solid rgba(128,128,128,0.4); opacity: 0.55; }
.sse-badge--on-m { background: #e45756; color: #fff; border-color: #e45756; opacity: 1; }
.sse-badge--on-s { background: #f2c744; color: #000; border-color: #f2c744; opacity: 1; }
.sse-sec { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em;
  opacity: 0.55; margin-top: 2px; }
.sse-fx { display: flex; align-items: center; gap: 5px; }
.sse-fx__dot { width: 8px; height: 8px; border-radius: 2px; flex: 0 0 auto; }
.sse-fx__name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sse-fx--off .sse-fx__name { text-decoration: line-through; opacity: 0.5; }
.sse-send { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sse-send--muted { opacity: 0.5; text-decoration: line-through; }
.sse-send--unresolved { color: #d62728; }
.sse-muted-note { opacity: 0.5; font-style: italic; }
.sse-strip--master { flex-basis: 150px; background: rgba(76,120,168,0.12); }
</style>
"""


def _chip(text: str) -> str:
    return f'<span class="sse-chip">{html.escape(text)}</span>'


def _fx_row(fx: FxChip) -> str:
    off = " sse-fx--off" if (not fx.enabled or fx.offline) else ""
    marker = " ⏻" if fx.offline else ("" if fx.enabled else " (byp)")
    tip = f"{fx.family} · {fx.state_label}"
    if fx.purpose:
        tip += f" — {fx.purpose}"
    return (
        f'<div class="sse-fx{off}" title="{html.escape(tip)}">'
        f'<span class="sse-fx__dot" style="background:{fx.color}"></span>'
        f'<span class="sse-fx__name">{html.escape(fx.name)}{marker}</span></div>'
    )


def _send_row(send: SendLine) -> str:
    cls = "sse-send"
    if send.unresolved:
        cls += " sse-send--unresolved"
    elif send.muted:
        cls += " sse-send--muted"
    db = "" if send.volume_db is None else f" {send.volume_db:+.1f} dB"
    return (
        f'<div class="{cls}">→ {html.escape(send.target)} '
        f'<span style="opacity:0.6">({html.escape(send.mode)}{db})</span></div>'
    )


def render_strip_html(strip: ChannelStrip) -> str:
    roles = "".join(_chip(r) for r in strip.roles)
    m_cls = "sse-badge sse-badge--on-m" if strip.muted else "sse-badge"
    s_cls = "sse-badge sse-badge--on-s" if strip.soloed else "sse-badge"
    fx_html = (
        "".join(_fx_row(f) for f in strip.fx)
        if strip.fx
        else '<div class="sse-muted-note">no inserts</div>'
    )
    sends_html = (
        "".join(_send_row(s) for s in strip.sends)
        if strip.sends
        else '<div class="sse-muted-note">no sends</div>'
    )
    recv = f' · {strip.receives} in' if strip.receives else ""
    return (
        '<div class="sse-strip">'
        f'<div class="sse-strip__hd" style="background:{strip.header_color}" '
        f'title="{html.escape(strip.name)}">{html.escape(strip.name)}</div>'
        '<div class="sse-strip__body">'
        f'<div class="sse-roles">{roles}</div>'
        '<div class="sse-meter">'
        f'<span class="sse-db">{html.escape(strip.volume_db_label)}</span>'
        f'<span class="sse-pan">pan {html.escape(strip.pan_label)}</span></div>'
        f'<div class="sse-ms"><span class="{m_cls}">M</span>'
        f'<span class="{s_cls}">S</span>'
        f'<span style="opacity:0.5;font-size:10px;align-self:center">'
        f'{strip.n_items} item{"s" if strip.n_items != 1 else ""}{recv}</span></div>'
        f'<div class="sse-sec">inserts</div>{fx_html}'
        f'<div class="sse-sec">sends</div>{sends_html}'
        "</div></div>"
    )


def _render_master_html(master: MasterStrip) -> str:
    rows = []
    rows.append(f"tempo {master.tempo:g}" if master.tempo else "tempo —")
    if master.time_signature:
        rows.append(master.time_signature)
    if master.sample_rate:
        rows.append(f"{master.sample_rate} Hz")
    body = "".join(f'<div class="sse-send">{html.escape(r)}</div>' for r in rows)
    return (
        '<div class="sse-strip sse-strip--master">'
        '<div class="sse-strip__hd" style="background:#4c78a8">Master</div>'
        '<div class="sse-strip__body">'
        f'<div class="sse-sec">project</div>{body}'
        f'<div class="sse-muted-note" style="margin-top:6px">{html.escape(master.note)}</div>'
        "</div></div>"
    )


def render_console_html(console: ConsoleModel) -> str:
    """Full, self-contained HTML block for the channel-strip console."""

    strips = "".join(render_strip_html(s) for s in console.strips)
    master = _render_master_html(console.master)
    return f'{CONSOLE_CSS}<div class="sse-console">{strips}{master}</div>'
