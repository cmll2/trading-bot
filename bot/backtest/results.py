"""Results files (FR-18, NFR-02, NFR-09, AD-21).

``results/{date}_{strategy}_{commit12}.json`` (machine-readable, sorted keys) and the
matching ``.md`` report. The content holds no wall-clock timestamp, so the same code,
config and data produce byte-identical files; the run date is only in the file name.
Every file is labelled SIMULATED.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


def results_stem(run_date: date, strategy_id: str, commit: str) -> str:
    return f"{run_date.isoformat()}_{strategy_id}_{commit[:12]}"


def write_results(
    results_dir: Path, stem: str, payload: dict[str, Any], report_md: str
) -> tuple[Path, Path]:
    """Write ``{stem}.json`` and ``{stem}.md`` atomically enough for a CLI run."""
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / f"{stem}.json"
    md_path = results_dir / f"{stem}.md"
    text = json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n"
    tmp = json_path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(json_path)
    tmp = md_path.with_suffix(".md.tmp")
    tmp.write_text(report_md, encoding="utf-8", newline="\n")
    tmp.replace(md_path)
    return json_path, md_path
