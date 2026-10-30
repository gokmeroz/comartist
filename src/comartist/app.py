"""Streamlit viewer: new chapter briefs, pipeline status, full runs, and the overview."""

import html
import threading
from pathlib import Path

import pandas as pd
import streamlit as st

from comartist.adapters import ModelError, build_image_model, build_text_model
from comartist.agents.critic import Critic
from comartist.agents.script_writer import ScriptWriter
from comartist.agents.story_architect import StoryArchitect
from comartist.agents.visual_director import VisualDirector
from comartist.config import PROVIDERS, Settings
from comartist.models import (
    ChapterRun,
    Cost,
    PanelResult,
    RunSettings,
    RunState,
    Stage,
    StageState,
)
from comartist.ui.theme import apply_theme, cost_hud, pixel_bar
from comartist.workflows.store import BriefError, RunStore, chapter_template, parse_brief
from comartist.tools.character_sheets import approve_sheet, generate_sheet
from comartist.workflows.panel_loop import PanelLoop, data_url
from comartist.workflows.script_loop import ScriptLoop
from comartist.workflows.stub_pipeline import run_stub_pipeline

STAGE_ICONS = {
    StageState.PENDING: "·",
    StageState.RUNNING: "⏳",
    StageState.DONE: "✅",
    StageState.FAILED: "❌",
}
STAGE_SHORT = {
    Stage.STORY_ARCHITECT: "Story",
    Stage.SCRIPT: "Script",
    Stage.VISUAL_DIRECTOR: "Visuals",
    Stage.PANELS: "Panels",
    Stage.LAYOUT: "Layout",
    Stage.CHAPTER_JUDGE: "Judge",
}
RUN_LABELS = {
    RunState.NOT_STARTED: "○ not started",
    RunState.RUNNING: "⏳ running",
    RunState.DONE: "✅ done",
    RunState.FAILED: "❌ failed",
    RunState.BUDGET_EXHAUSTED: "💸 budget exhausted",
}


@st.cache_resource
def get_store() -> RunStore:
    return RunStore(Settings().runs_dir)


def fmt_usd(cost: Cost) -> str:
    return "n/a" if cost.usd is None else f"${cost.usd:,.2f}"


def render_sidebar() -> RunSettings:
    st.sidebar.header("Compute")
    provider_id = st.sidebar.radio(
        "Model provider",
        list(PROVIDERS),
        format_func=lambda key: PROVIDERS[key].label,
        key="provider",
    )
    provider = PROVIDERS[provider_id]
    if provider.note:
        st.sidebar.caption(provider.note)
    if provider.api_key_env:
        if provider.key_present():
            st.sidebar.success(f"`{provider.api_key_env}` is set")
        else:
            st.sidebar.warning(f"Set `{provider.api_key_env}` in your environment")
    if not provider.implemented:
        st.sidebar.info("Adapter not wired yet. Runs use the stub for now.")
    text_model = st.sidebar.selectbox("Text model (agents + critic)", provider.text_models)
    image_model = st.sidebar.selectbox("Image model (panels)", provider.image_models)

    st.sidebar.header("Budget")
    max_attempts = st.sidebar.number_input(
        "Max attempts per panel", min_value=1, max_value=10, value=3,
        help="1 initial try + retries. Lower it while developing to save credits.",
    )
    max_script_attempts = st.sidebar.number_input("Max drafts per script", min_value=1, max_value=10, value=3)
    budget = st.sidebar.number_input(
        "Chapter budget (USD)", min_value=0.5, max_value=150.0, value=5.0, step=0.5,
        help="Hard cap per run. When it runs out, the best attempts so far are shown, not accepted.",
        key="budget_usd",
    )
    return RunSettings(
        provider=provider_id,
        text_model=text_model,
        image_model=image_model,
        max_script_attempts=int(max_script_attempts),
        max_panel_attempts=int(max_attempts),
        chapter_budget_usd=float(budget),
    )


