#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Move a repository from kit 2.x copies to the run form, and refresh its base configurations.

    kit_switch.py --write REPO [--commit SHA]
        the mechanical part of the switch (docs/quality.md, "Switching from
        kit 2.x"): removes the kit's scripts, the drift caller and the
        commit-check folder, rewrites the gate workflow to call quick.yml,
        check.yml and sonar.yml with the "✅ Check" job last, the comment
        caller, the hook list and Dependabot's entry, drops the block markers,
        turns the organization rules into a link, and writes the base
        configurations with their record
    kit_switch.py --configs REPO [--commit SHA]
        only the base configurations and their record (a repository that has
        switched takes newer ones)

The checkout this script is in is the kit that is written. It prints what it
did and what is left to do by hand, changes nothing outside REPO, and commits
nothing. It goes with kit 3.1, when no repository holds copies any more, but
for --configs.

Python 3.14 or newer; PyYAML.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "quality"))
import agent_docs  # noqa: E402  the kit's module, found through the path set above
import check_quality as cq  # noqa: E402  the kit's module, as above
import own_files  # noqa: E402  the kit's module, as above
import run_form  # noqa: E402  the kit's module, as above
import spdx_headers  # noqa: E402  the kit's module, as above

WORKFLOWS = ".github/workflows"
PRE_COMMIT = ".pre-commit-config.yaml"
# The hooks of the held form, all of them replaced by the kit's own entry.
HELD_HOOKS = {
    "kleidos-quality",
    "kleidos-md-nowrap",
    "kleidos-spdx-headers",
    "kleidos-agent-docs",
    "kleidos-commit-msg",
    "mypy",
}
HELD_FILES = (
    f"{WORKFLOWS}/quality-drift.yml",
    f"{WORKFLOWS}/commit-check.yml",
    ".github/quality/requirements-tools.txt",
)
# Each 2.x workflow -> the job of the run form that has taken its check.
NEW_JOB = {
    "reusable-lint.yml": "quick",
    "reusable-reuse.yml": "quick",
    "reusable-secrets.yml": "quick",
    "reusable-mypy.yml": "check",
    "reusable-python-tests.yml": "check",
    "reusable-eslint.yml": "check",
    "reusable-osv.yml": "check",
    "reusable-sonarcloud.yml": "sonar",
}
DEPENDABOT_ENTRY = f"""\
  # The hook revisions of {PRE_COMMIT}, the kit's and third parties'.
  - package-ecosystem: pre-commit
    directory: /
    schedule:
      interval: weekly
    cooldown:
      default-days: 7
      exclude:
        - "{run_form.KIT_HOOKS_URL}"
    ignore:
      # The kit's next major is taken by hand, with the fixes it asks for.
      - dependency-name: "{run_form.KIT_HOOKS_URL}"
        update-types: ["version-update:semver-major"]
      # crate-ci/typos also tags its sub-crates, which read as typos 5.x.
      - dependency-name: "https://github.com/crate-ci/typos"
        versions: [">= 2"]
    groups:
      hooks:
        patterns: ["*"]
"""
RULES_SECTION = (
    "## Organization rules\n\nThe rules every kleidos-dev repository shares are the"
    f" [organization rules]({agent_docs.RULES_URL}): read them before changing anything here.\n"
)
JOB_LINE = re.compile(r"^  (?P<id>[\w-]+):\s*(?:#.*)?$")


def head_of(path: Path) -> str:
    """The commit a checkout is at."""
    done = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


# --------------------------------------------------------------------------
# The base configurations


