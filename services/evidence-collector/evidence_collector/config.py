# Made with Claude (Claude Code, Anthropic)
"""Evidence collector settings from env. Never hardcode endpoints."""
import os
from dataclasses import dataclass
from pathlib import Path

from .safety_case import DEFAULT_PATH


@dataclass(frozen=True)
class Settings:
    data_dir: Path           # events.jsonl + evidence.db
    evidence_dir: Path       # one JSON file per evidence record
    safety_case: Path
    sovd_url: str            # OpenSOVD base, .../sovd
    sovd_app: str            # SOVD app = DFM entity path
    http_host: str
    http_port: int
    grace_ms: int            # wait after campaign_end for late messages
    diag_timeout_ms: int     # an expected DTC must show up in OpenSOVD this long after the guardian raised it
    end_timeout_ms: int      # campaign_end missing: close this long after the campaign's duration_s

    @property
    def events_path(self) -> Path:
        return self.data_dir / "events.jsonl"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "evidence.db"


def settings() -> Settings:
    data_dir = Path(os.environ.get("EVIDENCE_DATA_DIR", "./evidence-data"))
    return Settings(
        data_dir=data_dir,
        evidence_dir=Path(os.environ.get("EVIDENCE_DIR", str(data_dir / "evidence"))),
        safety_case=Path(os.environ.get("SAFETY_CASE_PATH", str(DEFAULT_PATH))),
        sovd_url=os.environ.get("SOVD_URL", "http://127.0.0.1:7690/sovd"),
        sovd_app=os.environ.get("SOVD_APP", "battery_guardian"),
        http_host=os.environ.get("EVIDENCE_HTTP_HOST", "127.0.0.1"),
        http_port=int(os.environ.get("EVIDENCE_HTTP_PORT", "8082")),
        grace_ms=int(os.environ.get("EVIDENCE_GRACE_MS", "5000")),
        diag_timeout_ms=int(os.environ.get("EVIDENCE_DIAG_TIMEOUT_MS", "5000")),
        end_timeout_ms=int(os.environ.get("EVIDENCE_END_TIMEOUT_MS", "30000")),
    )
