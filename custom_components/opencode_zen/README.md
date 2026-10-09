# OpenCode Zen — Home Assistant custom integration

Native conversation + AI-task agent for `https://opencode.ai/zen/v1` Responses API,
including `muse-spark-1.3-contributor-free`.

Replaces llama_cpp -> NodeRED header workaround. Sets
`Authorization: Bearer <api_key>` directly.

## Install

1. Copy `opencode_zen/` to `/homeassistant/custom_components/opencode_zen/`
2. Restart Home Assistant (required for custom_components)
3. Add integration, enter base URL + API key, pick model
4. Expose entities to Assist, select Assist API for control

## Verify

- Python syntax: `python3 -m compileall opencode_zen`
- HA check: Developer Tools > YAML > Check configuration after restart