def write_configs(repo: Path, kit: cq.Kit, commit: str, today: dt.date) -> list[str]:
    """Write the base configurations the tree calls for and their record."""
    path = own_files.own_file(repo, cq.SOURCE_JSON)
    old = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    recorded = (old.get("kit") or {}).get("profiles") or old.get("profiles") or []
    chosen = {"base", *recorded} | cq.detect_profiles(cq.Repo(repo))
    profiles = [p for p in cq.KNOWN_PROFILES if p in chosen]
    configs = run_form.base_configs(kit, profiles)
    for target in configs:
        own_files.own_file(repo, target)  # all of them, before the first is written
    log = []
    files = {}
    for target, source in sorted(configs.items()):
        data = kit.read(source)
        if own_files.write(repo, target, data):
            log.append(f"wrote {target}")
        files[target] = cq.sha256(data)
    record = {
        "$comment": (
            "The base configurations of the Kleidos quality kit the tools read from this"
            " repository's disk; nothing else of the kit is held here. Never edit them: the"
            " kit's tools/ecosystem.py refresh writes newer ones (docs/quality.md there)."
        ),
        "schema": run_form.SCHEMA,
        "upstream": {
            "repo": cq.KIT_REPO,
            "path": ".",
            "commit": commit,
            "held_by": "the kleidos-kit hook and the lint job of the kit's quick.yml",
        },
        "mode": "follow",
        "taken": today.isoformat(),
        "root": ".",
        "kit": {"version": kit.version(), "profiles": profiles},
        "sources": configs,
        "files": files,
    }
    text = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    if old.get("files") == files and old.get("schema") == run_form.SCHEMA:
        return log  # the bytes are the ones recorded: the date says when they were taken
    own_files.write(repo, cq.SOURCE_JSON, text)
    log.append(f"recorded {len(files)} base configurations in {cq.SOURCE_JSON}")
    return log


# --------------------------------------------------------------------------
# The files that lose their kit part


def remove_held(repo: Path) -> list[str]:
    """Remove the kit code a 2.x repository holds."""
    record = json.loads((repo / cq.SOURCE_JSON).read_text(encoding="utf-8"))
    paths = [str(e["path"]) for e in record.get("files") or [] if isinstance(e, dict)]
    log = []
    for rel in [*paths, *HELD_FILES]:
        path = repo / rel
        kept = rel in paths and not rel.endswith((".py", ".txt"))
        if kept or not path.is_file() or not path.resolve().is_relative_to(repo.resolve()):
            continue
        path.unlink()
        log.append(f"removed {rel}")
    folder = repo / ".github" / "commit-check"
    if folder.is_dir():
        shutil.rmtree(folder)
        log.append("removed .github/commit-check/")
    return log


def drop_markers(text: str) -> str:
    """A file without the managed-block marker lines."""
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not (cq.MARK_START.match(line.rstrip("\n")) or cq.MARK_END.match(line.rstrip("\n")))
    )


def split_entries(lines: list[str], opener: re.Pattern[str]) -> list[list[str]]:
    """Lines cut at each opener, the comment lines right above one kept with it."""
    out: list[list[str]] = [[]]
    for line in lines:
        if opener.match(line):
            above: list[str] = []
            while out[-1] and out[-1][-1].lstrip().startswith("#"):
                above.insert(0, out[-1].pop())
            out.append(above)
        out[-1].append(line)
    return out


def hook_list(text: str, kit: cq.Kit, profiles: list[str]) -> str:
    """A pre-commit configuration with the kit's hook entry in place of the held hooks."""
    head, sep, rest = drop_markers(text).partition("\nrepos:")
    first, _, body = rest.partition("\n")
    entries = split_entries(body.splitlines(keepends=True), re.compile(r"^  - repo:"))
    kept: list[str] = entries[0]
    for entry in entries[1:]:
        hooks = split_entries(entry, re.compile(r"^      - id:"))
        if not any(re.match(r"^  - repo:\s*local\b", line) for line in hooks[0]):
            kept += entry
            continue
        stay = []
        for hook in hooks[1:]:
            named = next(m for m in map(re.compile(r"^      - id:\s*(\S+)").match, hook) if m)
            if named.group(1) not in HELD_HOOKS:
                stay += hook
        if stay:
            kept += [line for line in hooks[0] if not line.lstrip().startswith("#")] + stay
    ids = [hook for hook, profile in run_form.KIT_HOOKS.items() if profile in profiles]
    entry_text = (
        "\n  # The quality kit's hooks (kleidos-dev/.github, docs/quality.md): nothing of\n"
        "  # them is held here, and Dependabot moves the rev.\n"
        f"  - repo: {run_form.KIT_HOOKS_URL}\n"
        f"    rev: v{kit.version()}\n"
        "    hooks:\n" + "".join(f"      - id: {hook}\n" for hook in ids)
    )
    return head + sep + first + entry_text + "".join(kept)


