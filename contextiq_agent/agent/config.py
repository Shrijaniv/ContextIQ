"""ContextIQ configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Load .env file from project root
try:
    from dotenv import load_dotenv
    PROJECT_ROOT = Path(__file__).parent.parent.parent
    ENV_FILE = PROJECT_ROOT / ".env"
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
except ImportError:
    pass  # dotenv not installed, rely on system env vars


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class ContextIQConfig:
    aws_region: str
    aws_profile: str | None
    openweathermap_api_key: str | None
    yelp_api_key: str | None
    tavily_api_key: str | None


def load_config() -> ContextIQConfig:
    """Load config from environment variables.

    Simple configuration with no mode complexity - just load environment variables.
    STRANDS_KNOWLEDGE_BASE_ID is read directly by memory tool from environment.

    If AWS_PROFILE is set, boto3 will automatically use that profile for credentials.
    """
    aws_profile = os.environ.get("AWS_PROFILE")
    if aws_profile:
        # Set AWS_PROFILE so boto3 uses it automatically
        os.environ["AWS_PROFILE"] = aws_profile

    return ContextIQConfig(
        aws_region=os.environ.get("AWS_REGION", "us-west-2"),
        aws_profile=aws_profile,
        openweathermap_api_key=os.environ.get("OPENWEATHERMAP_API_KEY"),
        yelp_api_key=os.environ.get("YELP_API_KEY"),
        tavily_api_key=os.environ.get("TAVILY_API_KEY"),
    )


# Module-level singleton
_config: ContextIQConfig | None = None


def get_config() -> ContextIQConfig:
    """Get or load the singleton config."""
    global _config
    if _config is None:
        _config = load_config()
    return _config
