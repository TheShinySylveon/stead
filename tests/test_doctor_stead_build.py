"""Doctor checks for unapproved or edited stead-build contributions."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from ctx import doctor, frontmatter


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DoctorSteadBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "context" / "contributions").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _stead_build(self, name: str, spec_sha: str | None) -> Path:
        meta = {
            "id": f"contribution-x-issue-{name}", "type": "contribution",
            "title": "X", "created": "2026-11-21", "updated": "2026-11-21",
            "kind": "issue", "number": int(name), "role": "author",
            "state": "open", "visibility": "public", "tags": ["stead-build"],
        }
        if spec_sha is not None:
            meta["spec_sha"] = spec_sha
        path = self.root / "context" / "contributions" / f"issue-{name}.md"
        path.write_text(frontmatter.dumps(meta, "approved body\n"), encoding="utf-8")
        return path

    def test_missing_spec_sha_warns(self) -> None:
        self._stead_build("1", None)
        report = doctor.run(self.root)
        self.assertTrue(any("no spec_sha" in w["message"] for w in report["warnings"]))

    def test_changed_body_warns(self) -> None:
        wrong = _sha("different body\n")
        self._stead_build("2", wrong)
        report = doctor.run(self.root)
        self.assertTrue(any("body changed (spec_sha mismatch)" in w["message"]
                           for w in report["warnings"]))

    def test_approved_is_silent(self) -> None:
        good = _sha("approved body\n")
        self._stead_build("3", good)
        report = doctor.run(self.root)
        self.assertFalse(any("spec_sha" in w["message"] for w in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
