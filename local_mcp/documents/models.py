"""Document parsing data models."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DocumentSource:
    path: Path
    label: str
    cleanup_dir: tempfile.TemporaryDirectory[str] | None = None

    def cleanup(self) -> None:
        if self.cleanup_dir is not None:
            self.cleanup_dir.cleanup()


@dataclass
class ParseResult:
    parser: str
    output_format: str
    content: str
    source: str
    metadata: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
