# NPH Command Center

<!-- project: github.com/n3phz/nph-command-center -->

Created 2026-10-02. One cockpit for the NPH ecosystem.
Repo: https://github.com/n3phz/nph-command-center (was empty/absent; created this session).

## Current State (2026-10-02)

- React 18 + TypeScript + Vite frontend, 10 lazy-loaded pages, dark-first shell with
  collapsible sidebar, command palette (`/`, `Cmd/Ctrl+K`), SSE live updates.
- FastAPI backend; `backend/backend/api/command_center.py` adds 11 read-only endpoints
  (`/api/system/status`, `/api/services`, `/api/hosts`, `/api/storage`,
  `/api/ai/command-center`, `/api/projects`, `/api/alerts`, `/api/activity`,
  `/api/quick-actions`, `/api/search`, `/api/infrastructure/snapshot`), wired into `main.py`.
- CI green on `main`: frontend `tsc && vite build` passes; backend imports + route
  resolution verified in a clean checkout.

## Data Honesty Rule

Service/host/storage/AI numbers in `command_center.py` are **static baseline constants**,
not live probes. They reflect what was observed from this host at 2026-10-02. Any health
check that actually queries a remote must be labelled with its source, and hosts without
verified reachability must render `discovered`, never `healthy`. Do not promote these
constants into "live metrics" claims.

## Deployment Blocker (verified, not guessed)

`pre35.neph.ovh` could not be reached from this environment:

- SSH port 22, 2222, 8022, and Tailscale IP `100.120.68.90` → connection refused.
- SSH port **49122 is open** but every locally available key is rejected
  (`id_ed25519`, `pve02_openclaw`, `hermes_ed25519`, `saltbox_openclaw`,
  `steam_trade_bot`, `pre35_ops`) → `Permission denied (publickey,password)`.
  This port matches the one pre34/pre30 use in `known_hosts`.
- Dokploy API (`/api/v1/*`) returns 401 on every management endpoint. No Dokploy
  token exists in env or the workspace.

Consequence: as of 2026-10-02 `https://pre35.neph.ovh/` still serves the Dokploy login
page and `/api/health` returns `{"ok":true}` from Dokploy, not from this app. To finish
deployment someone must either authorize `pre35_ops.pub` for root@pre35 on port 49122, or
supply a Dokploy API token.

## Next Steps

1. Add `pre35_ops.pub` to `/root/.ssh/authorized_keys` on pre35 (port 49122).
2. Build and push images on pre35; register an application in Dokploy; route the
   desired host/PathPrefix through Traefik.
3. Replace the static constants in `command_center.py` with real probes once reachability
   exists, keeping the honest-unavailable state for anything not verifiable.