"""Constants for the OpenCode Zen integration."""

import logging

DOMAIN = "opencode_zen"
LOGGER = logging.getLogger(__package__)

CONF_BASE_URL = "base_url"
CONF_CHAT_MODEL = "chat_model"
CONF_MAX_TOKENS = "max_tokens"
CONF_TEMPERATURE = "temperature"
CONF_TOP_P = "top_p"
CONF_RECOMMENDED = "recommended"
CONF_STREAMING = "streaming"
CONF_REQUIRE_CONFIRMATION = "require_confirmation"

DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_GO_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_ZEN_BASE_URL = "https://opencode.ai/zen/v1"
DEFAULT_MODEL = "muse-spark-1.3-contributor"
RECOMMENDED_CHAT_MODELS = [
    "muse-spark-1.3-contributor",
    "muse-spark-1.2-contributor",
    "muse-spark-1.3",
    "muse-spark-1.2",
]

RECOMMENDED_MAX_TOKENS = 3000
RECOMMENDED_TEMPERATURE = 0.7
RECOMMENDED_TOP_P = 1.0

MAX_TOOL_ITERATIONS = 10