def rules_link(text: str) -> str:
    """AGENTS.md with a link in place of the organization-rules block."""
    found = cq.find_block(text, agent_docs.BLOCK_ID)
    if found is None:
        return text
    start, end, _inner = found
    lines = text.splitlines(keepends=True)
    return "".join(lines[:start]) + RULES_SECTION + "".join(lines[end + 1 :])


# --------------------------------------------------------------------------
# The gate workflow


def kit_file(job: dict[str, Any]) -> str:
    """The 2.x kit workflow a job calls, or ""."""
    found = run_form.KIT_REF.match(str(job.get("uses", "")))
    return found["path"].rpartition("/")[2] if found else ""


def quoted(value: object) -> str:
    """A scalar as YAML reads it back, on one line."""
    return json.dumps(str(value).strip(), ensure_ascii=False)


def check_inputs(old: dict[str, list[dict[str, Any]]], profiles: list[str]) -> dict[str, str]:
    """check.yml's inputs, from what the 2.x callers passed."""

    def given(name: str) -> dict[str, Any]:
        calls = old.get(name) or [{}]
        values: dict[str, Any] = calls[0].get("with") or {}
        return values

    tests, types, node = (
        given("reusable-python-tests.yml"),
        given("reusable-mypy.yml"),
        given("reusable-eslint.yml"),
    )
    out: dict[str, str] = {}
    if "install" in tests:
        out["install"] = quoted(tests["install"])
    elif "run" in tests:
        out["python"] = quoted("-r requirements.txt")
    if "run" in tests:
        out["tests"] = quoted(tests["run"])
    for name in ("coverage-report", "coverage-artifact", "timeout-minutes"):
        if name in tests:
            out[name] = quoted(tests[name]) if name != "timeout-minutes" else str(tests[name])
    before = tests.get("install", "python -m pip install -r requirements.txt")
    if "install" in types and types["install"] != before:
        out["types-install" if tests else "install"] = quoted(types["install"])
    if "python" not in profiles:
        out["types"] = "false"
    if "ts" in profiles:
        out["node-directory"] = quoted(node.get("working-directory", "."))
        if "projects" in node:
            out["node-projects"] = quoted(node["projects"])
    return out


def call(job_id: str, title: str, workflow: str, extra: str, inputs: dict[str, str]) -> str:
    """One caller job of the run form."""
    text = f'  {job_id}:\n    name: "{title}"\n{extra}'
    text += f"    uses: {cq.KIT_REPO}/{WORKFLOWS}/{workflow}@v3\n"
    if inputs:
        text += "    with:\n" + "".join(f"      {k}: {v}\n" for k, v in inputs.items())
    grants = run_form.ALLOWED_PERMISSIONS.get(workflow, run_form.READ_CODE)
    text += "    permissions:\n" + "".join(f"      {k}: {v}\n" for k, v in grants.items())
    return text + "\n"


