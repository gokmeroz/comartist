# ComArtist repository guidance

## Project context and current scope

ComArtist is a Python-first agentic AI system that turns a short comic chapter
brief into a coherent comic chapter. It is an early research and development
project. Its defining challenge is maintaining characters, relationships,
visual identity, character knowledge, and story continuity across sequential
panels and long-running chapters.

The user supplies truth and creative intent; the system supplies creative
execution. Generation produces a candidate, not an automatically accepted
result. Candidates must be evaluated, and revisions should address specific
failures rather than blindly repeat generation.

The project was built out for the Meta Global AI Developer Hackathon
(Oct 26 – Nov 4, 2026) and is now in a post-hackathon hardening phase. All five
agent roles, the script and panel revision loops, lettering/layout, the Chapter
Judge, the acceptance boundary, and a two-chapter continuity demo exist. Prefer
consolidating and testing what exists over adding new architecture; introduce
new components only when requested.

The README provides broader project context. The architecture below captures
the current implementation direction and supersedes the README's broader agent
roster and roadmap wherever they differ.

## Architecture

Use Streamlit as a thin interface over a LangGraph workflow. Represent workflow
inputs, outputs, and shared state with Pydantic models.

Reserve agents for reasoning-heavy decisions. Do not turn every component into
an agent. There are five planned agent roles:

1. **Story Architect:** Interpret the brief and retrieved context; establish
   dramatic structure, event sequence, emotional progression, and page beats.
2. **Script Writer:** Produce structured scenes, panels, actions, dialogue,
   captions, and transitions while respecting canon and character knowledge.
3. **Visual Director:** Translate the script into framing, composition, poses,
   lighting, character placement, and visual conditioning requirements.
4. **Critic:** Evaluate script and visual candidates through appropriate
   text or multimodal model access; report actionable failures and recommended
   repairs. Script and visual critique are modes of this role, not additional
   agent roles.
5. **Chapter Judge:** Evaluate the assembled chapter as a sequential narrative,
   including pacing, readability, continuity, and overall coherence.

The intended flow is:

```text
Brief + retrieved context
  -> Story Architect
  -> Script Writer <-> Critic
  -> Visual Director
  -> panel generation service <-> Critic-directed revision
  -> lettering/layout service
  -> Chapter Judge
  -> accepted chapter + evaluation report + generation trace
```

LangGraph controls routing, bounded revision loops, checkpoints, and workflow
status. It should route failures to the stage that can repair them.

Implement these components as tools or services, not agents:

- Image generation and conditioning.
- Lettering, page layout, and export.
- Canonical storage and state updates.
- Semantic retrieval and context assembly.
- Temporal queries and character-knowledge lookup.
- Deterministic schema, reference, and continuity validation.
- Trace recording, cost accounting, and model access.

Keep UI, orchestration, agent reasoning, model adapters, and persistence separate.
Streamlit must not own core business logic. Agents should consume typed context
and return typed results; services should expose explicit, testable interfaces.

## State, memory, and canon

Use Pydantic models for the chapter brief, series and character state, timeline
events, story beats, script, panel specifications, critiques, generation
attempts, and chapter results. Use stable identifiers to connect artifacts and
preserve their provenance.

- **PostgreSQL:** Source of truth for accepted canonical structured state,
  relationships, events, and persisted workflow records.
- **Qdrant:** Semantic/RAG index for retrieving relevant scenes, conversations,
  and lore. Retrieved text does not override canonical records.
- **Temporal memory:** Represent when facts hold and when characters learn
  information. Support flashbacks without leaking future facts or knowledge.
- **Visual references:** Track approved character and location references,
  outfits, and relevant prior panels through explicit asset references.

Distinguish user-established or previously accepted **canon**, explicitly
labeled **derived information**, and candidate **ephemeral fiction**. Agents
must not silently modify canon. Inventions that establish lasting facts need
an explicit acceptance/commit policy. Failed drafts and rejected generations
must never become canonical memory.

