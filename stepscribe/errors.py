# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Turn the errors people actually hit into one sentence and a suggestion (``--debug`` shows all)."""

from __future__ import annotations

from typing import Any

import typer
from typer.core import TyperGroup

from stepscribe.envcheck import EnvironmentProblem

EXTRAS = {"mcp": "mcp", "httpx": "llm"}


def friendly_message(exc: BaseException) -> str | None:
    """One line for a known error, or None to keep the normal traceback."""
    from stepscribe.io.step_reader import StepReadError
    from stepscribe.render.raster import RenderUnavailable

    if isinstance(exc, EnvironmentProblem):
        return str(exc)
    if isinstance(exc, FileNotFoundError):
        name = exc.filename or (exc.args[0] if exc.args else "the file")
        return f"File not found: {name}. Check the path (put it in quotes if it has spaces)."
    if isinstance(exc, StepReadError):
        text = str(exc)
        if "external references" in text:
            tail = (
                ""
                if "next to it" in text
                else ". Put those files next to it, or export one self-contained STEP"
            )
            return text.rstrip(".") + tail + "."
        return f"{text}. Re-export it from your CAD program as STEP (AP203, AP214 or AP242)."
    if isinstance(exc, RenderUnavailable):
        return (
            "This computer cannot draw images (no usable OpenGL). "
            "Add --no-images, or run: python -m stepscribe doctor"
        )
    if isinstance(exc, MemoryError):
        return (
            "Ran out of memory. Close other programs, or use fewer processes: "
            "set STEPSCRIBE_WORKERS=1"
        )
    if isinstance(exc, TimeoutError):
        return "The analysis took too long and was stopped. Raise the limit with --timeout-s."
    if isinstance(exc, ModuleNotFoundError) and exc.name in EXTRAS:
        extra = EXTRAS[exc.name]
        return (
            f"This needs the optional package '{exc.name}': "
            f'python -m pip install "stepscribe-cad[{extra}]"'
        )
    return None


class FriendlyGroup(TyperGroup):
    """A command group that shows known errors as one line, unless ``--debug`` was given."""

    def invoke(self, ctx: Any) -> Any:
        try:
            return super().invoke(ctx)
        except (typer.Exit, typer.Abort):
            raise
        except Exception as exc:  # noqa: BLE001 - mapped below, everything else is re-raised
            if hasattr(exc, "format_message"):  # usage errors are shown by the command line itself
                raise
            if ctx.meta.get("stepscribe.debug"):
                raise
            message = friendly_message(exc)
            if message is None:
                raise
            typer.echo(message, err=True)
            raise typer.Exit(1) from None
