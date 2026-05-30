#!/usr/bin/env bash
# Restore the PoC to a clean state so you can re-run the agent recovery demo.
#
#   - stops the full stack
#   - reverts workspace/scraper.py to the seed (v1-only selectors + non-null validation)
#   - clears workspace/failure.json, workspace/agent.log, workspace/.git
#   - brings the full stack back up at SITE_VERSION=v1
#
# Doing the down/up cycle here (rather than leaving it to the user) guarantees
# no stale containers, no stale networks, and no leftover SITE_VERSION env
# from a previous shell command.

set -e
cd "$(dirname "$0")"

echo "==> stopping stack"
docker compose down >/dev/null

echo "==> restoring workspace/scraper.py from seed/"
cp seed/scraper.py workspace/scraper.py

echo "==> clearing failure.json, agent.log, any stale workspace/.git"
rm -f workspace/failure.json workspace/agent.log
rm -rf workspace/.git

echo "==> rebuilding & starting full stack at SITE_VERSION=v1"
SITE_VERSION=v1 docker compose up -d --build >/dev/null

cat <<EOF

reset complete.

  scraper.py  -> seed (only v1 selectors, with required-field validation)
  failure.json, agent.log -> cleared
  mock_site   -> v1
  stack       -> fresh

To reproduce the recovery loop:

  docker compose logs -f agent    # watch the agent in another shell
  make v2                         # BEM redesign + JSON-LD  (easy patch)
  make v3                         # web-component shell     (harder patch)

EOF