Store candidate changes separately from accepted state. Record the source,
story time, and acceptance status of facts. Commit chapter state only through
a deliberate acceptance boundary; keep retrying generation from duplicating
accepted events or records.

## Planned technology stack

| Area | Planned technologies |
| --- | --- |
| Language and dependency management | Python, uv |
| Structured models | Pydantic |
| UI | Streamlit |
| Orchestration | LangGraph |
| Model access and serving | LiteLLM, vLLM |
| Model and image tooling | Hugging Face Transformers, Diffusers, PEFT, Accelerate |
| Visual consistency | LoRA, IP-Adapter, ControlNet |
| Canonical persistence | PostgreSQL |
| Semantic memory | Qdrant, embeddings, RAG |
| Continuity | Temporal memory and structured character knowledge |
| Packaging and infrastructure | Docker |
| Testing | pytest |

This is a planned stack, not a claim that these dependencies are installed.
Introduce dependencies when their implementation phase needs them. Keep model
and image backends behind adapters so orchestration does not depend on a
particular provider or checkpoint.

## Coding conventions

- Use Python with type annotations on public interfaces and Pydantic models at
  workflow and service boundaries. Avoid loosely structured dictionaries for
  domain artifacts.
- Use `snake_case` for modules, functions, and variables; `PascalCase` for
  classes; and `UPPER_SNAKE_CASE` for constants. Prefer small modules with clear
  responsibilities over generic frameworks.
- Manage dependencies in `pyproject.toml` with uv and commit `uv.lock` once
  dependency management is introduced. Use `uv run` for project commands.
- Keep prompts versioned and separate from orchestration logic. Validate model
  outputs before consuming them or writing state.
- Pass configuration explicitly. Load credentials from environment variables;
  never commit secrets or include them in logs and traces.
- Keep inference, network, and database calls behind injectable interfaces so
  unit tests can run without remote providers, GPUs, or live databases.
- Use structured failure categories and actionable critique evidence. Treat
  critic scores as estimates requiring calibration, not measured probabilities.
- Bound generation and revision attempts with explicit stop conditions and
  budgets. Surface exhausted retries and partial results without marking them
  accepted.
- Panel revision policy: allow at most `max_panel_attempts` (default 3: one
  initial attempt plus two retries) per panel, plus a hard per-chapter budget
  (spend or image count). Route retries by failure category: rendering issues
  (e.g. composition, style drift) retry generation; script mismatches or missing
  characters go back to the Visual Director once. Stop early when the same
  failure repeats. Keep the highest-scored attempt, not the last; when limits
  are exhausted, surface it as not accepted. Keep both limits in configuration.
- Record enough provenance to inspect a run: artifact IDs, model and prompt
  versions, conditioning references, attempts, critique, timing, and available
  cost data. Do not swallow errors or silently accept invalid output.
- Make changes focused on the requested scope. Avoid speculative abstractions,
  extra agent roles, and unrelated dependencies.

## Testing and evaluation

Use pytest for meaningful behavior checks. Prioritize schema validation, canon
protection, temporal queries, character-knowledge boundaries, revision routing,
retry limits, and acceptance/commit behavior.

Keep default tests deterministic and independent of paid inference. Mark
integration or GPU-dependent checks separately and document their prerequisites
when introduced. Run checks appropriate to each implementation change.

Establish a small fixed evaluation set early. Include a two-chapter continuity
scenario with recurring characters and a location, an outfit change, and a
secret known to only one character. Evaluate both isolated panels and the
assembled sequence. Compare critic judgments against human judgments.

Track canon violations, character identity, visual continuity, script alignment,
narrative coherence, first-pass acceptance, attempts per accepted panel, cost,
and human preference. README numerical targets are aspirational until measured.

## Current implementation state

Python 3.12+, uv, `src/` layout, Pydantic, pydantic-settings, LangGraph,
Pillow, Streamlit, and pytest. Run tests with `uv run pytest` and the UI with
`uv run streamlit run src/comartist/app.py`. No formatter, linter, or CI
workflow is configured yet.

