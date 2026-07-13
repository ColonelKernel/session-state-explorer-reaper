# 90-second demo script

A tight walkthrough for a screen recording. Aim for ~90 seconds; the six beats below map to
roughly 15 seconds each. Speak in a calm, research-prototype register — no hype. The UI is
mixer-first: a channel-strip console on landing, then signal flow, mix notes, and the
research/data views.

---

**0:00 — Problem (≈15s)**

> "DAW sessions hold rich production knowledge — how a mix is organised, what is processed
> where, how it is routed. But most AI music systems only ever see rendered audio. The
> session structure itself is thrown away."

**0:15 — Prototype (≈15s)**

> "Session State Explorer parses a REAPER project into an interpretable model of its state.
> Loading the bundled example surfaces an at-a-glance overview — tracks, buses, sends, tempo,
> and a count of what it could not fully observe."

*(Click **Load bundled example project** with **Extract audio descriptors** ticked. Let the
overview band populate.)*

**0:30 — Mixer console (≈15s)**

> "It opens on a channel-strip console — the way a mixing engineer reads a session. Each
> track shows its colour, role, fader in dB, pan, its insert chain in order, and its sends."

*(Stay on the **🎚 Mixer** tab; the strips are the landing view. Let the console read.)*

**0:45 — Signal flow (≈15s)**

> "The signal-flow view lays routing out left to right — sources into buses into the master.
> Unresolved routes are marked honestly, as session state the parser could only partially
> observe."

*(Switch to **🔀 Signal flow**; the layered routing graph reads left→right, no hairball.)*

**1:00 — Mix notes (≈15s)**

> "Mix notes turns the state into a review checklist. Each note carries a reason, a concrete
> action, an explicit caveat — heuristics, not rules — and a page citation into the REAPER
> user guide."

*(Switch to **📝 Mix notes**; expand the top card to show Why / Action / Caveat / Grounding.)*

**1:15 — Research value (≈15s)**

> "Interpretable, honest about uncertainty, and grounded in the manual — a step toward
> DAW-state tools that support producers rather than replace them. The whole session exports
> as JSON — state, graph, descriptors and notes — for further research."

*(Switch to **🔬 Data & research**; scroll to the **Export** section to show the JSON downloads.)*

---

## Recording tips

- Generate data first: `python data/examples/make_example_data.py`.
- Run the app from the app venv on port 8502; drive it with the repo `.venv` Playwright
  (`scratchpad/record_demo.py`), which warms the librosa JIT before the recorded pass.
- The example project ships its own audio under `data/examples/audio`, so descriptors and the
  grounded recommendations populate without any extra setup.
- Record at 1600×900; the six beats are timed to `docs/demo/demo.srt`.
