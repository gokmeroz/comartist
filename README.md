# 🎨 ComArtist

> Built for the **[Meta Global AI Developer Hackathon](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/details)**
> (Meta × Cerebral Valley, remote, Oct 26 – Nov 4, 2026).
> Track: **Indie developer** · Theme: **Build for Your World**.

**ComArtist turns a short story brief into a finished, lettered comic chapter, and keeps characters consistent from one chapter to the next.**

Five Meta-powered agents plan, write, direct, and critique each chapter. A generated panel is only a candidate: the Critic checks it against the script and references, sends failures back for a targeted retry, and a Chapter Judge reviews the assembled pages. Nothing enters canon until a human accepts the chapter.

## ✅ What it has produced

The fixed two-chapter evaluation in [`evals/continuity/`](evals/continuity/) ran on Muse Wonder and Muse Image:

| Chapter | Panels | Pages | Panel attempts | Judge score* | Status |
|---|---:|---:|---:|---:|---|
| 1: The Reunion | 16 | 4 | 24 | 0.92 | Human accepted |
| 2: The Rooftop | 19 | 4 | 29 | 0.95 | Human accepted |

The automated continuity check [`scripts/check_continuity.py`](scripts/check_continuity.py) passes **12 of 12** checks across the two chapters:

- Matt and Andy keep the same locked appearance and approved reference images.
- Both characters change outfits between chapters, as the briefs require.
- The New York City setting holds.
- Andy's secret never appears in any dialogue or caption.

<sub>*Judge scores are uncalibrated model estimates, not measured quality. Results come from one evaluation pair, so this shows the system working, not a general success rate. Some panels were manually regenerated or resumed after errors during these runs.</sub>

## ⚙️ How it works

```mermaid
flowchart TD
    B["Brief + carried-over canon"] --> A["Story Architect"]
    A --> W["Script Writer"]
    W <-->|"bounded revisions"| C1["Critic: script mode"]
    C1 --> V["Visual Director"]
    V --> P["Muse Image panel generation"]
    P <-->|"retry by failure category"| C2["Critic: visual mode"]
    C2 --> L["Lettering + page layout"]
    L --> J["Chapter Judge"]
    J --> H["Human acceptance"]
    H --> K["Canon ledger + next chapter"]
```

- **Agents:** Story Architect, Script Writer, Visual Director, Critic, and Chapter Judge return validated, typed results.
- **Revision loops:** the script and panel loops are LangGraph graphs with attempt limits. Each panel gets up to 3 attempts, each chapter has a spend budget, and the best attempt is kept.
- **Continuity:** approved reference sheets, locked character looks, and accepted facts carry into the next chapter.
- **Lettering:** deterministic code draws tailed speech bubbles and page layouts instead of asking the image model to render text.
- **Streamlit UI:** brief entry, live stage status and logs, script critique, attempt viewer, cost tracking, single-panel regeneration, resume, and chapter acceptance.
- **Provenance:** every run stores its attempts, critiques, prompt versions, tokens, and cost.

### Built vs. planned

| Built and used in the runs above | Not built yet |
|---|---|
| Meta Model API adapter, stub adapter for offline runs | Working Fireworks and Modal adapters (listed in the UI only) |
| Local file storage for runs and a canon ledger | PostgreSQL persistence |
| Canon and outfit carry-over between chapters | Qdrant semantic retrieval, full temporal memory |
| Reference-image conditioning through Muse Image | LoRA, IP-Adapter, ControlNet, SAM segmentation |
| Human chapter acceptance | Human approval step for the script before panels |

