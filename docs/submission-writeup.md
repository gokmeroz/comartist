# ComArtist: submission writeup (draft)

**Tagline:** Turn a short story brief into a lettered comic chapter, with characters who stay themselves from one chapter to the next.

**Track:** Indie developer · **Theme:** Build for Your World

## Inspiration

Image models can draw a striking panel. A comic asks for something harder: the same people, in the right clothes, in the right place, knowing only what they should know, panel after panel. I wanted to find out if a team of AI agents could hold a story together rather than just illustrate one prompt.

## What it does

You write a short chapter brief with characters, a premise, and canon facts. ComArtist turns it into a lettered comic chapter:

1. **Story Architect** shapes the events and page beats.
2. **Script Writer** produces panels, dialogue, and captions, and the **Critic** can send the script back for revision.
3. **Visual Director** plans framing, poses, and character placement.
4. **Muse Image** generates each panel from approved character references.
5. The **Critic** reviews each panel against the script and references, and failures trigger a targeted retry.
6. Lettering and layout code adds speech bubbles and builds the pages.
7. The **Chapter Judge** reviews the assembled chapter as a sequence.
8. A human decides whether to accept it. Only then can its facts become canon for the next chapter.

## How I built it

ComArtist is written in Python, with Pydantic models at every boundary. Muse Wonder handles the reasoning and critique, and Muse Image generates the panels, both through the Meta Model API. LangGraph runs the script and panel revision loops, with limits on attempts and a spend budget per chapter. Each panel gets up to three attempts, and the best one is kept.

Streamlit is a thin interface over the pipeline. It shows live stage status, critiques, panel attempts, cost, single-panel regeneration, resume, and chapter acceptance. Tests run in GitHub Actions on a stub model, so they need no paid inference.

## Does it work?

I tested it on a fixed two-chapter story about Matt and Andy in New York City, where Andy holds a secret.

| Chapter | Panels | Pages | Panel attempts | Judge score (uncalibrated) | Status |
|---|---:|---:|---:|---:|---|
| 1: The Reunion | 16 | 4 | 24 | 0.92 | Accepted |
| 2: The Rooftop | 19 | 4 | 29 | 0.95 | Accepted |

An automated continuity check passes 12 of 12 checks. Both characters keep their locked looks and reference images, both change outfits as the briefs require, the setting holds, and Andy's secret never appears in any dialogue or caption.

This is one evaluation pair, so it shows the system working, not a general success rate. Some panels needed manual regeneration or a resume after errors.

I also used it on my own sci-fi story, planned as ten chapters:

| Chapter | Panels | Pages | Judge score (uncalibrated) | Status |
|---|---:|---:|---:|---|
| 1: The Journey Begins | 48 | 12 | 0.82 | Accepted |
| 2: Welcome to 2016 | 20 | 4 | 0.92 | Judge approved, not accepted |

Chapter 1 was first scored 0.45. The Judge's issues pointed at specific panels and one missing story beat, and after targeted redraws and a small script edit that added the missing beat, it approved the chapter. It cost $10.03. Chapter 2 carries over chapter 1's canon, locked faces, and approved references, with new outfits. The Judge approved it, but 4 of its 20 panels never passed the Critic, so the acceptance rule still blocks it. An 8-page version of chapter 2 failed twice, because the API dropped the larger requests.

## Challenges

- **Continuity inside a scene, not only across chapters.** One panel lost the rainy night and had to be redrawn with an explicit note.
- **The Critic running out of tokens.** Hidden reasoning counts against the limit, so busy panels hit a 4,000-token cap and failed on every attempt until it was raised.
- **Failures in long runs.** Network errors and content filters can stop a chapter partway, so runs now resume while keeping finished panels.
- **Large requests getting dropped.** The API kept closing the connection on the biggest calls: the Chapter Judge reading 12 pages, and the Script Writer and Visual Director planning 8 pages. Small requests still worked. Retrying just the failed stage, and keeping chapters to about 4 pages, got runs through.
- **Content filters on harmless scenes.** Some panels were refused repeatedly, such as a character hanging upside down from a portal. Rewording the action in neutral terms fixed some, but not all.
- **Lettering.** Bubble order, tails pointing at the right speaker, and tails crossing other bubbles all needed fixes. Text is drawn by code rather than by the image model.

## What I'm proud of

- A generated image is never automatically accepted. Every panel is a candidate that has to pass review.
- Failed drafts can't reach canon, because canon only changes after a human accepts a chapter.
- The continuity result comes from an automated check on a fixed scenario, not from eyeballing the output.

## What I learned

Consistency is a systems problem more than a prompting problem. Locked references, typed state, routed retries, and an explicit acceptance step did more than any single clever prompt. I also learned to treat critic scores as estimates, not measurements.

## What's next

- Generating panels in parallel. They run one at a time today, so an 8-page chapter takes about an hour.
- Splitting large requests into smaller ones, so the Judge and planners stop hitting the API's limits.
- A human approval step for the script before panels are generated.
- Persistent long-term memory with PostgreSQL and Qdrant, and proper temporal memory for flashbacks.
- Comparing critic judgments against human judgments to calibrate the scores.
- Longer stories, once two-chapter runs are reliable.

## Built with

Python, Pydantic, LangGraph, Streamlit, Pillow, pytest, uv, Meta Model API, Muse Wonder, Muse Image
