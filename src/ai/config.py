import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from ai.errors import ConfigurationError, ModelSelectionError


class Role(StrEnum):
    MATERIAL_ANALYSIS = "material_analysis"
    MATERIAL_OCR = "material_ocr"
    QUESTION_GENERATION = "question_generation"
    TEACHBACK = "teachback"
    EVALUATION = "evaluation"
    QUESTION_TAGGING = "question_tagging"


class ModelTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Literal["gemini", "openai", "anthropic", "groq"]
    model: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*$")
    available: bool = False
    supports_images: bool = False


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    gemini_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    groq_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    groq_strict_outputs: bool = False
    groq_model: str = Field(
        default="qwen/qwen3.8-27b",
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*$",
    )
    gemini_model: str = (
        "gemini-3.8-flash"  # Development credential helper, never an implicit allowlist.
    )
    live_enabled: bool = False
    free_tier_confirmed: bool = False
    server_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    upstage_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    upstage_model: str = Field(
        default="document-parse", pattern=r"^document-parse(?:-[a-zA-Z0-9]+)?$"
    )
    upstage_timeout_seconds: float = Field(default=120, gt=0, le=300)
    document_cache_dir: Path = Path(".cache/document-parse")
    timeout_seconds: float = Field(default=60, gt=0, le=60)
    max_output_tokens: int = Field(default=4096, ge=128, le=16384)
    model_allowlist: dict[str, ModelTarget] = Field(default_factory=dict, max_length=100)
    routes: dict[Role, str] = Field(default_factory=dict)
    default_model_id: str | None = None

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        values = dict(dotenv_values(env_file)) if env_file is not None else {}
        values.update(os.environ)
        try:
            return cls(
                gemini_api_key=values.get("GEMINI_API_KEY") or "",
                groq_api_key=values.get("GROQ_API_KEY") or "",
                groq_strict_outputs=values.get("GROQ_STRICT_OUTPUTS", "false"),
                groq_model=values.get("GROQ_MODEL") or "qwen/qwen3.8-27b",
                gemini_model=values.get("GEMINI_MODEL") or "gemini-3.8-flash",
                live_enabled=values.get("AI_LIVE_ENABLED", "false"),
                free_tier_confirmed=values.get("AI_FREE_TIER_CONFIRMED", "false"),
                server_api_key=values.get("AI_SERVER_API_KEY") or "",
                upstage_api_key=values.get("UPSTAGE_API_KEY") or "",
                upstage_model=values.get("UPSTAGE_DOCUMENT_MODEL") or "document-parse",
                upstage_timeout_seconds=values.get("UPSTAGE_TIMEOUT_SECONDS", "120"),
                document_cache_dir=values.get("DOCUMENT_CACHE_DIR") or ".cache/document-parse",
                timeout_seconds=values.get("AI_TIMEOUT_SECONDS", "60"),
                max_output_tokens=values.get("AI_MAX_OUTPUT_TOKENS", "4096"),
                model_allowlist=json.loads(values.get("AI_MODEL_ALLOWLIST") or "{}"),
                routes=json.loads(values.get("AI_MODEL_ROUTES") or "{}"),
                default_model_id=values.get("AI_DEFAULT_MODEL_ID") or None,
            )
        except (ValidationError, ValueError, TypeError):
            raise ConfigurationError(
                "Invalid AI configuration; check environment settings."
            ) from None

    def target_for(self, role: Role, model_id: str | None = None) -> ModelTarget:
        selected = model_id or self.routes.get(role) or self.default_model_id
        target = self.model_allowlist.get(selected or "")
        if target is None or not target.available:
            raise ModelSelectionError("model_id is not active in the configured backend allowlist.")
        if not any(selected.startswith(target.provider + separator) for separator in (":", "/")):
            raise ModelSelectionError(
                "model_id must be provider-qualified in the backend allowlist."
            )
        return target
