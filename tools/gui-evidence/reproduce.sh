#!/usr/bin/env bash
# Reproduce exactly this integration in a fresh clone.
#
#   bash tools/gui-evidence/reproduce.sh
#
# The setup and check commands match the verification plan. The two extra
# steps below (typecheck, compileall) are the repository's own CI gates; they run
# no test source, so they are not listed as plan checks. The frontend build *is* a
# plan check, because it compiles the new OrcaRouter provider UI. The only check
# that needs a real credential is the live one, and it is skipped without
# ORCAROUTER_API_KEY.
#
# The screenshots and manifest.json under orca-evidence/ are produced by the GUI
# step below: orca-evidence/ is purely this run's output directory, it is
# gitignored in full, and nothing under it ships in the patch. The harness itself
# lives in tools/gui-evidence/ so that applying this diff cannot put evidence into
# the tree — the validator requires evidence to be produced by verification.
set -euo pipefail

cd "$(dirname "$0")/../.."

echo "== setup =="
# The plan carries the setup as argument arrays, so the first group is spelled the
# way the validator runs it: `python3 -m pip install --break-system-packages -q`.
# Every pinned backend dependency lives in requirements.txt; `pytest` covers the
# test runner and `playwright` the GUI capture (the browser itself is
# /usr/bin/chromium, already present). `npm --prefix` is used throughout so no
# step depends on the caller's working directory.
python3 -m pip install --break-system-packages -q -r backend/requirements.txt pytest httpx playwright
npm ci --prefix frontend

echo "== frontend: build (plan check; compiles the OrcaRouter provider UI) =="
npm run build --prefix frontend

echo "== backend: credentials (API key adapter + credential seam) =="
python3 -m pytest backend/tests/test_orcarouter_credentials.py -q

echo "== backend: PKCE connect flow =="
python3 -m pytest backend/tests/test_orcarouter_pkce.py -q

echo "== backend: catalog + capability filters =="
python3 -m pytest backend/tests/test_orcarouter_catalog.py -q

echo "== backend: provider endpoints =="
python3 -m pytest backend/tests/test_orcarouter_api.py -q

echo "== frontend: unit tests =="
npm test --prefix frontend

echo "== frontend: typecheck (repo CI step; no test source, so not a plan check) =="
npm run typecheck --prefix frontend

echo "== backend: compile check (repo CI step; no test source, so not a plan check) =="
python3 -m compileall -q backend/app

echo "== GUI evidence (real backend + real UI + Chromium) =="
python3 tools/gui-evidence/run_gui_evidence.py --out orca-evidence

echo "== backend: live (needs ORCAROUTER_API_KEY, skipped otherwise) =="
python3 -m pytest backend/tests/test_orcarouter_live.py -q

echo
echo "All checks passed."