Layout of `src/comartist/`:

- `agents/`: Story Architect, Script Writer, Visual Director, Critic (script
  and panel modes), Chapter Judge.
- `prompts/`: versioned prompts, one module per agent or mode.
- `workflows/`: `script_loop.py` and `panel_loop.py` are LangGraph loops with
  bounded attempts and failure-category routing. `stub_pipeline.py` runs the
  chapter stages in sequence (real or stubbed per stage), plus resume and
  single-panel regeneration. `store.py` writes one run folder per chapter.
- `tools/`: acceptance boundary (`canon.py`), character sheets, lettering with
  tailed speech bubbles, page templates, continuity checks.
- `memory/continuity.py`: carries accepted canon and approved looks into the
  next chapter with story time attached.
- `adapters/`: model access through an OpenAI-compatible adapter (Responses or
  Chat Completions), a fallback wrapper, and a fake adapter for tests.
- `config.py`: providers. Meta Model API (Muse Wonder text, Muse Image) is the
  primary; Fireworks (Llama, FLUX) is the fallback. FLUX takes no reference
  images, so fallback panels lose character conditioning.

Live smoke and probe scripts live in `scripts/`; their outputs go to the
git-ignored `smoke_results/`.

Known gaps and debt:

- Canon and runs are stored as JSON on disk (`runs/canon.json`). PostgreSQL,
  Qdrant, and the temporal "who knows what, when" model are not implemented.
- The chapter-level pipeline is not a LangGraph graph, and `stub_pipeline.py`
  is misnamed: it runs real stages. Its docstring is out of date.
- Several `scripts/fix_*.py` and `resume_from_visual_director.py` are one-off
  manual repairs from the demo. They should become judge-driven repair and
  resume features.
- LiteLLM and vLLM are not used. Visual consistency relies on reference sheets
  and prompting; LoRA, IP-Adapter, and ControlNet are untried.
- No Docker packaging and no frozen evaluation baseline.

The phases below are the original plan. Phases 1–4 are implemented in a first
form (see the gaps above); phases 5–7 remain.

1. **Typed foundations and evaluation fixtures:** Define domain schemas,
   candidate versus accepted state, minimal canon and temporal interfaces,
   failure categories, run traces, and a small continuity evaluation set.
2. **Narrative MVP:** Implement Story Architect, Script Writer, and the Critic's
   script mode in LangGraph with typed outputs and bounded revisions. Expose
   brief entry, script review, and workflow status in a basic Streamlit UI.
   Use minimal local or in-memory service implementations where sufficient.
3. **Visual production:** Implement Visual Director and panel specifications;
   add image-generation adapters and approved reference conditioning. Integrate
   Diffusers and add LoRA, IP-Adapter, or ControlNet as experiments justify them.
   Implement deterministic lettering, layout, and export services.
4. **Visual critique and chapter acceptance:** Add multimodal Critic evaluation,
   targeted repair routing, and Chapter Judge evaluation of assembled chapters.
   Persist attempts and evaluation evidence; enforce explicit acceptance before
   canon updates.
5. **Persistent long-term memory:** Implement PostgreSQL canonical persistence,
   Qdrant retrieval, temporal queries, and visual-reference storage interfaces.
   Preserve the canon and knowledge rules established in the first phase.
6. **End-to-end validation and packaging:** Prove continuity across two short
   chapters, measure quality and cost, and package required services with Docker.
   Expand chapter length and autonomy only after the smaller workflow is reliable.
7. **Later research:** Curate traces with human evaluation for offline critic,
   conditioning, or generation-policy improvements. Test changes against a
   frozen evaluation set before adoption; do not continuously train on every
   generated artifact.

When implementation is requested, start with the smallest verifiable slice of
the applicable phase. Update this guidance when an architectural decision or
implemented milestone changes the project direction.
