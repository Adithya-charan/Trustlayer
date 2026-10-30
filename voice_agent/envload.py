"""Loads backend/.env into the worker's environment (the LiveKit, Sarvam and Tavus plugins read their keys from the environment) and
checks the required names. Values are never printed or logged; only variable NAMES appear in messages."""
import os
import pathlib

ENV_FILE = pathlib.Path(__file__).resolve().parents[1] / "backend" / ".env"
REQUIRED = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "SARVAM_API_KEY", "VOICE_AGENT_SECRET"]
OPTIONAL_AVATAR = ["TAVUS_API_KEY", "TAVUS_FACE_ID"]  # without these the agent runs voice-only


def parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip().removeprefix("export ").strip()] = v
    return out


def load(path: pathlib.Path = ENV_FILE) -> None:
    if path.exists():
        for k, v in parse(path.read_text(encoding="utf-8")).items():
            if v:
                os.environ.setdefault(k, v)  # a real environment variable wins over the file


def missing(env=None) -> list[str]:
    env = os.environ if env is None else env
    return [n for n in REQUIRED if not (env.get(n) or "").strip()]


def avatar_configured(env=None) -> bool:
    env = os.environ if env is None else env
    return all((env.get(n) or "").strip() for n in OPTIONAL_AVATAR)
