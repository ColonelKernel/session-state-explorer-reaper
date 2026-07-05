# Research context

**Session State Explorer v0 — Interpretable DAW-state graphs for human-centered
AI-assisted music production.**

This note situates the prototype within the research direction it is intended to support:
representations of digital-audio-workstation (DAW) state that are interpretable, honest
about uncertainty, and useful for assistance that respects producer agency.

## DAW-state representation

A modern session is a richly structured artifact: tracks and buses, media items and their
sources, processing chains, automation, and routing. This structure encodes a great deal of
production intent. Yet it is rarely treated as a representational target in its own right;
most computational work operates either on rendered audio or on isolated, decontextualised
parameters. The prototype takes the opposite stance and treats the **session state** as the
object of interest, extracting the accessible, human-meaningful surface of a REAPER project
into a typed data model (`ProjectState`, `TrackState`, `MediaItemState`, `FxState`,
`RouteState`).

## Partial observability

Real sessions are only ever *partially* observable from the project file. Plug-in-internal
state is opaque; referenced plug-ins or audio files may be missing; some routing cannot be
resolved with confidence. Rather than papering over these gaps, the prototype makes them
explicit: uncertain parses become warnings, unresolved routes become dedicated
`bus_or_target` nodes, and the graph reports how many elements were only partially observed.
Treating DAW state as a partially observable representation is, we argue, a more faithful
and more research-relevant framing than pretending a session can be perfectly reconstructed.

## Graph-based session modeling

The session is represented as a directed, typed graph. Nodes capture the *what* (project,
track, media item, audio file, FX, routing target) and edges capture the *how they relate*
(`contains_track`, `contains_item`, `uses_audio_file`, `processes_with`, `sends_to`,
`has_unresolved_route`). This makes the session legible to both people and algorithms: a
human can read the structure directly, while graph-level metrics and traversals enable
analysis that flat parameter lists do not.

## Audio descriptors

Structure alone does not tell us how a session *sounds*. The prototype connects the graph to
a small set of interpretable acoustic descriptors (loudness/RMS, spectral centroid and
rolloff, zero-crossing rate, onset strength, a dynamic-range approximation, and optional
integrated loudness) computed per audio file. The goal is not mastering-grade measurement
but a transparent bridge between session structure and acoustic outcome, so that structural
observations can be cross-checked against the audio they describe.

## Explainable recommendations

The prototype includes a deliberately simple, rule-based recommendation layer. Its purpose
is methodological: to show that an interpretable graph can support **explainable**,
graph-level suggestions. Each recommendation states *why* it was produced, *what* it relates
to (by node id), a candidate action, and an explicit caveat. There is no black box and no
claim of objectivity — the heuristics are scaffolding for a future, more capable, and
evaluated reasoning layer.

The suggestions are additionally **literature-grounded**: candidate actions name concrete
stock processors and canonical workflows drawn from the official REAPER User Guide and the
ReaEffects Guide, and every such recommendation carries page citations
(`reaper_fx_knowledge.py`). Provenance matters for explainability — a suggestion the user
can trace to a documented practice is inspectable and contestable in a way that free-form
generated advice is not.

## Human-centered AI-assisted production

A consistent design commitment runs through the prototype: **assistance, not automation.**
Recommendations are framed as candidate workflow suggestions; uncertainty is surfaced;
producer agency is preserved by construction. This reflects a human-centered stance in which
the system's role is to make a session more legible and to prompt reflection, not to make
creative decisions on the producer's behalf.

## Relevance to the MTG / Steinberg application

The Music Technology Group's strengths in music information retrieval and semantically
meaningful audio analysis, combined with Steinberg's deep expertise in professional DAW
software, define exactly the space this work inhabits: representations that sit between the
audio signal and the production environment. This prototype is a small, end-to-end proof of
fit — parse, represent, analyse, explain — and a concrete starting point for research into
DAW-state representations that *support* creative practice rather than replace it.
