"""Tests for EVIDENCE-FLIGHT-RECORDER0.

Recording rules under test:
- Missing citations are data (status ``absent``), not gaps to fill.
- Failures are data (status ``failed`` / ``error``), not errors to repair.
- Do not repair observations — raw state is preserved.
- No authority: recorder observes only.
- File output is durable NDJSON — parseable, diff-able, versionable.

All file I/O tests use ``tmp_path`` (pytest built-in) so nothing leaks.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from dagr_mcp.evidence_flight_recorder import (
    EvidenceFlightRecorder,
    FlightManifest,
    FlightRecord,
    InMemoryFlightRecorder,
    PHASE_CITED,
    PHASE_DISCOVERED,
    PHASE_FETCHED,
    PHASE_RELIED_UPON,
    STATUS_ABSENT,
    STATUS_ERROR,
    STATUS_FAILED,
    STATUS_NOT_EVALUATED,
    STATUS_PRESENT,
    read_flight_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _recorder(tmp_path: Path, *, session_ref: str = "session:test-001") -> EvidenceFlightRecorder:
    log = tmp_path / f"{session_ref.replace(':', '-')}.ndjson"
    return EvidenceFlightRecorder(log_path=log, session_ref=session_ref)


def _read_ndjson(path: Path) -> list[dict]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            lines.append(json.loads(raw))
    return lines


# ---------------------------------------------------------------------------
# FlightRecord construction
# ---------------------------------------------------------------------------


class TestFlightRecordConstruction:
    def test_json_round_trip(self) -> None:
        rec = FlightRecord(
            record_id="efr:abc",
            session_ref="session:x",
            phase=PHASE_DISCOVERED,
            occurred_at="2026-08-19T00:00:00+00:00",
            subject_ref="source:TH-S01",
            source_ref="tool:search",
            status=STATUS_PRESENT,
            detail="found in Wikipedia",
            failure_code=None,
        )
        line = rec.to_json_line()
        obj = json.loads(line)
        assert obj["phase"] == "discovered"
        assert obj["status"] == "present"
        assert obj["failure_code"] is None

    def test_absent_record_round_trip(self) -> None:
        rec = FlightRecord(
            record_id="efr:def",
            session_ref="session:x",
            phase=PHASE_CITED,
            occurred_at="2026-08-19T00:00:00+00:00",
            subject_ref="source:MISSING-001",
            source_ref=None,
            status=STATUS_ABSENT,
            detail="attributed in output but not in record",
            failure_code="citation.source_not_fetched",
        )
        obj = json.loads(rec.to_json_line())
        assert obj["status"] == "absent"
        assert obj["failure_code"] == "citation.source_not_fetched"
        assert obj["source_ref"] is None


# ---------------------------------------------------------------------------
# EvidenceFlightRecorder — file output
# ---------------------------------------------------------------------------


class TestFileRecorder:
    def test_record_creates_ndjson_file(self, tmp_path: Path) -> None:
        with _recorder(tmp_path) as rec:
            rec.discovered("source:wiki-mh370", source_ref="tool:search_wikipedia")

        lines = _read_ndjson(rec.log_path)
        assert len(lines) == 1
        assert lines[0]["phase"] == "discovered"
        assert lines[0]["subject_ref"] == "source:wiki-mh370"
        assert lines[0]["status"] == "present"

    def test_all_four_phases_recorded(self, tmp_path: Path) -> None:
        with _recorder(tmp_path) as rec:
            rec.discovered("source:TH-S01", source_ref="tool:search")
            rec.fetched("source:TH-S01", source_ref="url:https://example.com/th")
            rec.cited("source:TH-S01", source_ref="output:block-3")
            rec.relied_upon("source:TH-S01", source_ref="decision:verdict-A")

        lines = _read_ndjson(rec.log_path)
        assert len(lines) == 4
        phases = [ln["phase"] for ln in lines]
        assert phases == ["discovered", "fetched", "cited", "relied_upon"]

    def test_missing_citation_recorded_as_absent_not_repaired(self, tmp_path: Path) -> None:
        """Missing citations are data. The recorder must NOT fill the gap."""
        with _recorder(tmp_path) as rec:
            # AI cited a source that was never fetched
            rec.cited(
                "source:GHOST-001",
                source_ref=None,
                status=STATUS_ABSENT,
                detail="attributed in output; not in fetch log",
                failure_code="citation.source_not_fetched",
            )

        lines = _read_ndjson(rec.log_path)
        assert len(lines) == 1
        ln = lines[0]
        assert ln["status"] == "absent"
        assert ln["source_ref"] is None
        assert ln["failure_code"] == "citation.source_not_fetched"
        # Original detail is preserved verbatim — no repair
        assert "attributed in output" in ln["detail"]

    def test_failed_fetch_recorded_as_failed(self, tmp_path: Path) -> None:
        """Failures are data. Status is 'failed', not replaced with 'absent'."""
        with _recorder(tmp_path) as rec:
            rec.fetched(
                "source:TH-S01",
                source_ref="url:https://example.com/th",
                status=STATUS_FAILED,
                detail="HTTP 503 after 3 retries",
                failure_code="fetch.http_error.503",
            )

        lines = _read_ndjson(rec.log_path)
        assert len(lines) == 1
        assert lines[0]["status"] == "failed"
        assert lines[0]["failure_code"] == "fetch.http_error.503"

    def test_error_status_recorded_raw(self, tmp_path: Path) -> None:
        with _recorder(tmp_path) as rec:
            rec.record(
                PHASE_FETCHED,
                "source:NYT-001",
                status=STATUS_ERROR,
                detail="ConnectionRefusedError: [Errno 111] Connection refused",
                failure_code="fetch.connection_refused",
            )

        lines = _read_ndjson(rec.log_path)
        assert lines[0]["status"] == "error"
        assert "ConnectionRefusedError" in lines[0]["detail"]

    def test_records_are_appended_in_order(self, tmp_path: Path) -> None:
        log = tmp_path / "session.ndjson"
        rec = EvidenceFlightRecorder(log_path=log, session_ref="session:append-test")

        ids = []
        for i in range(5):
            rid = rec.discovered(f"source:item-{i}")
            ids.append(rid)
        rec.close()

        lines = _read_ndjson(log)
        assert len(lines) == 5
        for i, ln in enumerate(lines):
            assert ln["subject_ref"] == f"source:item-{i}"
            assert ln["record_id"] == ids[i]

    def test_each_record_has_unique_id(self, tmp_path: Path) -> None:
        with _recorder(tmp_path) as rec:
            id1 = rec.discovered("source:A")
            id2 = rec.discovered("source:B")
        assert id1 != id2
        assert id1.startswith("efr:")
        assert id2.startswith("efr:")

    def test_session_ref_propagated_to_all_records(self, tmp_path: Path) -> None:
        with _recorder(tmp_path, session_ref="session:XYZ") as rec:
            rec.discovered("source:A")
            rec.fetched("source:A")

        lines = _read_ndjson(rec.log_path)
        for ln in lines:
            assert ln["session_ref"] == "session:XYZ"

    def test_detail_preserved_verbatim(self, tmp_path: Path) -> None:
        raw_detail = "  Raw observation: tabs\there and unicode élève  "
        with _recorder(tmp_path) as rec:
            rec.discovered("source:A", detail=raw_detail)

        lines = _read_ndjson(rec.log_path)
        assert lines[0]["detail"] == raw_detail  # Not trimmed or normalized

    def test_record_after_close_raises(self, tmp_path: Path) -> None:
        rec = _recorder(tmp_path)
        rec.close()
        with pytest.raises(RuntimeError, match="closed"):
            rec.discovered("source:too-late")

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        rec = _recorder(tmp_path)
        rec.discovered("source:A")
        p1 = rec.close()
        p2 = rec.close()
        assert p1 == p2


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class TestManifest:
    def test_manifest_written_on_close(self, tmp_path: Path) -> None:
        rec = _recorder(tmp_path, session_ref="session:manifest-test")
        rec.discovered("source:A")
        rec.fetched("source:A", status=STATUS_ABSENT, failure_code="fetch.not_found")
        manifest_path = rec.close()

        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert data["session_ref"] == "session:manifest-test"
        assert data["total_records"] == 2
        assert data["by_phase"]["discovered"] == 1
        assert data["by_phase"]["fetched"] == 1
        assert data["by_status"]["present"] == 1
        assert data["by_status"]["absent"] == 1

    def test_gaps_surface_absent_records(self, tmp_path: Path) -> None:
        rec = _recorder(tmp_path)
        rec.discovered("source:A")
        rec.cited("source:GHOST", status=STATUS_ABSENT, failure_code="citation.source_not_fetched")
        rec.fetched("source:B", status=STATUS_ABSENT, failure_code="fetch.not_found")
        manifest_path = rec.close()

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(data["gaps"]) == 2
        gap_subjects = {g["subject_ref"] for g in data["gaps"]}
        assert "source:GHOST" in gap_subjects
        assert "source:B" in gap_subjects

    def test_failures_surface_failed_and_error_records(self, tmp_path: Path) -> None:
        rec = _recorder(tmp_path)
        rec.fetched("source:A", status=STATUS_FAILED, failure_code="fetch.http_error.500")
        rec.discovered("source:B", status=STATUS_ERROR, failure_code="discovery.tool_exception")
        rec.relied_upon("source:C")
        manifest_path = rec.close()

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(data["failures"]) == 2
        failure_subjects = {f["subject_ref"] for f in data["failures"]}
        assert "source:A" in failure_subjects
        assert "source:B" in failure_subjects

    def test_manifest_gaps_are_data_not_anomalies(self, tmp_path: Path) -> None:
        """A manifest with only absent records is valid — not a broken run."""
        rec = _recorder(tmp_path)
        rec.cited("source:GHOST-1", status=STATUS_ABSENT)
        rec.cited("source:GHOST-2", status=STATUS_ABSENT)
        manifest_path = rec.close()

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["total_records"] == 2
        assert len(data["gaps"]) == 2
        assert len(data["failures"]) == 0

    def test_manifest_path_is_sibling_of_log(self, tmp_path: Path) -> None:
        log = tmp_path / "my-session.ndjson"
        rec = EvidenceFlightRecorder(log_path=log, session_ref="session:path-test")
        rec.discovered("source:A")
        manifest_path = rec.close()

        assert manifest_path.parent == tmp_path
        assert manifest_path.name == "my-session.manifest.json"

    def test_manifest_log_path_is_absolute(self, tmp_path: Path) -> None:
        rec = _recorder(tmp_path)
        manifest_path = rec.close()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert Path(data["log_path"]).is_absolute()


# ---------------------------------------------------------------------------
# read_flight_log — round-trip and parse-error tolerance
# ---------------------------------------------------------------------------


class TestReadFlightLog:
    def test_round_trip_all_records(self, tmp_path: Path) -> None:
        with _recorder(tmp_path, session_ref="session:rt") as rec:
            rec.discovered("source:A", source_ref="tool:search")
            rec.fetched("source:A", source_ref="url:https://example.com")
            rec.cited(
                "source:GHOST",
                status=STATUS_ABSENT,
                failure_code="citation.source_not_fetched",
            )

        records = read_flight_log(rec.log_path)
        assert len(records) == 3
        assert records[0].phase == "discovered"
        assert records[1].phase == "fetched"
        assert records[2].phase == "cited"
        assert records[2].status == "absent"
        assert records[2].failure_code == "citation.source_not_fetched"

    def test_parse_error_lines_preserved_as_error_records(self, tmp_path: Path) -> None:
        """Malformed lines are failures, not discards."""
        log = tmp_path / "corrupt.ndjson"
        # Write one valid line and one corrupted line
        valid = FlightRecord(
            record_id="efr:ok",
            session_ref="session:x",
            phase=PHASE_DISCOVERED,
            occurred_at="2026-08-19T00:00:00+00:00",
            subject_ref="source:A",
            source_ref=None,
            status=STATUS_PRESENT,
            detail=None,
            failure_code=None,
        )
        log.write_text(
            valid.to_json_line() + "\n" + "{{NOT VALID JSON}}\n",
            encoding="utf-8",
        )

        records = read_flight_log(log)
        assert len(records) == 2
        assert records[0].status == STATUS_PRESENT
        # Parse-error record is itself a FlightRecord with status=error
        assert records[1].status == STATUS_ERROR
        assert records[1].failure_code == "flight_log.parse_error"
        assert "{{NOT VALID JSON}}" in (records[1].detail or "")

    def test_blank_lines_skipped(self, tmp_path: Path) -> None:
        log = tmp_path / "blanks.ndjson"
        valid = FlightRecord(
            record_id="efr:ok",
            session_ref="session:x",
            phase=PHASE_FETCHED,
            occurred_at="2026-08-19T00:00:00+00:00",
            subject_ref="source:A",
            source_ref=None,
            status=STATUS_PRESENT,
            detail=None,
            failure_code=None,
        )
        log.write_text("\n\n" + valid.to_json_line() + "\n\n", encoding="utf-8")

        records = read_flight_log(log)
        assert len(records) == 1
        assert records[0].phase == "fetched"


# ---------------------------------------------------------------------------
# InMemoryFlightRecorder
# ---------------------------------------------------------------------------


class TestInMemoryRecorder:
    def test_basic_recording(self) -> None:
        rec = InMemoryFlightRecorder(session_ref="session:mem")
        rec.discovered("source:A")
        rec.fetched("source:A", status=STATUS_ABSENT)
        assert rec.records()[0].phase == "discovered"
        assert rec.records()[1].status == "absent"

    def test_close_returns_manifest(self) -> None:
        rec = InMemoryFlightRecorder(session_ref="session:mem")
        rec.cited("source:GHOST", status=STATUS_ABSENT, failure_code="citation.source_not_fetched")
        rec.fetched("source:A", status=STATUS_FAILED, failure_code="fetch.timeout")
        manifest = rec.close()

        assert isinstance(manifest, FlightManifest)
        assert manifest.total_records == 2
        assert len(manifest.gaps) == 1
        assert len(manifest.failures) == 1
        assert manifest.log_path == "<in-memory>"

    def test_record_after_close_raises(self) -> None:
        rec = InMemoryFlightRecorder(session_ref="session:mem")
        rec.close()
        with pytest.raises(RuntimeError, match="closed"):
            rec.discovered("source:too-late")

    def test_context_manager(self) -> None:
        with InMemoryFlightRecorder(session_ref="session:ctx") as rec:
            rec.discovered("source:A")
            rec.relied_upon("source:A")
        assert rec.record_count == 2

    def test_no_file_written(self, tmp_path: Path) -> None:
        with InMemoryFlightRecorder(session_ref="session:no-file") as rec:
            rec.discovered("source:A")
        # In-memory recorder produces no files
        assert list(tmp_path.iterdir()) == []

    def test_phase_convenience_methods(self) -> None:
        rec = InMemoryFlightRecorder(session_ref="session:conv")
        rec.discovered("source:A")
        rec.fetched("source:A")
        rec.cited("source:A")
        rec.relied_upon("source:A")
        phases = [r.phase for r in rec.records()]
        assert phases == ["discovered", "fetched", "cited", "relied_upon"]


# ---------------------------------------------------------------------------
# Vocabulary validation
# ---------------------------------------------------------------------------


class TestVocabularyValidation:
    def test_unknown_phase_raises(self) -> None:
        rec = InMemoryFlightRecorder(session_ref="session:val")
        with pytest.raises(ValueError, match="Unknown evidence phase"):
            rec.record("hallucinated_phase", "source:A")

    def test_unknown_status_raises(self) -> None:
        rec = InMemoryFlightRecorder(session_ref="session:val")
        with pytest.raises(ValueError, match="Unknown evidence status"):
            rec.record("discovered", "source:A", status="invented_status")

    def test_all_known_phases_accepted(self) -> None:
        rec = InMemoryFlightRecorder(session_ref="session:all-phases")
        for phase in ("discovered", "fetched", "cited", "relied_upon"):
            rec.record(phase, f"source:{phase}")
        assert rec.record_count == 4

    def test_all_known_statuses_accepted(self) -> None:
        rec = InMemoryFlightRecorder(session_ref="session:all-statuses")
        for status in ("present", "absent", "failed", "error", "not_evaluated"):
            rec.record("discovered", f"source:{status}", status=status)
        assert rec.record_count == 5


# ---------------------------------------------------------------------------
# No-repair invariant
# ---------------------------------------------------------------------------


class TestNoRepairInvariant:
    """The recorder must never fill gaps, upgrade statuses, or normalize detail."""

    def test_absent_is_not_promoted_to_present(self, tmp_path: Path) -> None:
        with _recorder(tmp_path) as rec:
            rec.cited("source:GHOST", status=STATUS_ABSENT)

        lines = _read_ndjson(rec.log_path)
        assert lines[0]["status"] == "absent"

    def test_failed_is_not_promoted_to_absent(self, tmp_path: Path) -> None:
        with _recorder(tmp_path) as rec:
            rec.fetched("source:X", status=STATUS_FAILED)

        lines = _read_ndjson(rec.log_path)
        assert lines[0]["status"] == "failed"

    def test_none_source_ref_is_not_inferred(self, tmp_path: Path) -> None:
        with _recorder(tmp_path) as rec:
            rec.cited("source:GHOST", source_ref=None, status=STATUS_ABSENT)

        lines = _read_ndjson(rec.log_path)
        assert lines[0]["source_ref"] is None

    def test_none_detail_stays_none(self, tmp_path: Path) -> None:
        with _recorder(tmp_path) as rec:
            rec.discovered("source:A", detail=None)

        lines = _read_ndjson(rec.log_path)
        assert lines[0]["detail"] is None

    def test_failure_code_on_non_failure_status_preserved(self, tmp_path: Path) -> None:
        """Caller supplied failure_code on a present record — store it as-is."""
        with _recorder(tmp_path) as rec:
            rec.record(
                "discovered",
                "source:A",
                status=STATUS_PRESENT,
                failure_code="unexpected.code",
            )

        lines = _read_ndjson(rec.log_path)
        assert lines[0]["failure_code"] == "unexpected.code"


# ---------------------------------------------------------------------------
# Diffability — file is valid line-by-line JSON throughout session
# ---------------------------------------------------------------------------


class TestDiffability:
    def test_log_parseable_after_each_append(self, tmp_path: Path) -> None:
        """The file is valid NDJSON after every single write — not just at close."""
        log = tmp_path / "incremental.ndjson"
        rec = EvidenceFlightRecorder(log_path=log, session_ref="session:incr")

        for i in range(10):
            rec.discovered(f"source:item-{i}")
            # Re-parse the file at this point — it must be valid NDJSON
            lines = _read_ndjson(log)
            assert len(lines) == i + 1

        rec.close()

    def test_each_line_is_independent_json_object(self, tmp_path: Path) -> None:
        with _recorder(tmp_path) as rec:
            rec.discovered("source:A")
            rec.fetched("source:B", status=STATUS_ABSENT)

        raw = rec.log_path.read_text(encoding="utf-8").splitlines()
        non_empty = [ln for ln in raw if ln.strip()]
        for line in non_empty:
            obj = json.loads(line)  # must not raise
            assert isinstance(obj, dict)
            assert "record_id" in obj
            assert "phase" in obj
            assert "status" in obj