@st.fragment(run_every=2)
def render_cost_header() -> None:
    runs = get_store().list()
    total = Cost()
    for run in runs:
        total = total.add(run.cost)
    selected = st.session_state.get("selected_chapter")
    current = next((run.cost for run in runs if run.chapter_id == selected), Cost())
    budget = float(st.session_state.get("budget_usd", 5.0))
    st.markdown(
        cost_hud(
            [
                ("Chapter", fmt_usd(current), f"{current.total_tokens:,} tok"),
                ("All runs", fmt_usd(total), f"{total.total_tokens:,} tok"),
            ],
            pixel_bar((current.usd or 0.0) / budget, f"of ${budget:,.2f}", blocks=16, warn_at=0.8),
        ),
        unsafe_allow_html=True,
    )


def render_pipeline_status(runs: list[ChapterRun]) -> None:
    st.subheader("Pipeline status")
    if not runs:
        st.info("No chapters yet. Start one below with ✚ New chapter.")
        return
    rows = []
    for run in runs:
        row: dict[str, str | int] = {"Chapter": run.spec.title, "Run": RUN_LABELS[run.state]}
        for stage in Stage:
            row[STAGE_SHORT[stage]] = STAGE_ICONS[run.stages[stage].state]
        row["Tokens"] = run.cost.total_tokens
        row["USD"] = fmt_usd(run.cost)
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_new_chapter() -> None:
    with st.expander("✚ New chapter", expanded=st.session_state.get("new_open", False)):
        st.caption("Fill in the template and save. A fresh template appears for every new chapter.")
        template = chapter_template()
        uploaded = st.file_uploader("…or upload a filled .yaml", type=["yaml", "yml"])
        version = st.session_state.get("template_version", 0)
        text = st.text_area(
            "Chapter brief (YAML)",
            value=uploaded.getvalue().decode() if uploaded else template,
            height=480,
            key=f"brief_{version}_{uploaded.name if uploaded else ''}",
        )
        try:
            spec = parse_brief(text)
        except BriefError as error:
            st.error(f"✗ {error}")
        else:
            st.success(f"✓ Valid brief: {spec.title} · {spec.target_pages} pages")
            st.markdown(character_chips(spec.characters), unsafe_allow_html=True)
        save, download, _ = st.columns([1, 1, 2])
        download.download_button("⬇ Template", template, file_name="new_chapter.yaml")
        if save.button("💾 Save chapter"):
            try:
                run = get_store().create(text)
            except BriefError as error:
                st.error(f"Brief not saved: {error}")
                return
            st.session_state.selected_chapter = run.chapter_id
            st.session_state.template_version = version + 1
            st.session_state.new_open = False
            st.rerun()


def start_run(chapter_id: str, settings: RunSettings) -> None:
    run_settings = settings
    if not PROVIDERS[settings.provider].implemented:
        run_settings = settings.model_copy(update={"provider": "stub", "text_model": "stub-text", "image_model": "stub-image"})
    story_architect = script_loop = visual_director = panel_loop = None
    if run_settings.provider != "stub":
        try:
            text_model = build_text_model(run_settings.provider, run_settings.text_model)
            story_architect = StoryArchitect(text_model)
            visual_director = VisualDirector(text_model)
            panel_loop = PanelLoop(
                build_image_model(run_settings.provider, run_settings.image_model),
                Critic(text_model),
                visual_director,
                run_settings.max_panel_attempts,
            )
            script_loop = ScriptLoop(ScriptWriter(text_model), Critic(text_model), run_settings.max_script_attempts)
        except ModelError as error:
            st.session_state.start_error = str(error)
            return
    threading.Thread(
        target=run_stub_pipeline,
        args=(get_store(), chapter_id, run_settings),
        kwargs={"story_architect": story_architect, "script_loop": script_loop, "visual_director": visual_director, "panel_loop": panel_loop},
        daemon=True,
    ).start()


def render_stage_cards(run: ChapterRun) -> None:
    cols = st.columns(len(Stage))
    for col, stage in zip(cols, Stage, strict=True):
        status = run.stages[stage]
        attempts = f"<br>attempts: {status.attempts}" if status.attempts else ""
        tokens = f"<br>{status.cost.total_tokens:,} tok" if status.cost.total_tokens else ""
        col.markdown(
            f'<div class="stage-card {status.state.value}">'
            f'<div class="name">{html.escape(stage.value)}</div>'
            f"{STAGE_ICONS[status.state]} {html.escape(status.detail)}{attempts}{tokens}</div>",
            unsafe_allow_html=True,
        )


