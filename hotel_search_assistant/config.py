from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "hotel_assistant_config.json"


@dataclass(frozen=True)
class AssistantConfig:
    provider: str
    base_url: str
    model: str
    temperature: float
    max_tokens: int
    top_p: float
    frequency_penalty: float
    presence_penalty: float
    request_timeout_seconds: int
    system_prompt: str
    json_schema: dict[str, Any]


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AssistantConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        raw = json.load(file)

    system_prompt = raw["system_prompt"]

    return AssistantConfig(
        provider=str(raw["provider"]),
        base_url=str(raw["base_url"]).rstrip("/"),
        model=str(raw["model"]),
        temperature=float(raw.get("temperature", 0.2)),
        max_tokens=int(raw.get("max_tokens", 500)),
        top_p=float(raw.get("top_p", 1.0)),
        frequency_penalty=float(raw.get("frequency_penalty", 0)),
        presence_penalty=float(raw.get("presence_penalty", 0)),
        request_timeout_seconds=int(raw.get("request_timeout_seconds", 300)),
        system_prompt=normalize_system_prompt(system_prompt),
        json_schema=dict(raw["json_schema"]),
    )


def normalize_system_prompt(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(line) for line in value)
    return str(value)
