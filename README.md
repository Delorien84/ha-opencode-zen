# OpenCode Zen for Home Assistant

Custom integration that exposes [OpenCode Zen / Go](https://opencode.ai/docs/zen)
models (e.g. `muse-spark-1.3-contributor`) as native Home Assistant
`conversation` + `ai_task` agents via the OpenAI Responses API.

## Install via HACS

1. HACS → Integrations → ⋮ → Custom repositories
2. Add this repository URL as type **Integration**
3. Install **OpenCode Zen**, restart Home Assistant

## Manual install

Copy `custom_components/opencode_zen/` to
`/homeassistant/custom_components/opencode_zen/` and restart.

## Setup

Settings → Devices & services → Add Integration → **OpenCode Zen**:

- Base URL: `https://opencode.ai/zen/go/v1` (Go subscription)
  or `https://opencode.ai/zen/v1` (Zen pay-as-you-go)
- API key from the OpenCode console
- Pick a model, add a conversation and/or AI task agent

## Notes

- Free `*-contributor-free` models only work inside OpenCode,
  not through this API integration.
- Go requests send `x-opencode-session` + own User-Agent per Go docs.
- Streaming responses with non-streaming fallback.
- No extra Python dependencies (uses HA `aiohttp` + `probatio`).
