"""Pixel-art styling: yellow paper, blue pixel titles, hard-edged blocks."""

import html

import streamlit as st

PIXEL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap');

:root {
  --paper: #FFF3C4;
  --paper-dark: #FFE58A;
  --ink: #2B2118;
  --blue: #2E5BBA;
  --blue-dark: #1B3A7A;
}

html, body, [data-testid="stAppViewContainer"], .stMarkdown, p, li, label, td, th {
  font-family: 'VT323', monospace !important;
  font-size: 1.25rem;
}

h1, h2, h3, h4 {
  font-family: 'Press Start 2P', monospace !important;
  color: var(--blue) !important;
  text-shadow: 3px 3px 0 var(--paper-dark), 4px 4px 0 var(--blue-dark);
  letter-spacing: 1px;
  line-height: 1.5 !important;
}
h1 { font-size: 2rem !important; }
h2, h3 { font-size: 1.1rem !important; }

[data-testid="stSidebar"] {
  background: var(--paper-dark);
  border-right: 4px solid var(--ink);
}

.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
  font-family: 'Press Start 2P', monospace !important;
  font-size: 0.7rem;
  border: 3px solid var(--ink) !important;
  border-radius: 0 !important;
  box-shadow: 4px 4px 0 var(--ink);
}
.stButton > button:active { transform: translate(4px, 4px); box-shadow: none; }

.st-key-run_full button {
  width: 100%;
  min-height: 5.5rem;
  font-size: 1.4rem !important;
  background: var(--blue) !important;
  color: var(--paper) !important;
  box-shadow: 8px 8px 0 var(--ink);
}
.st-key-run_full button p { font-size: 1.3rem !important; }
.st-key-run_full button:disabled { background: #8A93A8 !important; }

.hud {
  background: var(--paper);
  border: 3px solid var(--ink);
  box-shadow: 4px 4px 0 var(--blue);
  padding: 0.35rem 0.6rem;
  margin-top: 0.8rem;
}
.hud-row {
  display: grid; grid-template-columns: 4.2rem auto 1fr; align-items: center;
  gap: 0.5rem; line-height: 1.6;
}
.hud-row .label { font-family: 'Press Start 2P', monospace; font-size: 0.45rem; color: var(--blue); }
.hud-row .usd { font-family: 'Press Start 2P', monospace; font-size: 0.6rem; color: var(--ink); white-space: nowrap; }
.hud-row .tok { font-family: 'Press Start 2P', monospace; font-size: 0.45rem; color: #7A6A45; white-space: nowrap; text-align: right; }
.hud .pixel-bar { margin: 0.25rem 0 0.1rem; display: grid; grid-template-columns: 1fr auto; gap: 0.5rem; align-items: center; }
.hud .pixel-bar .blocks { border-width: 2px; padding: 2px; gap: 2px; order: 1; }
.hud .pixel-bar .block { height: 6px; }
.hud .pixel-bar .bar-label { order: 2; margin: 0; font-size: 0.45rem; }

.stage-card {
  border: 3px solid var(--ink);
  background: var(--paper);
  padding: 0.5rem;
  min-height: 7.5rem;
}
.stage-card.done { background: #D9F2C4; }
.stage-card.running { background: #CFE0FF; }
.stage-card.failed { background: #F7C6C0; }
.stage-card .name {
  font-family: 'Press Start 2P', monospace;
  font-size: 0.55rem;
  color: var(--blue-dark);
}

.pixel-bar { margin: 0.6rem 0; }
.pixel-bar .blocks { display: flex; gap: 3px; border: 3px solid var(--ink); padding: 3px; background: var(--paper); }
.pixel-bar .block { flex: 1; height: 16px; background: #E9DDAF; }
.pixel-bar .block.on { background: var(--blue); }
.pixel-bar.warn .block.on { background: #C8402F; }
.pixel-bar .bar-label { font-family: 'Press Start 2P', monospace; font-size: 0.55rem; color: var(--blue-dark); margin-bottom: 4px; }

.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 0.4rem 0; }
.chip {
  border: 3px solid var(--ink); background: var(--paper-dark); padding: 2px 10px;
  box-shadow: 3px 3px 0 var(--blue); font-size: 1.15rem;
}

.comic-page {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px;
  background: #FFFDF3; border: 4px solid var(--ink); box-shadow: 8px 8px 0 var(--blue); padding: 12px;
}
.comic-page .panel {
  position: relative; border: 4px solid var(--ink); min-height: 220px; display: flex; flex-direction: column;
  background-color: #FFF8DC;
  background-image: radial-gradient(#E7D79B 1.5px, transparent 1.5px);
  background-size: 10px 10px;
}
.comic-page .panel.rejected { outline: 4px dashed #C8402F; outline-offset: -10px; }
.comic-page .caption {
  align-self: flex-start; background: var(--paper-dark); border-right: 3px solid var(--ink);
  border-bottom: 3px solid var(--ink); padding: 2px 8px; font-size: 1.05rem;
}
.comic-page .art { flex: 1; display: flex; align-items: center; justify-content: center; text-align: center; padding: 10px 18px; color: #7A6A45; }
.comic-page .bubble {
  align-self: center; background: white; border: 3px solid var(--ink); border-radius: 18px;
  padding: 4px 12px; margin-bottom: 30px; font-size: 1.1rem; max-width: 85%;
}
.comic-page .tag {
  position: absolute; right: 0; bottom: 0; background: var(--ink); color: var(--paper);
  font-family: 'Press Start 2P', monospace; font-size: 0.5rem; padding: 4px 6px;
}

textarea, input, [data-baseweb="select"] > div {
  border-radius: 0 !important;
  font-family: 'VT323', monospace !important;
}
[data-testid="stDataFrame"], [data-testid="stExpander"] { border: 3px solid var(--ink); border-radius: 0; }
</style>
"""


def apply_theme() -> None:
    st.markdown(PIXEL_CSS, unsafe_allow_html=True)


def cost_hud(rows: list[tuple[str, str, str]], footer: str = "") -> str:
    """One pixel panel of (label, usd, tokens) rows with an optional footer, e.g. a budget bar."""
    body = "".join(
        f'<div class="hud-row"><span class="label">{html.escape(label)}</span>'
        f'<span class="usd">{html.escape(usd)}</span><span class="tok">{html.escape(tok)}</span></div>'
        for label, usd, tok in rows
    )
    return f'<div class="hud">{body}{footer}</div>'


def pixel_bar(fraction: float, label: str, *, blocks: int = 24, warn_at: float | None = None) -> str:
    """A chunky block progress bar; turns red once `fraction` reaches `warn_at`."""
    fraction = min(max(fraction, 0.0), 1.0)
    lit = round(fraction * blocks)
    cells = "".join(f'<div class="block{" on" if i < lit else ""}"></div>' for i in range(blocks))
    warn = " warn" if warn_at is not None and fraction >= warn_at else ""
    return (
        f'<div class="pixel-bar{warn}"><div class="bar-label">{html.escape(label)} · {fraction:.0%}</div>'
        f'<div class="blocks">{cells}</div></div>'
    )