@st.fragment(run_every=1)
def render_run_progress(chapter_id: str) -> None:
    run = get_store().load(chapter_id)
    st.markdown(f"**Run:** {RUN_LABELS[run.state]} · updated {run.updated:%H:%M:%S} UTC")
    if run.state is not RunState.NOT_STARTED:
        fraction, label = run_progress(run)
        st.markdown(pixel_bar(fraction, label), unsafe_allow_html=True)
    if run.error:
        st.error(run.error)
    render_stage_cards(run)
    if run.log:
        st.code("\n".join(run.log[-20:]), language="text")
    if run.state is RunState.DONE and st.session_state.get("refreshed") != run.updated:
        st.session_state.refreshed = run.updated
        st.rerun(scope="app")


def run_progress(run: ChapterRun) -> tuple[float, str]:
    """Stage-weighted progress; the Panels stage advances per generated panel."""
    done = sum(status.state is StageState.DONE for status in run.stages.values())
    fraction = done / len(Stage)
    current = next((stage for stage in Stage if run.stages[stage].state is StageState.RUNNING), None)
    if current is None:
        return fraction, "Done" if run.state is RunState.DONE else run.state.value
    if current is Stage.PANELS and run.panels:
        generated = sum(bool(panel.attempts) for panel in run.panels)
        fraction += generated / len(run.panels) / len(Stage)
        return fraction, f"⏳ Panels {generated}/{len(run.panels)}"
    return fraction, f"⏳ {current.value}"


def character_chips(names: list[str]) -> str:
    chips = "".join(f'<span class="chip">👤 {html.escape(name)}</span>' for name in names)
    return f'<div class="chips">{chips}</div>'


def render_full_run(run: ChapterRun, settings: RunSettings) -> None:
    st.markdown(character_chips(run.spec.characters), unsafe_allow_html=True)
    st.subheader("Run full pipeline")
    st.caption(" → ".join(stage.value for stage in Stage))
    running = run.state is RunState.RUNNING
    label = "⏳ RUNNING…" if running else "▶ RUN FULL PIPELINE"
    if st.button(label, key="run_full", disabled=running, width="stretch"):
        start_run(run.chapter_id, settings)
        st.rerun()
    if error := st.session_state.pop("start_error", None):
        st.error(f"Run not started: {error}")
    render_run_progress(run.chapter_id)


def render_overview(run: ChapterRun) -> None:
    st.subheader("Overview")
    if run.state is not RunState.DONE:
        st.caption("Appears when the run finishes.")
        return
    cost = run.cost
    panels = run.stages[Stage.PANELS]
    metrics = st.columns(4)
    metrics[0].metric("Cost", fmt_usd(cost))
    metrics[1].metric("Tokens", f"{cost.total_tokens:,}")
    metrics[2].metric("Images", cost.images)
    metrics[3].metric("Pages", run.spec.target_pages)

    spec = run.spec
    left, right = st.columns(2)
    with left:
        st.markdown(f"**{html.escape(spec.title)}** · {html.escape(spec.timeframe)} · {html.escape(spec.location)}")
        st.markdown(f"**Characters:** {', '.join(spec.characters)}")
        st.markdown(f"**Premise:** {spec.premise}")
        if spec.tone:
            st.markdown(f"**Tone:** {', '.join(spec.tone)}")
    with right:
        st.markdown("**Canon**")
        for fact in spec.canon:
            st.markdown(f"- {fact}")
        st.markdown(f"**Panels:** {panels.detail}")
    if run.settings:
        st.caption(
            f"Provider: {run.settings.provider} · text: {run.settings.text_model} · "
            f"image: {run.settings.image_model} · max {run.settings.max_panel_attempts} attempts/panel · "
            f"budget ${run.settings.chapter_budget_usd:.2f}"
        )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Stage": stage.value,
                    "Result": run.stages[stage].detail,
                    "Attempts": run.stages[stage].attempts,
                    "Prompt tok": run.stages[stage].cost.prompt_tokens,
                    "Completion tok": run.stages[stage].cost.completion_tokens,
                    "USD": fmt_usd(run.stages[stage].cost),
                }
                for stage in Stage
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    if run.settings and run.settings.provider == "stub":
        st.info("Stub run: outputs and token counts are simulated. No model was called.")
    elif run.outline:
        st.info("The Chapter Judge is simulated; earlier stages used real models.")
    if run.outline:
        render_outline(run)
    if run.script_critique:
        render_critique(run)
    if run.visual_plan:
        render_visual_plan(run)
    if run.pages:
        render_pages(run)
    elif run.panels:
        render_comic_preview(run.panels)
    if run.panels:
        render_attempt_viewer(run.panels)


