"""Changelog Forge: a git range in, release notes for two audiences out.

Pipeline (docs/architecture.md): collect -> normalise -> chunk -> map -> reduce -> verify ->
render. Every model call goes through llm-kit (`changelog_forge.llm`), every reference the
model emits is checked against the collected input (`pipeline.verify`), and every run carries
a cost ledger at paid rates.
"""

__version__ = "0.1.0"