def convert_ci(text: str, kit: cq.Kit, profiles: list[str]) -> str:
    """A 2.x gate workflow in the run form: its own jobs kept, the kit's called by name."""
    parsed = yaml.safe_load(text)
    jobs: dict[str, dict[str, Any]] = parsed["jobs"]
    old: dict[str, list[dict[str, Any]]] = {}
    new_of: dict[str, str] = {}
    for job_id, job in jobs.items():
        name = kit_file(job)
        taken = name in NEW_JOB and not (name in old and NEW_JOB[name] == "check")
        if taken:
            new_of[job_id] = NEW_JOB[name]
        if name:
            old.setdefault(name, []).append(job)
    head, _sep, body = text.partition("\njobs:\n")
    blocks = split_entries(body.splitlines(keepends=True), JOB_LINE)
    own: list[str] = []
    skippable: list[str] = []
    kept_ids: list[str] = []
    for block in blocks[1:]:
        named = next(m for m in map(JOB_LINE.match, block) if m)
        job_id = named.group("id")
        if job_id in new_of:
            continue
        kept_ids.append(job_id)
        if "if" in jobs[job_id]:
            skippable.append(job_id)
        own += [point_at(rewrite_needs(line, new_of), jobs[job_id]) for line in block]
    skip = (old.get("reusable-lint.yml") or [{}])[0].get("with") or {}
    quick_inputs = {"skip": quoted(skip["skip"])} if "skip" in skip else {}
    callers = call("quick", "⚡ Quick", run_form.QUICK, "", quick_inputs)
    callers += call(
        "check", "🧪 Check", run_form.CHECK, "    needs: quick\n", check_inputs(old, profiles)
    )
    ids = ["quick", "check", *kept_ids]
    if "reusable-sonarcloud.yml" in old:
        sonar_old = old["reusable-sonarcloud.yml"][0]
        needs = ["check"] + [n for n in run_form.words(sonar_old.get("needs")) if n in kept_ids]
        inputs = {k: quoted(v) for k, v in (sonar_old.get("with") or {}).items()}
        extra = f"    needs: [{', '.join(needs)}]\n    if: github.event_name != 'schedule'\n"
        callers += call("sonar", "📊 Sonar", run_form.SONAR, extra, inputs)
        ids.append("sonar")
        skippable.append("sonar")
    return (
        head
        + "\n\njobs:\n"
        + callers
        + "".join(own).strip("\n")
        + ("\n\n" if own else "")
        + gate_text(kit, ids, skippable)
    ).replace("\n\n\njobs:", "\n\njobs:")


def rewrite_needs(line: str, new_of: dict[str, str]) -> str:
    """A `needs:` line with the 2.x kit jobs replaced by the ones that took their checks."""
    lead, sep, value = line.partition("needs:")
    ids = value.strip().removeprefix("[").removesuffix("]")
    if lead != "    " or not sep or not re.fullmatch(r"[\w ,-]+", ids):
        return line
    new = [new_of.get(i, i) for i in re.split(r"[ ,]+", ids.strip())]
    return f"    needs: [{', '.join(dict.fromkeys(new))}]\n"


def point_at(line: str, job: dict[str, Any]) -> str:
    """A `uses:` line of a kit workflow the repository keeps calling itself, at the branch."""
    if not kit_file(job) or not line.startswith("    uses:"):
        return line
    return line.partition("@")[0] + "@v3\n"


def gate_text(kit: cq.Kit, ids: list[str], skippable: list[str]) -> str:
    """The kit's gate job, for these jobs."""
    model = kit.read(run_form.MODEL_CI).decode("utf-8")
    gate = model[model.index("  done:\n") :]
    gate = re.sub(r"needs: \[[^\]]*\]", f"needs: [{', '.join(ids)}]", gate, count=1)
    return re.sub(r"MAY_SKIP: .*", f"MAY_SKIP: {' '.join(skippable) or '""'}", gate, count=1)


