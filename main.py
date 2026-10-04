"""Vercel entry point: Vercel's FastAPI preset looks for `app` in a root-level main.py.

Everything lives in the package; this file only re-exports it. Locally and in Docker use
`uvicorn changelog_forge.api.main:app` instead (docs/setup.md).
"""

from changelog_forge.api.main import app

__all__ = ["app"]
