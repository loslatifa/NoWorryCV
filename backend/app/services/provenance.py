"""Capture runtime identifiers without including credentials, endpoints or candidate data."""
import hashlib
import json
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.schemas.quality import GenerationProvenance
from backend.app.services.llm.provider import get_llm_provider
from backend.app.services.prompt_loader import get_prompt_loader

SCORING_VERSION = "jd-match-v1"


def digest_files(paths):
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda value: str(value)):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def capture_provenance(processing_mode="full"):
    settings = get_settings()
    provider = get_llm_provider()
    loader = get_prompt_loader()
    root = Path(__file__).resolve().parents[3]
    agents = root / "backend" / "app" / "agents"
    data = dict(
        provider=getattr(provider, "name", "unknown"),
        model=getattr(provider, "model", "stub" if not provider.is_available else "unknown"),
        prompt_version=loader.default_version,
        prompt_digest=digest_files((loader.base_dir / loader.default_version).glob("*.md")),
        scoring_version=SCORING_VERSION,
        scoring_digest=digest_files([agents / "ats.py", root / "backend/app/services/scoring/heuristics.py"]),
        pipeline_digest=digest_files(list(agents.glob("*.py")) + [root / "backend/app/services/preferences.py", root / "backend/app/schemas/preferences.py", root / "backend/app/schemas/interview.py", root / "backend/app/services/interviews.py", root / "backend/app/services/llm/provider.py", root / "backend/app/services/llm/structured.py"]),
        processing_mode=processing_mode, strict_mode=settings.llm_strict_mode,
    )
    data["fingerprint"] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return GenerationProvenance(**data)
