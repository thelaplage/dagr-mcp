from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_frozen_wp2a_artifacts_match_pins():
    schema = ROOT / "dagr_mcp/vendor/srs/srs-envelope-v0.2.0.schema.json"
    assert digest(schema.read_bytes()) == (
        "d03aad1d5517e2acb65d5c866905aed7219bcbbfadd1a4a97eac546dd23f0333"
    )

    # The v0.2.1 envelope is the additive successor. The v0.2.0 pin above is
    # retained unchanged: v0.2.1 does not replace it, and both digests are
    # externally pinnable.
    schema_v0_2_1 = ROOT / "dagr_mcp/vendor/srs/srs-envelope-v0.2.1.schema.json"
    assert digest(schema_v0_2_1.read_bytes()) == (
        "2afa1ec9f093fd7c06c4f5db7bfd37cc63e64e3dcbe47c963f4df586a1c18ca1"
    )

    archive = ROOT / "dagr_mcp/vendor/srs/frozen-profiles.zip"
    expected = {
        "docs/profiles/SRS_SIGNED_RECEIPT_PROFILE_v0_1.md": (
            "827cdbbe9a4a836ed70ee4422db0d6ee361568949c5e87cc8c2abcc408d99df1"
        ),
        "docs/profiles/SRS_MCP_SDK_ENFORCEMENT_PROFILE_v0_1.md": (
            "3043993d6297a1c493ee7b2e8ab2627267054ae2de5f8f83d55cd80e1a52f9ce"
        ),
    }
    with zipfile.ZipFile(archive) as frozen:
        for member, wanted in expected.items():
            assert digest(frozen.read(member)) == wanted