def render_critique(run: ChapterRun) -> None:
    critique = run.script_critique
    st.subheader("Script critique")
    verdict = "Approved" if critique.approved else "Not approved"
    st.markdown(f"**{verdict}** · score {critique.score:.2f} (uncalibrated estimate)")
    for issue in critique.issues:
        where = issue.panel_id or "chapter"
        st.markdown(f"- **{issue.category}** ({where}): {issue.evidence} *Repair:* {issue.repair}")
    if version := run.prompt_versions.get(Stage.SCRIPT):
        st.caption(f"Prompts: {version}")


def render_reference_sheets(run: ChapterRun) -> None:
    st.markdown("**Character references**")
    st.caption("Generate a sheet, then approve it. Approval locks the look for every later run.")
    settings = run.settings
    columns = st.columns(len(run.visual_plan.looks))
    for column, look in zip(columns, run.visual_plan.looks):
        draft = run.reference_drafts.get(look.name)
        approved = run.spec.references.get(look.name)
        with column:
            st.markdown(f"**{look.name}**: {'✅ approved' if approved else 'not approved'}")
            if draft or approved:
                st.image(approved if approved and not draft else draft)
            if st.button("Generate sheet", key=f"sheet-{look.name}"):
                try:
                    model = build_image_model(settings.provider, settings.image_model)
                    generate_sheet(model, get_store(), run, look, run.visual_plan.style)
                except ModelError as error:
                    st.error(str(error))
                else:
                    st.rerun()
            if draft and draft != approved and st.button("Approve", key=f"approve-{look.name}"):
                approve_sheet(get_store(), run, look)
                st.rerun()


def render_visual_plan(run: ChapterRun) -> None:
    plan = run.visual_plan
    st.subheader("Visual plan")
    st.markdown(f"**Style:** {plan.style}")
    for look in plan.looks:
        st.markdown(f"- **{look.name}:** {look.appearance} Outfit: {look.outfit}")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Panel": panel.panel_id,
                    "Framing": panel.framing,
                    "Composition": panel.composition,
                    "Poses": panel.poses,
                    "Lighting": panel.lighting,
                    "Setting": panel.setting,
                    "References": ", ".join(panel.references),
                }
                for panel in plan.panels
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    render_reference_sheets(run)
    if version := run.prompt_versions.get(Stage.VISUAL_DIRECTOR):
        st.caption(f"Prompt: {version}")


def render_outline(run: ChapterRun) -> None:
    outline = run.outline
    st.subheader("Story outline")
    st.markdown(f"*{html.escape(outline.logline)}*")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Page": beat.page,
                    "What happens": beat.summary,
                    "Characters": ", ".join(beat.characters),
                    "Location": beat.location,
                    "Emotion": beat.emotion,
                    "Turn": beat.turn,
                }
                for beat in outline.beats
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    if outline.proposed_facts:
        st.markdown("**Proposed new facts** (candidates, not canon)")
        for fact in outline.proposed_facts:
            st.markdown(f"- {fact}")
    if version := run.prompt_versions.get(Stage.STORY_ARCHITECT):
        st.caption(f"Prompt: {version}")


