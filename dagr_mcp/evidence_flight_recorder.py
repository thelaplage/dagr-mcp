"""EVIDENCE-FLIGHT-RECORDER0 — structured audit log for AI evidence behavior.

Tracks separately:
- ``discovered``  — what the AI surfaced or located
- ``fetched``     — what was actually retrieved / loaded
- ``cited``       — what was attributed in AI output
- ``relied_upon`` — what drove the AI's conclusions or decisions

Recording rules:
- Missing citations are data (status ``absent``), not gaps to fill.
- Failures are data (status ``failed`` / ``error``), not errors to repair.
- Do not repair observations. Record the raw state.
- No authority. This recorder observes; it does not admit, refuse, or gate.
- No in-memory-only state: every record is written to a durable NDJSON file
  before ``record()`` returns.

This module has no authority over admission decisions and MUST NOT be imported
by arcs-verify (issuer/verifier separation is inviolate).

Outputs
-------
``<session_ref>.ndjson`` — one JSON object per line, one line per ``FlightRecord``.
``<session_ref>.manifest.json`` — summary written on ``close()``.

Both files are diff-able, versionable, and inspectable with standard tools.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Sequence


# ---------------------------------------------------------------------------
# Vocabulary — closed sets; do not widen without a doctrine decision.
# ---------------------------------------------------------------------------

EvidencePhase = Literal["discovered", "fetched", "cited", "relied_upon"]
EvidenceStatus = Literal["present", "absent", "failed", "error", "not_evaluated"]

PHASE_DISCOVERED: EvidencePhase = "discovered"
PHASE_FETCHED: EvidencePhase = "fetched"
PHASE_CITED: EvidencePhase = "cited"
PHASE_RELIED_UPON: EvidencePhase = "relied_upon"

STATUS_PRESENT: EvidenceStatus = "present"
STATUS_ABSENT: EvidenceStatus = "absent"
STATUS_FAILED: EvidenceStatus = "failed"
STATUS_ERROR: EvidenceStatus = "error"
STATUS_NOT_EVALUATED: EvidenceStatus = "not_evaluated"

_KNOWN_PHASES: frozenset[str] = frozenset(
    {"discovered", "fetched", "cited", "relied_upon"}
)
_KNOWN_STATUSES: frozenset[str] = frozenset(
    {"present", "absent", "failed", "error", "not_evaluated"}
)

# Failure statuses — these are surfaced as ``failures`` in the manifest.
_FAILURE_STATUSES: frozenset[str] = frozenset({"failed", "error"})
# Gap statuses — surfaced as ``gaps`` (missing citations, missing fetches).
_GAP_STATUSES: frozenset[str] = frozenset({"absent"})


# ---------------------------------------------------------------------------
# Core record type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FlightRecord:
    """One evidence-phase observation.

    All fields are positional or keyword; none have defaults except
    ``source_ref``, ``detail``, and ``failure_code`` which may be ``None``
    when not applicable.

    ``record_id`` is a stable UUID minted at construction time.  Callers
    should treat it as opaque.

    Invariants
    ----------
    - ``phase`` must be in ``_KNOWN_PHASES``.
    - ``status`` must be in ``_KNOWN_STATUSES``.
    - ``detail`` and ``failure_code`` are stored exactly as supplied — no
      trimming, normalizing, or inference.  Raw observation is the contract.
    """

    record_id: str
    session_ref: str
    phase: str          # EvidencePhase — validated on construction
    occurred_at: str    # ISO 8601 UTC, e.g. "2026-08-19T14:30:00.000000+00:00"
    subject_ref: str    # what is being tracked (tool name, source ID, URL, etc.)
    source_ref: str | None  # where it came from; None if genuinely unknown
    status: str             # EvidenceStatus — validated on construction
    detail: str | None      # raw observation text; not repaired or normalized
    failure_code: str | None  # structured failure code for ``failed``/``error``

    def to_json_line(self) -> str:
        """Serialize to a single JSON line (no trailing newline)."""
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))


def _validate_phase(phase: str) -> None:
    if phase not in _KNOWN_PHASES:
        raise ValueError(
            f"Unknown evidence phase {phase!r}. "
            f"Known phases: {sorted(_KNOWN_PHASES)}"
        )


def _validate_status(status: str) -> None:
    if status not in _KNOWN_STATUSES:
        raise ValueError(
            f"Unknown evidence status {status!r}. "
            f"Known statuses: {sorted(_KNOWN_STATUSES)}"
        )


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_record_id() -> str:
    return f"efr:{uuid.uuid4()}"


def _make_record(
    *,
    session_ref: str,
    phase: str,
    subject_ref: str,
    source_ref: str | None,
    status: str,
    detail: str | None,
    failure_code: str | None,
    occurred_at: str | None,
) -> FlightRecord:
    """Construct and validate a ``FlightRecord``.  Internal helper."""
    _validate_phase(phase)
    _validate_status(status)
    return FlightRecord(
        record_id=_new_record_id(),
        session_ref=session_ref,
        phase=phase,
        occurred_at=occurred_at or _now_utc_iso(),
        subject_ref=subject_ref,
        source_ref=source_ref,
        status=status,
        detail=detail,
        failure_code=failure_code,
    )


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


@dataclass
class FlightManifest:
    """Summary written when the recorder is closed.

    ``gaps`` lists every record whose status is ``absent`` — missing citations
    and missing fetches, preserved as-is.  ``failures`` lists every record
    whose status is ``failed`` or ``error``.  Both are data, not anomalies.
    """

    session_ref: str
    opened_at: str
    closed_at: str
    log_path: str           # absolute path to the NDJSON log file
    total_records: int
    by_phase: dict[str, int]
    by_status: dict[str, int]
    gaps: list[dict]        # absent-status records (missing citations, fetches)
    failures: list[dict]    # failed/error-status records

    def to_dict(self) -> dict:
        return {
            "session_ref": self.session_ref,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "log_path": self.log_path,
            "total_records": self.total_records,
            "by_phase": self.by_phase,
            "by_status": self.by_status,
            "gaps": self.gaps,
            "failures": self.failures,
        }


# ---------------------------------------------------------------------------
# Shared manifest builder (used by both recorder implementations)
# ---------------------------------------------------------------------------


def _assemble_manifest(
    *,
    session_ref: str,
    opened_at: str,
    log_path: str,
    records: list[FlightRecord],
) -> FlightManifest:
    by_phase: dict[str, int] = {}
    by_status: dict[str, int] = {}
    gaps: list[dict] = []
    failures: list[dict] = []

    for rec in records:
        by_phase[rec.phase] = by_phase.get(rec.phase, 0) + 1
        by_status[rec.status] = by_status.get(rec.status, 0) + 1
        if rec.status in _GAP_STATUSES:
            gaps.append(asdict(rec))
        if rec.status in _FAILURE_STATUSES:
            failures.append(asdict(rec))

    return FlightManifest(
        session_ref=session_ref,
        opened_at=opened_at,
        closed_at=_now_utc_iso(),
        log_path=log_path,
        total_records=len(records),
        by_phase=by_phase,
        by_status=by_status,
        gaps=gaps,
        failures=failures,
    )


# ---------------------------------------------------------------------------
# File-backed recorder
# ---------------------------------------------------------------------------


class EvidenceFlightRecorder:
    """Append-only, file-backed audit log for AI evidence behavior.

    Usage::

        recorder = EvidenceFlightRecorder(
            log_path=Path("/path/to/session.ndjson"),
            session_ref="session:abc123",
        )
        recorder.discovered("wikipedia:MH370", source_ref="tool:search")
        recorder.fetched("wikipedia:MH370", source_ref="url:https://...",
                         status="absent", detail="HTTP 404")
        recorder.cited("wikipedia:MH370", source_ref="url:https://...",
                       status="absent",
                       failure_code="citation.source_not_fetched")
        manifest_path = recorder.close()

    Or as a context manager::

        with EvidenceFlightRecorder(...) as rec:
            rec.discovered(...)

    Durability
    ----------
    Each call to ``record()`` writes one JSON line to the NDJSON file and
    calls ``fsync``.  The file is opened in write mode (truncates on open);
    concurrent writers are not coordinated.

    Thread safety
    -------------
    Not thread-safe.  Each thread / task should use its own recorder instance.
    """

    def __init__(
        self,
        log_path: Path | str,
        session_ref: str,
    ) -> None:
        self._log_path = Path(log_path).resolve()
        self._session_ref = session_ref
        self._opened_at = _now_utc_iso()
        self._records: list[FlightRecord] = []
        self._closed = False
        self._manifest_path: Path | None = None

        # Truncate on open: each recorder instance owns exactly one session's
        # records. Callers must use a unique path per session.
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._log_path.open("w", encoding="utf-8")

    # ------------------------------------------------------------------
    # Core record API
    # ------------------------------------------------------------------

    def record(
        self,
        phase: str,
        subject_ref: str,
        *,
        source_ref: str | None = None,
        status: str = STATUS_PRESENT,
        detail: str | None = None,
        failure_code: str | None = None,
        occurred_at: str | None = None,
    ) -> str:
        """Append one ``FlightRecord`` to the NDJSON log.

        Returns the stable ``record_id`` of the appended record.

        Parameters
        ----------
        phase:
            One of ``discovered``, ``fetched``, ``cited``, ``relied_upon``.
        subject_ref:
            Identifier for what is being tracked.  Use a structured
            prefix where possible (e.g. ``"tool:search_wikipedia"``,
            ``"source:TH-S01"``, ``"url:https://..."``).
        source_ref:
            Where the subject came from.  ``None`` when genuinely unknown —
            not inferred.
        status:
            One of ``present``, ``absent``, ``failed``, ``error``,
            ``not_evaluated``.  ``absent`` = missing citation / not found.
            ``failed`` / ``error`` = the operation failed.  Do not substitute
            ``present`` for a failure or missing item.
        detail:
            Raw observation text.  Stored verbatim — not trimmed, normalized,
            or inferred.
        failure_code:
            Structured code for ``failed``/``error`` statuses.  Not required
            but strongly recommended for machine-readable gap analysis.
        occurred_at:
            ISO 8601 UTC timestamp.  Defaults to now.

        Raises
        ------
        ValueError
            If ``phase`` or ``status`` is outside the known vocabulary.
        RuntimeError
            If the recorder has already been closed.
        """
        if self._closed:
            raise RuntimeError("EvidenceFlightRecorder is closed; cannot record more.")
        rec = _make_record(
            session_ref=self._session_ref,
            phase=phase,
            subject_ref=subject_ref,
            source_ref=source_ref,
            status=status,
            detail=detail,
            failure_code=failure_code,
            occurred_at=occurred_at,
        )
        self._records.append(rec)
        self._fh.write(rec.to_json_line() + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())
        return rec.record_id

    # ------------------------------------------------------------------
    # Phase-specific convenience methods
    # ------------------------------------------------------------------

    def discovered(
        self,
        subject_ref: str,
        *,
        source_ref: str | None = None,
        status: str = STATUS_PRESENT,
        detail: str | None = None,
        failure_code: str | None = None,
        occurred_at: str | None = None,
    ) -> str:
        """Record an evidence-discovery observation."""
        return self.record(
            PHASE_DISCOVERED,
            subject_ref,
            source_ref=source_ref,
            status=status,
            detail=detail,
            failure_code=failure_code,
            occurred_at=occurred_at,
        )

    def fetched(
        self,
        subject_ref: str,
        *,
        source_ref: str | None = None,
        status: str = STATUS_PRESENT,
        detail: str | None = None,
        failure_code: str | None = None,
        occurred_at: str | None = None,
    ) -> str:
        """Record a fetch-attempt observation."""
        return self.record(
            PHASE_FETCHED,
            subject_ref,
            source_ref=source_ref,
            status=status,
            detail=detail,
            failure_code=failure_code,
            occurred_at=occurred_at,
        )

    def cited(
        self,
        subject_ref: str,
        *,
        source_ref: str | None = None,
        status: str = STATUS_PRESENT,
        detail: str | None = None,
        failure_code: str | None = None,
        occurred_at: str | None = None,
    ) -> str:
        """Record a citation observation.

        Use ``status="absent"`` when the AI attributed a claim to a source
        but that source was not fetched or does not exist in the record.
        Missing citations are data — not errors to repair.
        """
        return self.record(
            PHASE_CITED,
            subject_ref,
            source_ref=source_ref,
            status=status,
            detail=detail,
            failure_code=failure_code,
            occurred_at=occurred_at,
        )

    def relied_upon(
        self,
        subject_ref: str,
        *,
        source_ref: str | None = None,
        status: str = STATUS_PRESENT,
        detail: str | None = None,
        failure_code: str | None = None,
        occurred_at: str | None = None,
    ) -> str:
        """Record a reliance observation.

        ``relied_upon`` captures what the AI used to ground its conclusions or
        decisions, as distinct from what it merely cited in output.  It is
        valid for a source to appear in ``cited`` but not ``relied_upon`` and
        vice versa — the gap is itself an observation, not an inconsistency to
        resolve.
        """
        return self.record(
            PHASE_RELIED_UPON,
            subject_ref,
            source_ref=source_ref,
            status=status,
            detail=detail,
            failure_code=failure_code,
            occurred_at=occurred_at,
        )

    # ------------------------------------------------------------------
    # Close / manifest
    # ------------------------------------------------------------------

    def close(self) -> Path:
        """Flush, close the NDJSON log, and write a summary manifest.

        Returns the path to the manifest file.

        The manifest surfaces:
        - ``gaps``: every record with status ``absent`` (missing citations,
          missing fetches) — data, not anomalies.
        - ``failures``: every record with status ``failed`` or ``error`` —
          data, not anomalies.

        Calling ``close()`` a second time is a no-op (returns the same
        manifest path).
        """
        if self._closed:
            return self._manifest_path

        self._fh.close()
        self._closed = True  # set before manifest write; handle is now closed regardless
        manifest = self._build_manifest()
        manifest_path = self._log_path.with_suffix(".manifest.json")
        manifest_path.write_text(
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._manifest_path = manifest_path
        return manifest_path

    def _build_manifest(self) -> FlightManifest:
        return _assemble_manifest(
            session_ref=self._session_ref,
            opened_at=self._opened_at,
            log_path=str(self._log_path),
            records=self._records,
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "EvidenceFlightRecorder":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Inspection (read-only)
    # ------------------------------------------------------------------

    @property
    def log_path(self) -> Path:
        return self._log_path

    @property
    def session_ref(self) -> str:
        return self._session_ref

    @property
    def record_count(self) -> int:
        return len(self._records)

    def records(self) -> list[FlightRecord]:
        """Return a copy of all records appended so far."""
        return list(self._records)


# ---------------------------------------------------------------------------
# In-memory recorder (for testing and environments where file I/O is
# unavailable)
# ---------------------------------------------------------------------------


class InMemoryFlightRecorder:
    """In-memory variant of ``EvidenceFlightRecorder``.

    No files are written.  Intended for unit tests and dry-run scenarios.
    The recording contract (no repair, gaps are data, failures are data) is
    identical.
    """

    def __init__(self, session_ref: str) -> None:
        self._session_ref = session_ref
        self._opened_at = _now_utc_iso()
        self._records: list[FlightRecord] = []
        self._closed = False
        self._manifest: FlightManifest | None = None

    def record(
        self,
        phase: str,
        subject_ref: str,
        *,
        source_ref: str | None = None,
        status: str = STATUS_PRESENT,
        detail: str | None = None,
        failure_code: str | None = None,
        occurred_at: str | None = None,
    ) -> str:
        if self._closed:
            raise RuntimeError("InMemoryFlightRecorder is closed.")
        rec = _make_record(
            session_ref=self._session_ref,
            phase=phase,
            subject_ref=subject_ref,
            source_ref=source_ref,
            status=status,
            detail=detail,
            failure_code=failure_code,
            occurred_at=occurred_at,
        )
        self._records.append(rec)
        return rec.record_id

    def discovered(self, subject_ref: str, **kwargs) -> str:
        return self.record(PHASE_DISCOVERED, subject_ref, **kwargs)

    def fetched(self, subject_ref: str, **kwargs) -> str:
        return self.record(PHASE_FETCHED, subject_ref, **kwargs)

    def cited(self, subject_ref: str, **kwargs) -> str:
        return self.record(PHASE_CITED, subject_ref, **kwargs)

    def relied_upon(self, subject_ref: str, **kwargs) -> str:
        return self.record(PHASE_RELIED_UPON, subject_ref, **kwargs)

    def close(self) -> FlightManifest:
        """Mark closed and return a ``FlightManifest`` (not written to disk)."""
        if self._closed:
            return self._manifest  # type: ignore[return-value]
        self._closed = True
        self._manifest = self._build_manifest()
        return self._manifest

    def _build_manifest(self) -> FlightManifest:
        return _assemble_manifest(
            session_ref=self._session_ref,
            opened_at=self._opened_at,
            log_path="<in-memory>",
            records=self._records,
        )

    def records(self) -> list[FlightRecord]:
        return list(self._records)

    @property
    def record_count(self) -> int:
        return len(self._records)

    def __enter__(self) -> "InMemoryFlightRecorder":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Log reader — parse an existing NDJSON log back to FlightRecords
# ---------------------------------------------------------------------------


def read_flight_log(log_path: Path | str) -> list[FlightRecord]:
    """Parse an NDJSON flight log and return all ``FlightRecord`` objects.

    Blank lines are skipped.  Lines that cannot be parsed as JSON are
    represented as ``FlightRecord`` entries with:
    - ``phase="parse_error"`` (a special sentinel — not a real phase)
    - ``status="error"``
    - ``failure_code="flight_log.parse_error"``
    - ``detail`` = the raw line text

    This preserves the "failures are data" invariant even in the reader.
    """
    path = Path(log_path)
    records: list[FlightRecord] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.rstrip("\n")
            if not line:
                continue
            try:
                obj = json.loads(line)
                records.append(
                    FlightRecord(
                        record_id=obj.get("record_id", ""),
                        session_ref=obj.get("session_ref", ""),
                        phase=obj.get("phase", ""),
                        occurred_at=obj.get("occurred_at", ""),
                        subject_ref=obj.get("subject_ref", ""),
                        source_ref=obj.get("source_ref"),
                        status=obj.get("status", ""),
                        detail=obj.get("detail"),
                        failure_code=obj.get("failure_code"),
                    )
                )
            except (json.JSONDecodeError, TypeError) as exc:
                records.append(
                    FlightRecord(
                        record_id=_new_record_id(),
                        session_ref="",
                        phase="parse_error",
                        occurred_at=_now_utc_iso(),
                        subject_ref=f"log_line:{lineno}",
                        source_ref=str(path),
                        status=STATUS_ERROR,
                        detail=line,
                        failure_code="flight_log.parse_error",
                    )
                )
    return records


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

__all__ = [
    # Vocabulary
    "EvidencePhase",
    "EvidenceStatus",
    "PHASE_DISCOVERED",
    "PHASE_FETCHED",
    "PHASE_CITED",
    "PHASE_RELIED_UPON",
    "STATUS_PRESENT",
    "STATUS_ABSENT",
    "STATUS_FAILED",
    "STATUS_ERROR",
    "STATUS_NOT_EVALUATED",
    # Types
    "FlightRecord",
    "FlightManifest",
    # Recorders
    "EvidenceFlightRecorder",
    "InMemoryFlightRecorder",
    # Reader
    "read_flight_log",
]
