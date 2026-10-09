# AGENTS.md — ha-opencode-zen

Custom Home Assistant integration exposing OpenCode Zen/Go models as native
`conversation` + `ai_task` agents via the OpenAI Responses API.

## Layout

- `custom_components/opencode_zen/` — the integration
  (`entity.py` shared Responses loop, `conversation.py`, `ai_task.py`,
  `api.py` validation client, `config_flow.py`, `const.py`)
- `brand/icon.png` — required by HACS
- `hacs.json`, `README.md`, `.github/ISSUE_TEMPLATE/`

## Invariants (do not break)

- Transport is **Responses API with SSE streaming** (`stream: true`) and a
  **non-streaming fallback** when the stream fails before any data arrives.
- Every POST needs `Authorization: Bearer` + `x-opencode-session`
  (per-conversation ID) + own `User-Agent` (Go docs requirement).
- Paid Go models live on `https://opencode.ai/zen/go/v1`
  (`muse-spark-1.3-contributor`); Zen pay-as-you-go on `/zen/v1`.
  Free `*-contributor-free` models fail outside OpenCode (`FreeTierError`).
- Validation POST must use `max_output_tokens >= 16` (Go rejects less).
- Runtime deps: only HA-provided `aiohttp` + `probatio`. No new
  `requirements` without discussion.
- HA floor is 2026.9 (subentries, `ConversationEntity`, `AITaskEntity`).

## Commit format (Conventional Commits — drives releases)

- `feat:` new user-visible feature → minor bump (e.g. `feat: stream responses`)
- `fix:` bug fix → patch bump (e.g. `fix: require 16+ output tokens`)
- `docs:`, `chore:`, `refactor:` → no release (unless breaking)
- Breaking change: `feat!:` / footer `BREAKING-CHANGE:` → major bump
- Scope is optional: `feat(entity): ...`. Keep subject imperative, ≤72 chars,
  English. One logical change per commit.

## Workflow (release-please)

1. Edit here, keep `translations/en.json` + `translations/cs.json` keys in sync.
2. `python3 -m compileall` + `json.tool` check on changed JSON.
3. Commit with **Conventional Commits** (`feat:`, `fix:`, docs/chore otherwise).
   Never bump `manifest.json` version by hand — release-please owns it.
4. Push to `main`. The release-please action opens/updates a release PR
   (CHANGELOG + manifest bump). Merge it to tag + publish the release.
5. HACS picks up the new release automatically.
6. Never hand-edit the HACS-managed live copy; update it through HACS.

No secrets in this repo. API keys live only in HA config entries.
