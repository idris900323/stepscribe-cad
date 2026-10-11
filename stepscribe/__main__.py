# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""``python -m stepscribe``: works even when pip's Scripts folder is not on PATH."""

from stepscribe.cli import app

if __name__ == "__main__":
    app()