## 🚀 Run it

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run pytest
uv run streamlit run src/comartist/app.py
```

The stub provider runs the whole UI offline with simulated output. For real generation, set `COMARTIST_META_API_KEY` in your environment or `.env`, and pick the Meta provider in the sidebar.

To reproduce the two-chapter evaluation (costs real credits, about $5):

```sh
uv run python scripts/run_continuity_demo.py
uv run python scripts/check_continuity.py <chapter-1-run-id> <chapter-2-run-id>
```

## 🏁 Hackathon Context

| | |
|---|---|
| Event | Meta Global AI Developer Hackathon (virtual, worldwide) |
| Build window | Oct 26, 2026 12:00 PM ET → Nov 4, 2026 9:00 PM ET |
| Submission deadline | **Nov 4, 2026, 9:00 PM ET** |
| Judging | Nov 4 – Nov 8 · Winners announced Nov 9 |
| Track | Indie developer — judged on creativity, technical ambition, and whether it works |
| Theme | Build for Your World — turn a personal story into a coherent comic chapter |

Judging criteria shape the scope: the submission must **work end to end** on a
short chapter, show **technical ambition** (multi-agent orchestration,
critique-driven revision, continuity memory), and be **creative** in output.
Breadth beyond that is deferred until after the deadline.

### Prior work disclosure

ComArtist began as a concept before the hackathon. Before Oct 26, 2026 the
repository contained a project README, an empty package layout, three Pydantic
data models (chapter, character, state), a minimal Streamlit input page, and one
test file. No agents, model integrations, image generation, or continuity checks
existed. Everything else was built during the hackathon (Oct 26 – Nov 4, 2026).

The pre-hackathon snapshot is tagged
[`pre-hackathon`](https://github.com/gokmeroz/comartist/tree/pre-hackathon);
see the [full diff of hackathon work](https://github.com/gokmeroz/comartist/compare/pre-hackathon...main).

## 🎬 Concept teaser

![ComArtist teaser: a brief becomes a comic chapter, with a Critic that catches continuity errors](docs/media/comartist-teaser.gif)

▶ **[Full-quality version with sound (mp4)](docs/media/comartist-teaser.mp4)**

> This teaser predates the working pipeline. Its comic scenes, including the "mistaken" attempts, are sample art in our target style, were not generated by ComArtist, and are labeled in the video as a concept mockup. It does not show the results above.

---

# 🔭 Long-term vision

**Everything below is the original design and research direction, not a description of the current system.** It includes ideas that were later changed or have not been built, such as additional agent roles, long-term memory, and learning loops. For what exists today, see [What it has produced](#-what-it-has-produced) and [Built vs. planned](#built-vs-planned).

> **An autonomous multi-agent system that turns ideas into coherent, evolving comic chapters.**

ComArtist is an experimental **Agentic AI comic-production system** designed to transform a simple story idea into a complete comic chapter.

Instead of treating comic generation as:

```text
Prompt → Image
```

ComArtist treats it as a long-running creative workflow:

```text
Idea → Memory Retrieval → Story → Script → Visual Direction
     → Panel Generation → Critique → Revision → Comic Chapter
```

The goal is not simply to generate attractive images.

The goal is to build an AI system capable of maintaining **characters, relationships, story continuity, visual identity, world state, and narrative history across potentially hundreds of chapters.**

---

# 💡 Why ComArtist?

Current generative models can already produce:

- stories
- dialogue
- illustrations
- comic-style images

But generating **one image** is very different from maintaining a coherent comic universe.

A long-running comic introduces problems such as:

- Does the character still look like the same person 40 panels later?
- Does their personality remain consistent?
- Does the system remember something that happened 20 chapters ago?
- Does a character know information they have not learned yet?
- Is someone wearing the correct clothes after changing outfits?
- Does a location remain visually recognizable?
- Does the generated panel actually match the script?
- Can the system detect its own mistakes and repair them?

ComArtist explores these problems using **multi-agent orchestration, multimodal generation, persistent memory, RAG, visual conditioning, automated evaluation, and iterative self-correction.**

---

# 🧠 Core Idea

The user should not have to write an entire screenplay.

A chapter could start with something as simple as:

```yaml
timeframe: Summer 2024
location: New York City

characters:
  - Matt
  - Andy

canon:
  - Andy moved to NYC in 2020.
  - Matt and Andy have not met since middle school.
  - Matt is in the United States for Work & Travel.
  - They meet near NYU.
  - They go to a pub where Harry Potter is playing.
  - They spend the evening catching up about their lives.

tone:
  - nostalgic
  - funny
  - grounded
  - bittersweet

target_pages: 18
```

ComArtist should determine the rest.

For example:

- Where exactly should the chapter begin?
- Who arrives first?
- How awkward is the reunion?
- What memories naturally come up?
- When should the conversation become serious?
- How should the visual framing change?
- What should the final emotional beat be?

The user provides **truth and intent**.

The agents provide **creative execution**.

---

# 🏗️ System Architecture

```mermaid
flowchart TD

    USER["💡 Chapter Brief"]

    USER --> MEMORY

    subgraph MEMORY["🧠 Memory System"]
        CANON["Canonical State"]
        RAG["Semantic / RAG Memory"]
        TIMELINE["Temporal Memory"]
        VISUAL["Visual References"]
    end

    MEMORY --> ARCHITECT

    subgraph STORY["✍️ Narrative Pipeline"]
        ARCHITECT["Story Architect"]
        PLOT["Plot Agent"]
        WRITER["Script Writer"]
        SCRIPTCRITIC["Script Critic"]

        ARCHITECT --> PLOT
        PLOT --> WRITER
        WRITER --> SCRIPTCRITIC
        SCRIPTCRITIC -->|Revise| WRITER
    end

    SCRIPTCRITIC -->|Approved| DIRECTOR

    subgraph VISUALPIPE["🎬 Visual Pipeline"]
        DIRECTOR["Visual Director"]
        PROMPT["Panel Prompt Compiler"]
        GENERATOR["Image Generation"]
        VLM["Vision Critic"]

        DIRECTOR --> PROMPT
        PROMPT --> GENERATOR
        GENERATOR --> VLM
        VLM -->|Regenerate| PROMPT
    end

    VLM -->|Approved| LAYOUT

    subgraph FINAL["📖 Publishing Pipeline"]
        LAYOUT["Lettering & Layout"]
        JUDGE["Chapter Judge"]
        EXPORT["Comic Chapter"]

        LAYOUT --> JUDGE
        JUDGE --> EXPORT
        JUDGE -->|Revision Required| STORY
    end
