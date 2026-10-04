#!/usr/bin/env bash
# Changelog Forge: push secrets to the two Vercel projects, write local .env files, run migrations.
# Run from Git Bash:  bash scripts/setup-env.sh
# Reads (never prints):
#   G:\AI Engineering Journey\.env                                   GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY
#   G:\Vibe Engineering Apps\.secrets\changelog-forge-database-url.txt         pooled Neon URL
#   G:\Vibe Engineering Apps\.secrets\changelog-forge-database-direct-url.txt  direct Neon URL (migrations)
#   G:\Vibe Engineering Apps\.secrets\changelog-forge-cron-secret.txt
#   optional: changelog-forge-github-token.txt (fine-grained PAT, public repos read), changelog-forge-qstash-token.txt,
#             changelog-forge-langfuse-public.txt / -secret.txt
set -euo pipefail
export PATH="/c/tools/node24:$PATH"
cd "$(dirname "$0")/.."

SECRETS="/g/Vibe Engineering Apps/.secrets"
JOURNEY_ENV="/g/AI Engineering Journey/.env"
API_URL="https://changelog-forge-api.vercel.app"
WEB_URL="https://changelogforge.vercel.app"

read_env() { grep -E "^\s*$2\s*=" "$1" | head -1 | sed -E "s/^\s*$2\s*=\s*//; s/^[\"']//; s/[\"']\s*$//" | tr -d '\r'; }
read_secret() { tr -d '\r\n' < "$1"; }
opt_secret() { [ -s "$1" ] && read_secret "$1" || true; }
set_env() { # dir name value [--sensitive]
  local dir="$1" name="$2" value="$3" flag="${4:-}"
  [ -n "$value" ] || { echo "  skip $name (empty)"; return 0; }
  for target in production preview development; do
    local ok=0
    for attempt in 1 2 3 4; do
      if printf '%s' "$value" | (cd "$dir" && vercel env add "$name" "$target" --force $flag >/dev/null 2>&1); then ok=1; break; fi
      sleep $((5 * attempt))
    done
    [ "$ok" = 1 ] || { echo "FAILED: vercel env add $name $target in $dir"; exit 1; }
  done
  echo "  set $name ($dir)"
}

echo "Collecting values..."
GEMINI=$(read_env "$JOURNEY_ENV" GEMINI_API_KEY)
GROQ=$(read_env "$JOURNEY_ENV" GROQ_API_KEY)
OPENROUTER=$(read_env "$JOURNEY_ENV" OPENROUTER_API_KEY)
CRON=$(read_secret "$SECRETS/changelog-forge-cron-secret.txt")
DB_URL=$(read_secret "$SECRETS/changelog-forge-database-url.txt")
DIRECT_URL=$(read_secret "$SECRETS/changelog-forge-database-direct-url.txt")
case "$DB_URL" in postgres*) ;; *) echo "database url must be postgres://"; exit 1;; esac
GH_TOKEN_VAL=$(opt_secret "$SECRETS/changelog-forge-github-token.txt")
QSTASH=$(opt_secret "$SECRETS/changelog-forge-qstash-token.txt")
LF_PUBLIC=$(opt_secret "$SECRETS/changelog-forge-langfuse-public.txt")
LF_SECRET=$(opt_secret "$SECRETS/changelog-forge-langfuse-secret.txt")

echo "Pushing API env (project changelog-forge-api, repo root)..."
set_env . DATABASE_URL "$DB_URL" --sensitive
set_env . GROQ_API_KEY "$GROQ" --sensitive
set_env . GEMINI_API_KEY "$GEMINI" --sensitive
set_env . OPENROUTER_API_KEY "$OPENROUTER" --sensitive
set_env . CRON_SECRET "$CRON" --sensitive
set_env . GITHUB_TOKEN "$GH_TOKEN_VAL" --sensitive
set_env . QSTASH_TOKEN "$QSTASH" --sensitive
set_env . LANGFUSE_PUBLIC_KEY "$LF_PUBLIC"
set_env . LANGFUSE_SECRET_KEY "$LF_SECRET" --sensitive
set_env . WEB_ORIGIN "$WEB_URL"
set_env . PUBLIC_API_URL "$API_URL"

echo "Pushing web env (project changelog-forge, root dir web/)..."
set_env web NEXT_PUBLIC_API_URL "$API_URL"
set_env web NEXT_PUBLIC_APP_URL "$WEB_URL"

echo "Writing .env (API) and web/.env.local..."
cat > .env <<EOF
DATABASE_URL=$DB_URL
DATABASE_DIRECT_URL=$DIRECT_URL
GROQ_API_KEY=$GROQ
GEMINI_API_KEY=$GEMINI
OPENROUTER_API_KEY=$OPENROUTER
CRON_SECRET=$CRON
GITHUB_TOKEN=$GH_TOKEN_VAL
QSTASH_TOKEN=$QSTASH
LANGFUSE_PUBLIC_KEY=$LF_PUBLIC
LANGFUSE_SECRET_KEY=$LF_SECRET
WEB_ORIGIN=http://localhost:3600
PUBLIC_API_URL=http://localhost:7860
PORT=7860
EOF
cat > web/.env.local <<EOF
NEXT_PUBLIC_API_URL=http://localhost:7860
NEXT_PUBLIC_APP_URL=http://localhost:3600
EOF

echo "Running database migrations (direct URL)..."
DATABASE_URL="$DIRECT_URL" uv run migrate 2>&1 | tail -3
echo "Done. Deploy with: vercel deploy --prod --yes   (repo root = API)   and   (cd web && vercel deploy --prod --yes)"
