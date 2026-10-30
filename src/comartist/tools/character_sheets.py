"""Character reference sheets: generate a candidate, then approve it explicitly.

A generated sheet stays a draft. Only `approve_sheet` puts it in the brief, and it locks the
matching look so later visual plans cannot drift away from the approved image.
"""

import base64
from pathlib import Path

from comartist.adapters import ImageModel, ImageRequest
from comartist.models import ChapterRun, CharacterLook
from comartist.workflows.store import RunStore, slugify


def sheet_prompt(look: CharacterLook, style: str) -> str:
    return (
        f"Character reference sheet of {look.name}. {style}. "
        f"Appearance: {look.appearance} Outfit: {look.outfit} "
        "Full body front view and a head-and-shoulders close-up, neutral expression, "
        "plain light background. No text, labels, or captions."
    )


def generate_sheet(
    model: ImageModel, store: RunStore, run: ChapterRun, look: CharacterLook, style: str
) -> str:
    """Save a draft sheet and return its location. Raises ModelError on failure."""
    result = model.generate(ImageRequest(prompt=sheet_prompt(look, style)))
    run.reference_cost = run.reference_cost.add(result.cost)
    if result.image_b64:
        folder = store.root / run.chapter_id / "references"
        folder.mkdir(exist_ok=True)
        # A new file each time, so regenerating can never change an approved sheet.
        stem = f"{slugify(look.name)}-{len(list(folder.glob(f'{slugify(look.name)}-*'))) + 1}"
        path: Path = folder / f"{stem}.{result.mime_type.split('/')[-1]}"
        path.write_bytes(base64.b64decode(result.image_b64))
        location = str(path)
    else:
        location = result.url
    run.reference_drafts[look.name] = location
    run.log.append(f"Reference: draft sheet for {look.name} ({result.provider}/{result.model})")
    store.save(run)
    return location


def approve_sheet(store: RunStore, run: ChapterRun, look: CharacterLook) -> None:
    run.spec.references[look.name] = run.reference_drafts[look.name]
    locked = [item for item in run.spec.locked_looks if item.name.casefold() != look.name.casefold()]
    run.spec.locked_looks = [*locked, look]
    run.log.append(f"Reference: approved sheet for {look.name}; look locked")
    store.save(run)
