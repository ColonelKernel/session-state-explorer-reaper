# Session State Explorer v0

**Interpretable DAW-state graphs for human-centered AI-assisted music production.**

Session State Explorer is a small research prototype that parses a [REAPER](https://www.reaper.fm/)
`.rpp` project into an **interpretable, partially observable graph** of its DAW state —
tracks, media items, audio files, FX chains, and routing — links that structure to simple
**audio descriptors**, and produces **explainable, caveated recommendations**. It is a
proof-of-fit artifact for doctoral research on DAW-state representation, developed in the
context of the Music Technology Group (Universitat Pompeu Fabra) and Steinberg.

> This prototype does not attempt to reconstruct a complete DAW session or replace the
> producer. It demonstrates how accessible DAW-state elements can be represented,
> inspected, and used for explainable assistance.

---

## 1. Research motivation

DAW sessions contain a great deal of structured production knowledge — how a mix is
organised into tracks and buses, which processors are applied where, and how material is
routed — but most AI music systems only ever see rendered audio or isolated parameters.
This prototype treats the **session itself** as a first-class, interpretable object: it
turns the accessible surface of a REAPER project into a typed graph that a human can read,
that an algorithm can reason over, and that is honest about what it could *not* observe.

## 2. Screenshot

> _Add screenshots to [`docs/screenshots/`](docs/screenshots/) and reference them here._
>
> ![Session State Explorer screenshot placeholder](docs/screenshots/placeholder.png)

## 3. Features

- **Tolerant `.rpp` parser** — a stack-based, line-oriented reader that extracts the
  human-meaningful surface of a session and records a warning for anything uncertain,
  rather than failing.
- **Interpretable DAW-state graph** — a typed `networkx` directed graph of project,
  tracks, media items, audio files, FX and routes.
- **Interactive visualization** — PyVis (draggable HTML) with an automatic Plotly
  fallback; node types are colour- and shape-coded with a legend and display filters.
- **Audio descriptors** — simple, interpretable acoustic features per audio file via
  `librosa` (optional, graceful when absent).
- **Explainable recommendations** — five rule-based heuristics, each with an explanation,
  a suggested action, related node ids, and an explicit caveat.
- **Session fingerprint & comparison** — a small structural fingerprint and a similarity
  measure between two exported sessions (stretch feature).
- **JSON export** — graph, descriptors, recommendations, and a full session document.

## 4. Installation

```bash
git clone <your-fork-url> session-state-explorer
cd session-state-explorer
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

Python 3.10+ is required. The audio and visualization layers are optional: if `librosa`
or `pyvis` is missing, the app still parses projects and builds graphs, and tells you what
is unavailable. You can also install via the package extras:

```bash
pip install -e .            # core only
pip install -e ".[full]"    # + audio (librosa, soundfile, pyloudnorm) and PyVis
pip install -e ".[test]"    # + pytest
```

## 5. Usage

Generate the bundled example data (synthetic stems + a matching project), then run the app:

```bash
python data/examples/make_example_data.py
streamlit run src/session_state_explorer/app.py
```

In the app:

1. Click **Load bundled example project** (or upload your own `.rpp`).
2. For audio, set the **base audio directory** (e.g. `data/examples`) or upload stems, then
   tick **Extract audio descriptors**.
3. Explore the summary, graph, tables, descriptors, recommendations, and exports.

## 6. Expected input

- A REAPER project file (`.rpp`, plain text).
- Optionally, the associated audio files (WAV/AIFF/FLAC/OGG/MP3/M4A) reachable via an
  absolute path, a path relative to the project, or a user-supplied base directory; or an
  uploaded stem/mixdown.

Because browser uploads do not expose the original folder, the app asks for a **base audio
directory** when resolving media referenced by an uploaded `.rpp`.

## 7. What the prototype extracts from `.rpp`

| Element       | Fields |
| ------------- | ------ |
| Project       | name, tempo + time signature, sample rate (+ enforced flag), authoring platform, warnings |
| Track         | name, heuristic role, volume (dB), pan / pan mode / pan law / width, mute, solo (+ raw solo mode, solo defeat), master/parent send, colour |
| Media item    | name, position, length, source type |
| Audio file    | source path (resolved when possible) |
| FX            | name, type (VST/JS/AU/CLAP/…), heuristic family, enabled/bypassed, offline, main vs. record chain, preset |
| Route         | source/target track, send vs. unresolved, send mode / level (dB) / pan / mute, raw line |

Plug-in-private parameter state is **not** decoded. FX are identified by name and a coarse
keyword family (EQ, Dynamics, Ambience, Saturation, Modulation, Pitch, Utility, Unknown).

Value semantics (volume scaling, solo modes, send modes, the custom-colour "in use" flag
and its OS-dependent byte order) follow the official REAPER extension SDK documentation.

## 8. Graph schema overview

**Node types:** `project`, `track`, `media_item`, `audio_file`, `fx`, `bus_or_target`
(used for unresolved routes).

**Edge types:** `contains_track`, `contains_item`, `uses_audio_file`, `processes_with`,
`sends_to`, `has_unresolved_route`.

**Graph metadata:** track/item/FX/route counts, number of audio files, density, number of
unresolved (partially observed) elements, number of warnings.

## 9. Recommendation examples

Five heuristic rules, each producing a caveated `Recommendation`:

1. **Shared ambience bus** — several tracks use reverb/delay individually with no shared
   return → suggest a shared ambience bus.
2. **Vocal chain** — a vocal-named track lacks common vocal-processing elements → suggest
   reviewing EQ / compression / de-essing / ambience.
3. **Dense FX chain** — a track carries more than six processors → suggest labelling or
   splitting corrective vs. creative processing.
4. **Missing bus structure** — many tracks (> 8) with no routing detected → suggest groups.
5. **Level imbalance** — one audio item is much hotter than the project median → suggest a
   gain-staging check.

Every recommendation ends with: _“This is a graph-based heuristic, not an objective mixing
rule.”_

## 10. Export format

```json
{
  "schema_version": "0.2.0",
  "project": { "...": "parsed ProjectState" },
  "graph": { "nodes": [], "edges": [], "metadata": {} },
  "descriptors": [],
  "recommendations": [],
  "fingerprint": {},
  "warnings": []
}
```

## 11. Limitations

- `.rpp` parsing is **partial** by design; it captures the accessible surface, not the full
  session.
- Plug-in state is **opaque**: FX are recognised by name/family only.
- Missing plug-ins or audio files may prevent full reconstruction; such gaps are flagged as
  warnings and as `bus_or_target` / unresolved nodes rather than hidden.
- Track colours are stored OS-natively; when the authoring platform cannot be read from the
  project header, the Windows byte order is assumed and a warning notes that red/blue may be
  swapped. Take FX, master-track FX and hardware output routing are detected but not
  modelled (each is surfaced as a warning).
- Audio descriptors are **simple summaries**, not mastering-grade measurements. Integrated
  loudness (LUFS) is computed only when `pyloudnorm` is installed.
- Recommendations are **heuristics for reflection**, not automated mixing decisions.

## 12. Relationship to the PhD proposal

The proposed research concerns **interpretable DAW-state graphs for human-centered
AI-assisted music production**. This prototype demonstrates the core building blocks: a
session can be parsed into a typed, partially observable state; represented as an
interpretable graph; linked to acoustic descriptors; and used to drive explainable,
caveated suggestions that keep the producer in control. See
[`docs/research_context.md`](docs/research_context.md) for the longer framing.

## 13. Roadmap

- Broaden parser coverage (envelopes, take FX, item fades, tempo maps).
- Richer, validated audio descriptors and optional Essentia high-level features.
- Learned (not only rule-based) graph reasoning, evaluated with producers in the loop.
- Cross-DAW state ingestion and a shared, interpretable session schema.
- A curated corpus enabling structural retrieval over many session fingerprints.

## 14. License

[MIT](LICENSE).
