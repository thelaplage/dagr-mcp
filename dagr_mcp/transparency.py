from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol

import rfc8785


class TransparencyPublicationState(str, Enum):
    REGISTERED = "registered"
    PENDING = "pending"
    TS_REFUSED = "ts_refused"
    TRANSPORT_FAILED = "transport_failed"


@dataclass(frozen=True, slots=True)
class TransparencyPublicationRequest:
    """Digest-only binding from one already-committed SRS receipt to transparency.

    This object is not an admission request and carries no authority movement.
    It deliberately excludes tool arguments, results, prompts, transcripts and
    other governed raw content.
    """

    schema: str
    receipt_id: str
    receipt_kind: str
    receipt_digest: str
    subject_ref: str

    @classmethod
    def from_envelope(cls, envelope: Mapping[str, Any]) -> "TransparencyPublicationRequest":
        canonical = rfc8785.dumps(dict(envelope))
        return cls(
            schema="dagr.transparency_publication_request.v0.1",
            receipt_id=str(envelope["receipt_id"]),
            receipt_kind=str(envelope["receipt_kind"]),
            receipt_digest="sha256:" + hashlib.sha256(canonical).hexdigest(),
            subject_ref=str(envelope["subject_ref"]),
        )

    def payload_bytes(self) -> bytes:
        return json.dumps(
            asdict(self),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class TransparencyPublicationResult:
    schema: str
    receipt_id: str
    state: TransparencyPublicationState
    statement_digest: str | None = None
    receipt_digest: str | None = None
    receipt_bytes_hex: str | None = None
    location: str | None = None
    http_status: int | None = None
    detail: str | None = None

    @classmethod
    def failed(
        cls,
        receipt_id: str,
        *,
        detail: str,
        statement_digest: str | None = None,
    ) -> "TransparencyPublicationResult":
        return cls(
            schema="dagr.transparency_publication_result.v0.1",
            receipt_id=receipt_id,
            state=TransparencyPublicationState.TRANSPORT_FAILED,
            statement_digest=statement_digest,
            detail=detail,
        )

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["state"] = self.state.value
        return body


class TransparencyPublisher(Protocol):
    def publish(
        self, request: TransparencyPublicationRequest
    ) -> TransparencyPublicationResult: ...


class TransparencyResultSink(Protocol):
    def write(self, result: TransparencyPublicationResult) -> None: ...


class ReceiptSink(Protocol):
    def write(self, envelope: Mapping[str, Any]) -> str: ...


class JsonlTransparencyResultSink:
    """Append-only local publication-result custody.

    The sink contains only SCITT transport/publication metadata and receipt
    bytes returned by the Transparency Service. It never receives SRS raw
    governed content because the publication request itself is digest-only.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, result: TransparencyPublicationResult) -> None:
        line = json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        # One append is intentionally simple and independently owned from the
        # SRS receipt sink. Failure here must never retroactively invalidate an
        # already-committed DAGR receipt.
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


class PublishingReceiptSink:
    """Post-commit transparency wrapper around an existing SRS receipt sink.

    Ordering is load-bearing:

      inner SRS sink commit -> optional transparency publication

    Publication and result-custody failures are never re-raised. The only
    exception allowed to cross this wrapper is a failure from the *inner* SRS
    receipt sink itself. Therefore enabling transparency cannot alter a DAGR
    admission/outcome disposition or turn a successfully committed SRS receipt
    into an emitter failure.
    """

    def __init__(
        self,
        inner: ReceiptSink,
        *,
        publisher: TransparencyPublisher | None = None,
        result_sink: TransparencyResultSink | None = None,
    ):
        self.inner = inner
        self.publisher = publisher
        self.result_sink = result_sink

    def write(self, envelope: Mapping[str, Any]) -> str:
        receipt_id = self.inner.write(envelope)  # authoritative commit happens first
        if self.publisher is None:
            return receipt_id

        request = TransparencyPublicationRequest.from_envelope(envelope)
        try:
            result = self.publisher.publish(request)
        except Exception as exc:  # external transparency is a non-authoritative side effect
            result = TransparencyPublicationResult.failed(
                receipt_id,
                detail=f"publisher_exception:{type(exc).__name__}",
            )

        if self.result_sink is not None:
            try:
                self.result_sink.write(result)
            except Exception:
                # Do not launder a publication-result custody problem into an
                # SRS receipt failure. Operators can monitor this side channel
                # independently; DAGR semantics remain closed.
                pass
        return receipt_id


@dataclass(frozen=True, slots=True)
class ScrapiResponse:
    state: TransparencyPublicationState
    location: str | None
    receipt_bytes: bytes | None
    http_status: int | None
    detail: str | None = None


class ScrapiClient:
    """Narrow draft-ietf-scitt-scrapi-11 registration adapter.

    v0.1 deliberately performs exactly one POST and does not poll asynchronous
    registrations. HTTP 202 becomes ``PENDING`` with the returned Location;
    a separate caller may resolve it later. This keeps post-receipt publication
    from blocking the governed MCP call on Transparency Service finality.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        request_headers: Mapping[str, str] | None = None,
    ):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("SCRAPI base_url must be an absolute http(s) URL")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self.request_headers = dict(request_headers or {})

    def register(self, statement_bytes: bytes) -> ScrapiResponse:
        headers = {
            "Content-Type": "application/cose",
            "Accept": "application/cose",
            **self.request_headers,
        }
        request = urllib.request.Request(
            f"{self.base_url}/entries",
            data=statement_bytes,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                status = int(response.status)
                location = response.headers.get("Location")
                body = response.read()
                if status == 201:
                    if not location or not body:
                        return ScrapiResponse(
                            TransparencyPublicationState.TRANSPORT_FAILED,
                            location,
                            None,
                            status,
                            "scrapi_201_missing_location_or_receipt",
                        )
                    return ScrapiResponse(
                        TransparencyPublicationState.REGISTERED,
                        location,
                        body,
                        status,
                    )
                if status == 202:
                    if not location:
                        return ScrapiResponse(
                            TransparencyPublicationState.TRANSPORT_FAILED,
                            None,
                            None,
                            status,
                            "scrapi_202_missing_location",
                        )
                    return ScrapiResponse(
                        TransparencyPublicationState.PENDING,
                        location,
                        None,
                        status,
                    )
                return ScrapiResponse(
                    TransparencyPublicationState.TRANSPORT_FAILED,
                    location,
                    None,
                    status,
                    f"unexpected_http_status:{status}",
                )
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                return ScrapiResponse(
                    TransparencyPublicationState.TS_REFUSED,
                    exc.headers.get("Location") if exc.headers else None,
                    None,
                    int(exc.code),
                    "registration_policy_or_request_refused",
                )
            return ScrapiResponse(
                TransparencyPublicationState.TRANSPORT_FAILED,
                exc.headers.get("Location") if exc.headers else None,
                None,
                int(exc.code),
                f"http_error:{exc.code}",
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return ScrapiResponse(
                TransparencyPublicationState.TRANSPORT_FAILED,
                None,
                None,
                None,
                f"transport_error:{type(exc).__name__}",
            )


class ScittStatementPublisher:
    """Build a digest-only SCITT Signed Statement and register it with SCRAPI.

    ``scitt-cose`` is imported lazily so the base DAGR MCP installation retains
    byte-compatible behavior and dependency isolation unless the operator opts
    into the ``scitt`` extra.
    """

    def __init__(
        self,
        client: ScrapiClient,
        *,
        issuer: str,
        private_key_pem: bytes,
        alg: str = "EdDSA",
    ):
        if not issuer:
            raise ValueError("SCITT issuer must be non-empty")
        self.client = client
        self.issuer = issuer
        self.private_key_pem = private_key_pem
        self.alg = alg

    def publish(
        self, request: TransparencyPublicationRequest
    ) -> TransparencyPublicationResult:
        try:
            from scitt_cose import build_signed_statement
        except ImportError as exc:  # explicit optional capability boundary
            return TransparencyPublicationResult.failed(
                request.receipt_id,
                detail="scitt_extra_not_installed",
            )

        statement = build_signed_statement(
            request.payload_bytes(),
            alg=self.alg,
            private_key_pem=self.private_key_pem,
            issuer=self.issuer,
            subject=request.receipt_id,
            content_type="application/json",
        )
        statement_digest = "sha256:" + hashlib.sha256(statement).hexdigest()
        response = self.client.register(statement)
        receipt_digest = (
            "sha256:" + hashlib.sha256(response.receipt_bytes).hexdigest()
            if response.receipt_bytes is not None
            else None
        )
        return TransparencyPublicationResult(
            schema="dagr.transparency_publication_result.v0.1",
            receipt_id=request.receipt_id,
            state=response.state,
            statement_digest=statement_digest,
            receipt_digest=receipt_digest,
            receipt_bytes_hex=(
                response.receipt_bytes.hex() if response.receipt_bytes is not None else None
            ),
            location=response.location,
            http_status=response.http_status,
            detail=response.detail,
        )


__all__ = [
    "JsonlTransparencyResultSink",
    "PublishingReceiptSink",
    "ReceiptSink",
    "ScrapiClient",
    "ScrapiResponse",
    "ScittStatementPublisher",
    "TransparencyPublicationRequest",
    "TransparencyPublicationResult",
    "TransparencyPublicationState",
    "TransparencyPublisher",
    "TransparencyResultSink",
]