```

---

# 🤖 Agent System

ComArtist is designed around specialized agents rather than one giant prompt.

### Story Architect

Transforms the user's chapter idea into a dramatic structure while respecting existing canon.

### Plot Agent

Creates the sequence of events, emotional progression, pacing, and page-level beats.

### Script Writer

Produces:

- panel descriptions
- dialogue
- captions
- actions
- expressions
- scene transitions

### Script Critic

Evaluates:

- pacing
- dialogue
- characterization
- continuity
- contradictions
- narrative quality

Failed scripts enter a:

```text
Writer → Critic → Revision → Critic
```

loop.

### Lore / Continuity Agent

Tracks the evolving universe:

```text
characters
relationships
locations
events
knowledge
objects
injuries
outfits
timeline
world rules
```

### Visual Director

Converts narrative instructions into visual direction:

- framing
- composition
- camera angle
- pose
- lighting
- emotion
- character placement
- environmental context

### Panel Generator

Produces panels using diffusion / image-generation models with visual conditioning.

### Vision Critic

Uses a multimodal model to evaluate generated panels.

Example evaluation:

```json
{
  "character_identity": 0.94,
  "outfit_consistency": 0.97,
  "pose_accuracy": 0.82,
  "script_alignment": 0.91,
  "environment_consistency": 0.88,
  "visual_quality": 0.90,
  "requires_regeneration": false
}
```

### Chapter Judge

Evaluates the complete chapter rather than isolated panels.

It checks whether the final result works as a **sequential narrative**.

---

# 🔁 Self-Correction

A core principle of ComArtist is:

> **Generation is not completion. Generation is a candidate.**

```mermaid
flowchart LR

    A["Generate"] --> B["Evaluate"]
    B --> C{"Pass?"}

    C -->|Yes| D["Accept"]
    C -->|No| E["Critique"]

    E --> F["Modify Strategy"]
    F --> A

    D --> G["Store Trace"]
