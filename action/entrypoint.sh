#!/bin/sh
# GitHub Action entrypoint (see ../action.yml). Runs inside the project's Docker image.
#   1. work out base..head from the event (or the `base`/`head` inputs)
#   2. run the normal CLI, JSON out
#   3. publish as a release body or a PR comment
set -eu

if [ -z "${GROQ_API_KEY:-}" ] && [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "::error::set the groq-api-key (or gemini-api-key) input"
  exit 1
fi

RANGE="$(python -m changelog_forge.action range)"
echo "Changelog Forge: ${GITHUB_REPOSITORY} ${RANGE}"

changelog-forge "${GITHUB_REPOSITORY}" "${RANGE}" \
  --audience "${CF_AUDIENCES:-user,dev}" \
  --json --out /tmp/changelog-forge.json

python -m changelog_forge.action publish /tmp/changelog-forge.json

# Best effort: the job summary file may not be writable for a non-root container user.
if [ -n "${GITHUB_STEP_SUMMARY:-}" ] && [ -w "${GITHUB_STEP_SUMMARY}" ]; then
  python -c "import json,sys; from changelog_forge.action import compose_body; from changelog_forge.models import ReleaseNotes; d=json.load(open('/tmp/changelog-forge.json')); print(compose_body({k: ReleaseNotes.model_validate(v) for k, v in d['outputs'].items()}))" >> "${GITHUB_STEP_SUMMARY}" || true
fi
