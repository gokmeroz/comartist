"""Deterministic continuity checks between two chapter runs. No model calls."""

import re

from pydantic import BaseModel, Field

from comartist.models import ChapterRun


class Secret(BaseModel):
    holder: str = Field(min_length=1)
    never_written: list[str] = Field(min_length=1)


class ContinuityExpectations(BaseModel):
    recurring_characters: list[str] = Field(min_length=1)
    location: str = ""
    outfit_changes: list[str] = Field(default_factory=list)
    secret: Secret | None = None


class ContinuityCheck(BaseModel):
    name: str
    passed: bool
    evidence: str


def _look(run: ChapterRun, name: str):
    return next((look for look in run.spec.looks() if look.name.casefold() == name.casefold()), None)


def _reference(run: ChapterRun, name: str) -> str | None:
    return next((path for key, path in run.spec.references.items() if key.casefold() == name.casefold()), None)


def _leaks(run: ChapterRun, phrases: list[str]) -> list[str]:
    patterns = [
        re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", 0 if phrase.isupper() else re.IGNORECASE)
        for phrase in phrases
    ]
    found = []
    for panel in run.script.panels if run.script else []:
        texts = [panel.caption, *(line.text for line in panel.dialogue)]
        for pattern in patterns:
            if any(pattern.search(text) for text in texts):
                found.append(f"{run.chapter_id} {panel.panel_id}: {pattern.pattern}")
    return found


def check_continuity(first: ChapterRun, second: ChapterRun, expect: ContinuityExpectations) -> list[ContinuityCheck]:
    checks = []
    for run in (first, second):
        problems = [] if run.accepted else ["not accepted"]
        if not (run.verdict and run.verdict.approved):
            problems.append("Chapter Judge did not approve")
        checks.append(ContinuityCheck(
            name=f"{run.chapter_id} accepted", passed=not problems, evidence="; ".join(problems) or "accepted",
        ))
    for name in expect.recurring_characters:
        missing = [
            run.chapter_id for run in (first, second)
            if not run.script or not any(name.casefold() in map(str.casefold, p.characters) for p in run.script.panels)
        ]
        checks.append(ContinuityCheck(
            name=f"{name} appears in both chapters", passed=not missing,
            evidence=f"missing from {', '.join(missing)}" if missing else "on panel in both",
        ))
        old, new = _look(first, name), _look(second, name)
        same_face = bool(old and new and old.appearance == new.appearance)
        checks.append(ContinuityCheck(
            name=f"{name} keeps the same appearance", passed=same_face,
            evidence="identical locked appearance" if same_face else
            f"chapter 1: {old.appearance if old else 'no locked look'} | chapter 2: {new.appearance if new else 'no locked look'}",
        ))
        old_ref, new_ref = _reference(first, name), _reference(second, name)
        checks.append(ContinuityCheck(
            name=f"{name} keeps the same reference image", passed=bool(old_ref) and old_ref == new_ref,
            evidence=f"chapter 1: {old_ref or 'none'} | chapter 2: {new_ref or 'none'}",
        ))
    for name in expect.outfit_changes:
        old, new = _look(first, name), _look(second, name)
        changed = bool(old and new and old.outfit != new.outfit)
        checks.append(ContinuityCheck(
            name=f"{name} changes outfit", passed=changed,
            evidence=f"chapter 1: {old.outfit if old else 'none'} | chapter 2: {new.outfit if new else 'none'}",
        ))
    if expect.location:
        wrong = [run.chapter_id for run in (first, second) if run.spec.location != expect.location]
        checks.append(ContinuityCheck(
            name=f"Both chapters set in {expect.location}", passed=not wrong,
            evidence=f"different in {', '.join(wrong)}" if wrong else "same location",
        ))
    if expect.secret:
        leaks = [leak for run in (first, second) for leak in _leaks(run, expect.secret.never_written)]
        checks.append(ContinuityCheck(
            name=f"{expect.secret.holder}'s secret never written", passed=not leaks,
            evidence="; ".join(leaks) or "no forbidden phrase in any dialogue or caption",
        ))
    return checks