def panel_html(panel: PanelResult) -> str:
    final = panel.attempts[-1] if panel.attempts else None
    badge = "✅" if panel.accepted else "❌"
    tries = f"{len(panel.attempts)} tr{'y' if len(panel.attempts) == 1 else 'ies'}"
    caption = f'<div class="caption">{html.escape(panel.caption)}</div>' if panel.caption else ""
    bubble = f'<div class="bubble">{html.escape(panel.dialogue)}</div>' if panel.dialogue else ""
    rejected = "" if panel.accepted or final is None else " rejected"
    if panel.best_image:
        art = f'<img src="{html.escape(data_url(panel.best_image))}" alt="{html.escape(panel.description)}" style="width:100%;display:block">'
    else:
        art = f'<div class="art">{html.escape(panel.description)}</div>'
    return (
        f'<div class="panel{rejected}">{caption}'
        f"{art}{bubble}"
        f'<div class="tag">{panel.panel_id} · {badge} {tries}</div></div>'
    )


def render_pages(run: ChapterRun) -> None:
    st.subheader("Comic pages")
    for page in run.pages:
        st.image(page)
    if run.pdf:
        st.download_button(
            "Download PDF", Path(run.pdf).read_bytes(), file_name=f"{run.chapter_id}.pdf", mime="application/pdf"
        )


def render_comic_preview(panels: list[PanelResult]) -> None:
    st.subheader("Comic preview")
    if not any(panel.best_image for panel in panels):
        st.caption("Placeholder art: this run had no image model.")
    pages = sorted({panel.page for panel in panels})
    page = st.select_slider("Page", options=pages, format_func=lambda n: f"Page {n}") if len(pages) > 1 else pages[0]
    cells = "".join(panel_html(panel) for panel in panels if panel.page == page)
    st.markdown(f'<div class="comic-page">{cells}</div>', unsafe_allow_html=True)


def render_attempt_viewer(panels: list[PanelResult]) -> None:
    st.subheader("Panel attempts")
    retried = [panel for panel in panels if len(panel.attempts) > 1 or not panel.accepted]
    st.caption(
        f"{len(retried)} of {len(panels)} panels needed a retry or were not accepted. "
        "Each attempt shows the Critic's verdict."
    )
    choice = st.selectbox(
        "Inspect panel",
        [panel.panel_id for panel in panels],
        index=panels.index(retried[0]) if retried else 0,
        format_func=lambda pid: f"{pid} ({'retried' if any(p.panel_id == pid for p in retried) else 'first try'})",
    )
    panel = next(panel for panel in panels if panel.panel_id == choice)
    st.markdown(f"**Script:** {panel.description}")
    cols = st.columns(max(len(panel.attempts), 1))
    for col, attempt in zip(cols, panel.attempts, strict=False):
        if attempt.image:
            col.image(attempt.image)
        verdict = "✅ accepted" if attempt.accepted else f"❌ {attempt.failure}"
        state = "done" if attempt.accepted else "failed"
        col.markdown(
            f'<div class="stage-card {state}"><div class="name">Attempt {attempt.attempt}</div>'
            f"{html.escape(verdict)}<br>{html.escape(attempt.note)}</div>",
            unsafe_allow_html=True,
        )
    if not panel.accepted:
        st.warning("Attempts exhausted: the best attempt is shown, not accepted.")


def main() -> None:
    st.set_page_config(page_title="ComArtist", page_icon="🎨", layout="wide")
    apply_theme()
    settings = render_sidebar()

    title, cost = st.columns([5, 2])
    with title:
        st.title("ComArtist")
        st.caption("Brief → Story → Script ⇄ Critic → Visuals → Panels ⇄ Critic → Layout → Judge")
    with cost:
        render_cost_header()

    runs = get_store().list()
    render_pipeline_status(runs)
    st.divider()
    render_new_chapter()
    if not runs:
        return
    st.divider()
    ids = [run.chapter_id for run in runs]
    if st.session_state.get("selected_chapter") not in ids:
        st.session_state.selected_chapter = ids[-1]
    titles = {run.chapter_id: run.spec.title for run in runs}
    selected = st.selectbox("Chapter", ids, format_func=titles.__getitem__, key="selected_chapter")
    run = next(run for run in runs if run.chapter_id == selected)
    render_full_run(run, settings)
    st.divider()
    render_overview(run)


if __name__ == "__main__":
    main()