def gate_workflow(repo: Path) -> Path | None:
    """The workflow that calls the 2.x lint job."""
    for path in sorted((repo / WORKFLOWS).glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        jobs = data.get("jobs") if isinstance(data, dict) else None
        for job in (jobs or {}).values():
            if isinstance(job, dict) and kit_file(job) == "reusable-lint.yml":
                return path
    return None


# --------------------------------------------------------------------------
# The switch


def switch(repo: Path, kit: cq.Kit, commit: str, today: dt.date) -> list[str]:
    """Bring a kit 2.x repository to the run form; return what was done and what is left."""
    record_path = repo / cq.SOURCE_JSON
    if not record_path.is_file() or cq.record_of(cq.Repo(repo)) is not None:
        return ["nothing to switch: this repository holds no kit 2.x copies"]
    log = remove_held(repo)
    for rel in ("pyproject.toml", ".typos.toml"):
        path = repo / rel
        if path.is_file():
            own_files.write(repo, rel, drop_markers(path.read_text(encoding="utf-8")))
    agents = repo / "AGENTS.md"
    if agents.is_file():
        own_files.write(repo, "AGENTS.md", rules_link(agents.read_text(encoding="utf-8")))
        log.append("AGENTS.md links the organization rules")
    log += write_configs(repo, kit, commit, today)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    profiles = record["kit"]["profiles"]
    hooks = repo / PRE_COMMIT
    listed = hook_list(hooks.read_text(encoding="utf-8"), kit, profiles)
    own_files.write(repo, PRE_COMMIT, listed)
    log.append(f"{PRE_COMMIT} takes the kit's hooks at v{kit.version()}")
    dependabot = repo / ".github" / "dependabot.yml"
    if dependabot.is_file() and "package-ecosystem: pre-commit" not in (
        old := dependabot.read_text(encoding="utf-8")
    ):
        moved = old.rstrip("\n") + "\n" + DEPENDABOT_ENTRY
        own_files.write(repo, ".github/dependabot.yml", moved)
        log.append("dependabot.yml moves the hook revisions")
    comment = kit.read("quality/templates/run/commit-check-comment.yml").decode("utf-8")
    caller = spdx_headers.set_year(comment, str(today.year))
    own_files.write(repo, f"{WORKFLOWS}/commit-check-comment.yml", caller)
    gate = gate_workflow(repo)
    if gate is None:
        log.append("left: no gate workflow found; write it from quality/templates/run/ci.yml")
    else:
        converted = convert_ci(gate.read_text(encoding="utf-8"), kit, profiles)
        rel = gate.relative_to(repo).as_posix()
        own_files.write(repo, rel, converted)
        log.append(f"{rel} calls the entry workflows")
    log += [
        "left: read the gate workflow's comments and the needs of the repository's own jobs",
        "left: AGENTS.md, README.md and the docs that name the copies, the sync or the drift job",
        "left: waivers of tool pins go (an old pin is a note now); the license lines are fixed",
    ]
    return log


def main(argv: list[str] | None = None) -> int:
    """The command line."""
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", type=Path, metavar="REPO", help="the whole switch")
    group.add_argument("--configs", type=Path, metavar="REPO", help="the base configurations")
    ap.add_argument("--commit", help="the kit commit to note (the checkout's, by default)")
    args = ap.parse_args(argv)
    repo = args.write or args.configs
    if not (repo / ".git").exists():
        print(f"kit_switch: {repo} is not the top of a git work tree", file=sys.stderr)
        return 2
    status = ["git", "status", "--porcelain"]
    if args.write and subprocess.run(status, cwd=repo, capture_output=True, check=True).stdout:
        print(f"kit_switch: {repo} has uncommitted changes: commit them first", file=sys.stderr)
        return 2
    kit = cq.DirKit(KIT)
    commit = args.commit or head_of(KIT)
    today = dt.datetime.now(tz=dt.UTC).date()
    work = switch if args.write else write_configs
    try:
        log = work(repo.resolve(), kit, commit, today)
    except own_files.RefusedError as exc:
        print(f"kit_switch: {exc}", file=sys.stderr)
        return 2
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
