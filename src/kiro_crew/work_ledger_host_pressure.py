"""The host's memory pressure, as one record every conductor can read.

``docs/request-for-change/rfc-work-ledger-resource-pressure.md`` §3.1 and §3.2.
The gateway's :class:`~kiro_crew.notifications.resource_pressure.ResourcePressureNotifier`
is the only writer: while a pressure episode is open it rewrites this record on
every sample, and on recovery it writes ``clear`` once. ``work_ledger_read`` shows
it on the ``conductor`` block and the work-ledger probe wakes on it.

The record is host-wide, so it lives in one file beside the boards, not inside any
board: each conductor stays the only writer of its own header, and nothing that
walks the work-ledger tree ever meets it.

A record nobody refreshed for :data:`STALE_SECS` reads as absent. So a gateway that
died or restarted mid-episode cannot leave a ``critical`` behind; absent means
proceed, the same as ``resource_status.admission_check`` on an unreadable probe.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kiro_crew.atomic_write import atomic_write
from kiro_crew.config.paths import data_home

logger = logging.getLogger(__name__)

LEVEL_TIGHT = "tight"
LEVEL_CRITICAL = "critical"
LEVEL_CLEAR = "clear"
LEVELS: tuple[str, ...] = (LEVEL_TIGHT, LEVEL_CRITICAL, LEVEL_CLEAR)

#: Three of the notifier's 30 s samples. A record older than this reads as absent.
STALE_SECS = 90.0

#: How long a ``clear`` record reads. It is written once and never refreshed, so it
#: must outlast a conductor's turn and its next 300 s patrol tick, or a conductor
#: that was mid-turn at recovery would never read the level that resumes it. A
#: ``clear`` past its episode still means proceed, the same as absent.
CLEAR_STALE_SECS = 900.0

_FILE_NAME = "work-ledger-host-pressure.json"


def path() -> Path:
    """Resolved per call: ``data_home()`` is overridable in tests."""
    return data_home() / _FILE_NAME


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds")


def write(
    *,
    episode: str,
    level: str,
    since: float,
    reading: str,
    load_per_cpu: float | None,
    now: float | None = None,
) -> None:
    """Replace the record atomically. *since* and *now* are wall-clock epochs."""
    stamp = time.time() if now is None else now
    record = {
        "episode": episode,
        "level": level,
        "since": _iso(since),
        "updated_at": _iso(stamp),
        "updated_epoch": stamp,
        "reading": reading,
        "load_per_cpu": load_per_cpu,
    }
    atomic_write(path(), json.dumps(record), mode=0o600, newline="\n")


def read_record(now: float | None = None) -> dict[str, Any] | None:
    """The fresh stored record, or ``None``. Never raises.

    ``None`` for a missing, torn or unknown-level file, and for one older than
    :data:`STALE_SECS` (:data:`CLEAR_STALE_SECS` for ``clear``).
    """
    try:
        raw = json.loads(path().read_text(encoding="utf-8"))
        level = raw.get("level")
        episode = raw.get("episode")
        updated = float(raw.get("updated_epoch"))
    except Exception:
        return None
    if level not in LEVELS or not isinstance(episode, str) or not episode:
        return None
    age = (time.time() if now is None else now) - updated
    if not 0 <= age <= (CLEAR_STALE_SECS if level == LEVEL_CLEAR else STALE_SECS):
        return None
    return dict(raw, age_secs=int(age))


def read(now: float | None = None) -> dict[str, Any] | None:
    """The ``host_pressure`` block ``work_ledger_read`` shows, or ``None`` when absent."""
    record = read_record(now)
    if record is None:
        return None
    return {
        "level": record["level"],
        "since": record.get("since", ""),
        "age_secs": record["age_secs"],
        "reading": record.get("reading", ""),
        "load_per_cpu": record.get("load_per_cpu"),
    }