```

Instead of blindly regenerating panels, ComArtist should understand **why** something failed.

Examples:

```text
WRONG_CHARACTER_IDENTITY
WRONG_OUTFIT
POSE_MISMATCH
MISSING_CHARACTER
MISSING_OBJECT
CONTINUITY_VIOLATION
STYLE_DRIFT
SCRIPT_MISMATCH
DIALOGUE_ERROR
BAD_COMPOSITION
```

Those failures become valuable data for improving the system later.

---

# 🧠 Long-Term Memory

ComArtist is intended to support stories that evolve over **years and potentially hundreds of chapters**.

That requires more than ordinary conversation history.

The memory architecture separates different kinds of knowledge.

```mermaid
flowchart TD

    CURRENT["Current Chapter"]

    CURRENT --> STRUCTURED
    CURRENT --> VECTOR
    CURRENT --> TEMPORAL
    CURRENT --> VISUAL

    STRUCTURED["Structured Memory
    Characters
    Relationships
    World State"]

    VECTOR["Semantic Memory
    Previous Scenes
    Conversations
    Lore"]

    TEMPORAL["Temporal Memory
    Events
    Changes
    Timeline"]

    VISUAL["Visual Memory
    Character References
    Locations
    Previous Panels"]
```

For example:

```text
2020
Andy moves to New York City.

2024
Matt visits the United States through Work & Travel.

Summer 2024
Matt and Andy meet again for the first time since middle school.
```

If ComArtist later generates a flashback set in **2019**, it must understand that:

```text
Andy has NOT moved to NYC yet.
```

Long-term memory therefore needs to represent not only:

> **What is true?**

but:

> **When was it true?**

---

# 🧩 Canon vs Creativity

ComArtist separates information into three categories.

### Canon

Facts established by the user or previously accepted chapters.

```text
Andy moved to NYC in 2020.
```

Agents cannot silently modify canon.

### Derived Information

Reasonable conclusions based on existing canon.

```text
Andy probably knows NYC better than Matt.
```

### Ephemeral Fiction

Scene-level details the agents are free to invent.

```text
Andy jokes that Matt still orders the same drink he liked years ago.
```

This distinction allows agents to be creative without hallucinating permanent facts about the story universe.

---

# 🧬 Learning & Improvement

ComArtist does **not** continuously retrain itself on everything it generates.

Instead:

```mermaid
flowchart TD

    GENERATE["Generate Chapters"]
    TRACE["Store Generation Traces"]
    LABEL["Critic + Human Evaluation"]
    DATASET["Curated ComArtist Dataset"]
    TRAIN["Offline Training / Fine-Tuning"]
    TEST["Frozen Evaluation Set"]
    DECISION{"Improved?"}
    DEPLOY["Deploy New Version"]
    REJECT["Reject Update"]

    GENERATE --> TRACE
    TRACE --> LABEL
    LABEL --> DATASET
    DATASET --> TRAIN
    TRAIN --> TEST
    TEST --> DECISION

    DECISION -->|Yes| DEPLOY
    DECISION -->|No| REJECT
```

Generation traces can eventually provide training examples containing:

```text
story context
+
character references
+
panel specification
+
generated image
+
critic evaluation
+
failure reason
+
revised generation
+
human preference
```

This creates a domain-specific dataset for improving:

- visual critics
- character consistency
- generation policies
- story evaluators
- prompt compilation
- LoRA adapters

---

# 🗃️ Example State

```text
ComicState
│
├── Series
│   ├── title
│   ├── premise
│   ├── genre
│   └── world_rules
│
├── Characters
│   ├── identity
│   ├── appearance
│   ├── personality
│   ├── relationships
│   └── visual_references
│
├── Timeline
│
├── Chapters
│   ├── chapter_001
│   ├── chapter_002
│   └── ...
│
├── CurrentChapter
│   ├── beats
│   ├── pages
│   └── panels
│
└── GenerationHistory
    ├── attempts
    ├── critiques
    ├── scores
    └── revisions
```

---

# 🛠️ Planned Tech Stack

### Core

```text
Python
Pydantic
PyTorch
```

### Agentic AI

```text
LangGraph
LangChain
LiteLLM
LangSmith
```

### Hugging Face

```text
Transformers
Diffusers
PEFT
Accelerate
Datasets
Hugging Face Hub
```

### Visual Consistency

```text
LoRA
IP-Adapter
ControlNet
Vision-Language Models
```

### Memory

```text
PostgreSQL
Qdrant
Embeddings
RAG
Temporal Memory
```

### Model Serving

```text
Meta Model API (Muse Spark, Muse Wonder, Muse Image, SAM 3.1)
Fireworks / Modal / Baseten (Meta open-weights models)
vLLM (local fallback)
```

### Interface

```text
Streamlit
```

### Infrastructure

```text
Docker
Docker Compose
GitHub Actions
pytest
```

---

# 🖥️ UI Philosophy

The interface is intentionally simple.

ComArtist is primarily an **AI systems project**, not a frontend project.

```text
┌──────────────────────────────────────────────┐
│                  ComArtist                   │
├──────────────────────────────────────────────┤
│                                              │
│  What happens in this chapter?               │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │ Summer 2024. Matt meets his old...    │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  Characters: Matt, Andy                      │
│  Target pages: 18                            │
│                                              │
│           [ Generate Chapter ]               │
│                                              │
├──────────────────────────────────────────────┤
│ Pipeline                                     │
│                                              │
│ ✓ Memory Retrieval                           │
│ ✓ Story Architect                            │
│ ✓ Plot Agent                                 │
│ ✓ Script Writer                              │
│ ↻ Script Critic                              │
│ ○ Visual Director                            │
│ ○ Panel Generator                            │
│ ○ Vision Critic                              │
│ ○ Chapter Judge                              │
└──────────────────────────────────────────────┘
```

Streamlit is sufficient for exposing:

- story input
- character management
- pipeline status
- generated pages
- critic scores
- agent traces
- regeneration history
- cost metrics

---

# 📊 Evaluation

ComArtist should be measurable.

Possible metrics include:

| Metric | Description |
|---|---|
| Character Identity | Does the character remain recognizable? |
| Visual Continuity | Are appearance and environment consistent? |
| Script Alignment | Does the panel depict what the script requested? |
| Narrative Coherence | Does the chapter make sense sequentially? |
| Canon Violations | How often does the system contradict established facts? |
| First-Pass Success | Percentage of panels accepted without regeneration |
| Regeneration Rate | Average attempts required per accepted panel |
| Cost / Panel | Average generation cost |
| Cost / Chapter | Total inference cost |
| Human Preference | Human evaluation of final output |

An eventual target could look like:

```text
20-page chapter
~100 final panels

Character consistency     ≥ 90%
Script alignment          ≥ 90%
Narrative coherence       ≥ 90%
Canon violations          < 2%
Average generations       ≤ 2.5 / panel
Target chapter cost       ≤ $15
```

---

# 🧪 Research Questions

ComArtist explores questions including:

### Can an agentic system maintain character identity across long visual sequences?

### Can multimodal agents identify and repair their own continuity errors?

### How should long-term narrative memory be represented?

### Can structured memory and RAG complement each other for fictional universes?

### Can generation policies learn which conditioning strategies work best for different scenes?

### How much autonomous revision is necessary before additional inference cost stops improving quality?

### Can a system maintain coherent canon across 100+ chapters?

---

# ⏱️ Hackathon Plan (Oct 26 – Nov 4)

| Days | Goal |
|---|---|
| Oct 26–27 | Meta Model API adapter + stub (Meta credits received), typed schemas, evaluation fixture |
| Oct 28–30 | Narrative MVP: Story Architect → Script Writer ⇄ Critic in LangGraph |
| Oct 31–Nov 2 | Visual Director, panel generation (Muse Image), visual Critic with bounded revision |
| Nov 3 | Lettering/layout, Chapter Judge, Streamlit demo of a full short chapter |
| Nov 4 | Freeze, record demo, write submission — **due 9:00 PM ET** |

The roadmap below is the longer-term plan beyond the hackathon.

# 🗺️ Development Roadmap

```mermaid
flowchart LR

    V01["v0.1
    Story Pipeline"]

    V02["v0.2
    Panel Generation"]

    V03["v0.3
    Visual Critic"]

    V04["v0.4
    Character Memory"]

    V05["v0.5
    RAG + Timeline"]

    V06["v0.6
    Self-Correction"]

    V07["v0.7
    Evaluation Suite"]

    V10["v1.0
    Autonomous Chapter"]

    V01 --> V02 --> V03 --> V04 --> V05 --> V06 --> V07 --> V10
```

### Phase 1 — Narrative MVP

- [ ] Define `ComicState`
- [ ] Story Architect
- [ ] Plot Agent
- [ ] Script Writer
- [ ] Script Critic
- [ ] LangGraph orchestration
- [ ] Basic Streamlit UI

### Phase 2 — Visual Generation

- [ ] Panel specification schema
- [ ] Visual Director
- [ ] Diffusers integration
- [ ] Character reference conditioning
- [ ] Panel generation

### Phase 3 — Evaluation

- [ ] VLM Critic
- [ ] Failure taxonomy
- [ ] Panel scoring
- [ ] Automated regeneration
- [ ] Generation traces

### Phase 4 — Memory

- [ ] Character memory
- [ ] World-state database
- [ ] Qdrant RAG
- [ ] Temporal memory
- [ ] Visual memory
- [ ] Canon validation

### Phase 5 — Learning

- [ ] ComArtistBench
- [ ] Human evaluation pipeline
- [ ] Critic fine-tuning
- [ ] Character LoRA training
- [ ] Generation-policy optimization
- [ ] Regression evaluation

### Phase 6 — Full Chapter Generation

```text
One Idea
   ↓
Zero Manual Intervention
   ↓
Complete Comic Chapter
   ↓
Evaluation Report + Generation Trace
```

---

# 🎯 Long-Term Goal

The long-term vision is simple:

> Give ComArtist a few sentences about something that happened — or something that should happen — and receive a complete comic chapter that understands everything that came before it.

After dozens or hundreds of chapters, the system should understand:

- who the characters are
- what they look like
- how they speak
- how their relationships changed
- where they have been
- what they know
- what they have experienced
- how the world evolved

without requiring the entire history to be manually explained again.

---

# ⚠️ Status

> 🚧 **Early Research / Development**

ComArtist is currently being designed and implemented.

The initial focus is not maximum image quality.

The initial focus is proving that a multi-agent architecture can reliably coordinate:

```text
Memory
+
Narrative Planning
+
Visual Generation
+
Evaluation
+
Self-Correction
```

across an entire sequential comic chapter.

---

# 📜 License

License TBD.

---

<p align="center">
  <strong>ComArtist</strong><br>
  Turning ideas into evolving comic worlds.
</p>
