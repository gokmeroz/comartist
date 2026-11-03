# ComArtist demo cheat sheet

**One-liner:** ComArtist turns a short brief into a lettered comic chapter and keeps characters consistent across chapters.

**Key idea:** generation is only a candidate. It gets critiqued, repaired, judged, and reaches canon only when a person accepts it.

## Before the demo

```sh
uv sync
uv run pytest
uv run streamlit run src/comartist/app.py
open runs/chapter-2-the-rooftop-2/pages/chapter.pdf
```

- [ ] `COMARTIST_META_API_KEY` is in `.env` (sidebar shows it as set)
- [ ] Sidebar provider is **Meta Model API** for live work, **Stub** for a free dry run
- [ ] Budget is set in the sidebar (default $10 per chapter)
- [ ] Chapter PDFs are open as a backup

## Demo flow

| Step | Show | Say |
|---|---|---|
| 1 | Chapter brief (YAML) | "You supply the truth and intent. The agents do the creative execution." |
| 2 | Stage cards and log | "Five agents, with LangGraph controlling the revision loops." |
| 3 | Outline | "Proposed facts stay candidates, not canon." |
| 4 | Script critique | "The Critic gives failure categories, evidence, and a repair." |
| 5 | Visual plan and reference sheets | "Approving a sheet locks that look for later chapters." |
| 6 | Panel attempts | "Retries target the failure. We keep the best attempt, not the last." |
| 7 | Comic pages | "Lettering is deterministic code, not image-model text." |
| 8 | Verdict and acceptance | "Nothing enters canon until a person accepts it." |
| 9 | Chapter 2 PDF, continuity check | "Same faces, new outfits, and the secret stays secret." |

## The pipeline

```text
Brief + carried-over canon
  -> Story Architect
  -> Script Writer <-> Critic
  -> Visual Director
  -> Muse Image <-> Critic
  -> Lettering + layout
  -> Chapter Judge
  -> Human acceptance -> canon + next chapter
```

## Panel retry rules

| Failure | What happens |
|---|---|
| `MISSING_CHARACTER`, `SCRIPT_MISMATCH` | Back to Visual Director, once |
| Other failures, such as `COMPOSITION`, `WRONG_OUTFIT`, `STYLE_DRIFT` | Regenerate with the Critic's repairs |
| Content filter refusal | Reshoot once in neutral wording |
| Same failure twice in a row | Stop early |

**Limits:** 3 attempts per panel, 3 drafts per script, $10 per chapter by default. Unaccepted panels stay marked as not accepted.

## Numbers

| Chapter | Panels | Pages | Attempts | Judge score* | Cost | Status |
|---|---:|---:|---:|---:|---:|---|
| 1: The Reunion | 16 | 4 | 24 | 0.92 | $3.57 | Human accepted |
| 2: The Rooftop | 19 | 4 | 29 | 0.95 | $3.42 | Human accepted |

- Continuity check: **12 of 12** passed
- Tests: **144** passing, no paid inference needed
- Models: **Muse Wonder** (text and critique), **Muse Image** (panels)

*Judge scores are uncalibrated model estimates from one evaluation pair, not measured quality. Some panels were manually regenerated or resumed after errors.

## Live commands

```sh
# Free: show the continuity check
uv run python scripts/check_continuity.py chapter-1-the-reunion chapter-2-the-rooftop-2

# Free: re-letter a finished chapter
uv run python scripts/letter_run.py chapter-1-the-reunion
```

Use `chapter-2-the-rooftop-2`, the accepted run. The older `chapter-2-the-rooftop` shows 5/12.

## If something breaks

| Problem | Do this |
|---|---|
| Run stops partway | Click **Resume**. Finished panels are kept. |
| Budget exhausted | Raise the budget, then **Resume**. Earlier spend still counts. |
| A panel looks wrong | **Fix a panel** with a note. It re-letters and re-judges the chapter. |
| **Accept chapter** is missing | Read the warning: the Judge or a panel blocked it. |
| Stub looks fake or can't be accepted | That's expected. It's a UI rehearsal only. |
| Live generation is slow or down | Switch to the finished chapters and PDFs. |

## Likely questions

- **Is it fully autonomous?** No. Humans approve reference sheets and accept chapters.
- **How does it stay consistent?** Approved references, locked looks, and carried-over dated canon.
- **Why not one big prompt?** Each stage returns validated output and can fail and be repaired on its own.
- **Is there long-term memory?** Not fully. Runs and canon are local files. PostgreSQL, Qdrant, and full temporal memory are planned.
- **What about LoRA, IP-Adapter, ControlNet?** Not built. Consistency uses Muse Image reference conditioning.
- **Does the Judge send work back automatically?** No. A person fixes panels after a rejection.
- **Was the teaser made by ComArtist?** No. It's a labeled concept mockup that predates the pipeline.

## Don't claim

- Scores are measured quality or a general success rate
- Fireworks, Modal, or local generation work (they're UI options only)
- The demo reproduces for $5 (the accepted chapters total about $7)
