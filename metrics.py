"""Operational metrics serialization."""

from __future__ import annotations

from typing import Any


def _metric_name(key: str) -> str:
    return "efdb_" + "".join(character if character.isalnum() else "_" for character in key.lower())


def prometheus(metrics: dict[str, Any]) -> str:
    lines = ["# HELP efortablejd_info EflortableJD process information", "# TYPE efortablejd_info gauge", "efortablejd_info{version=\"1\"} 1"]
    for key, value in sorted(metrics.items()):
        if isinstance(value, bool):
            value = int(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            name = _metric_name(key)
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")
    return "\n".join(lines) + "\n"


def snapshot(metrics: dict[str, Any]) -> dict[str, Any]:
    return {"metrics": dict(metrics), "numeric": {key: value for key, value in metrics.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}}
