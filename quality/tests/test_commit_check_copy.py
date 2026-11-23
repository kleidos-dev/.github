# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""The commit-message checker the kit's CI runs is kleidos-dev/agents', byte for byte.

reusable-commit-check.yml takes .github/commit-check/check_commit_msg.py
from the kit commit a repository records, so this copy is the one every
repository's CI checks commit messages with. It is recorded in
.github/commit-check/SOURCE.json (source, commit, SHA-256): a hand edit here
fails the digest, and with kleidos-dev/agents checked out beside this
repository (or named by KLEIDOS_AGENTS_REPO) the recorded commit must hold
the same bytes, so the CI's checker cannot drift from the one each
repository's commit-msg hook runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / ".github" / "commit-check" / "SOURCE.json"


def _manifest() -> dict[str, object]:
    data: dict[str, object] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data


def _files() -> list[dict[str, str]]:
    files = _manifest()["files"]
    assert isinstance(files, list)
    return files


class CommitCheckCopyTest(unittest.TestCase):
    def test_the_copy_is_the_bytes_the_manifest_records(self) -> None:
        files = _files()
        self.assertEqual([e["path"] for e in files], [".github/commit-check/check_commit_msg.py"])
        for entry in files:
            digest = hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest()
            self.assertEqual(
                digest,
                entry["sha256"],
                f"{entry['path']} is not the copy SOURCE.json records: never edit it here;"
                " copy it from kleidos-dev/agents and update the manifest",
            )

    def test_the_recorded_commit_holds_the_same_bytes(self) -> None:
        named = os.environ.get("KLEIDOS_AGENTS_REPO")
        source = Path(named) if named else ROOT.parent / "agents"
        if not (source / ".git").exists():
            self.skipTest("kleidos-dev/agents is not checked out beside this repository")
        commit = str(_manifest()["commit"])
        for entry in _files():
            shown = subprocess.run(
                ["git", "-C", str(source), "show", f"{commit}:{entry['source_path']}"],
                capture_output=True,
                check=False,
            )
            if shown.returncode != 0:
                self.skipTest(f"commit {commit[:12]} is not in {source} (fetch it)")
            self.assertEqual(hashlib.sha256(shown.stdout).hexdigest(), entry["sha256"])


if __name__ == "__main__":
    unittest.main()
