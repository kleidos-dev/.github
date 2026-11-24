#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""The run form: a repository that calls the kit by name and holds none of its code.

From kit 3.0.0 a repository runs the kit instead of copying it (docs/quality.md,
"How a repository runs the kit"): its CI calls the entry workflows at the branch
v<major>, its hooks come from the kit's hook repository at a release tag, and it
holds only the base configurations a tool reads from its disk, recorded like any
other copy that crosses between repositories. check_quality.py imports this
module when .github/quality/SOURCE.json is such a record (and in
kleidos-dev/.github for its own workflows), and it checks:

  record       the base configurations the profiles call for are there, are
               bytes some kit release holds, and are not edited in place; so
               is every other vendored copy (schema kleidos.vendored-copy/1)
  kit-code     no kit script, managed block, drift caller or commit-check
               folder is left in the tree
  workflows    the entry workflows are called, at the branch, on every pull
               request and push, with the permissions and secrets they need
               and no more
  gate         one job named "✅ Check" needs every other job of its file and
               fails unless they succeeded
  permissions  no workflow can write a check or a commit status
  hooks        the kit's hook entry at a release tag, and every third-party
               hook of the kit's canonical list, unweakened
  dependabot   the pre-commit ecosystem runs, and leaves the kit's majors to people

A repository is never reported for being behind a newer release.
"""

from __future__ import annotations

import datetime as dt
import json
import posixpath
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

import check_quality as cq
import yaml

if TYPE_CHECKING:
    from collections.abc import Iterable

SCHEMA = "kleidos.vendored-copy/1"
DIGESTS = "quality/config-digests.json"
MODEL_CI = "quality/templates/run/ci.yml"
QUICK, CHECK, SONAR = "quick.yml", "check.yml", "sonar.yml"
ENTRY = (QUICK, CHECK, SONAR)
COMMENT = "reusable-commit-check-comment.yml"
GATE = "✅ Check"
GATE_KEYS = {"name", "needs", "if", "runs-on", "timeout-minutes", "permissions", "steps"}
GATE_STEP_KEYS = {"name", "shell", "env", "run"}
# The one reference of our own that is a name: the branch the release moves.
KIT_REF = re.compile(
    r"kleidos-dev/\.github/(?P<path>[^\s'\"@#]*)@(?P<ref>[^\s'\"#]+)", re.IGNORECASE
)
KIT_WORKFLOW = re.compile(r"^\.github/workflows/(?P<file>[\w.-]+\.ya?ml)$")
SELF_WORKFLOW = re.compile(r"^\./\.github/workflows/(?P<file>[\w.-]+\.ya?ml)$")
KIT_HOOKS_URL = "https://github.com/kleidos-dev/.github"
KIT_HOOKS = {"kleidos-kit": "base", "kleidos-commit-msg": "base", "kleidos-mypy": "python"}
DENY_INPUT = "${{ secrets.KLEIDOS_DENY_EXTRA }}"
# What a caller of each kit workflow may grant it; anything else may only read the code.
READ_CODE = {"contents": "read"}
ALLOWED_PERMISSIONS = {
    SONAR: {"contents": "read", "id-token": "write"},
    "reusable-sonarcloud.yml": {"contents": "read", "id-token": "write"},
    COMMENT: {"actions": "read", "contents": "read", "pull-requests": "write"},
}
# A token that writes either can post the required check's name on a commit.
FORGES_CHECKS = ("checks", "statuses")
MARKED_FILES = (".pre-commit-config.yaml", "pyproject.toml", ".typos.toml", "AGENTS.md")
RETIRED_PATHS = (
    ".github/workflows/quality-drift.yml",
    ".github/commit-check/",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REPO_SLUG = re.compile(r"^[\w.-]+/[\w.-]+$")


def is_record(data: Any) -> bool:
    """Whether a parsed JSON file is a record of vendored copies."""
    return isinstance(data, dict) and data.get("schema") == SCHEMA


def branch_of(version: str) -> str:
    """The branch that carries a kit version's major: 3.1.0 is called at v3."""
    return f"v{version.split('.')[0]}"


def base_configs(kit: cq.Kit, profiles: Iterable[str]) -> dict[str, str]:
    """The base configurations these profiles call for: target -> the kit file it copies."""
    chosen = set(profiles)
    return {
        str(entry["target"]): str(entry["source"])
        for entry in kit.manifest().get("copy", [])
        if entry["profile"] in chosen
        and "requires" not in entry
        and not str(entry["source"]).endswith(cq.PY_SUFFIXES)
    }


# --------------------------------------------------------------------------
# Records of copies


def record_problems(data: dict[str, Any], today: dt.date) -> list[str]:
    """What is wrong with a vendored-copy record's own fields."""
    out: list[str] = []
    upstream = data.get("upstream")
    if not isinstance(upstream, dict):
        upstream = {}
    if not REPO_SLUG.match(str(upstream.get("repo", ""))):
        out.append("upstream.repo must name the source repository (owner/name)")
    commit = upstream.get("commit")
    if commit is not None and not cq.SHA40.match(str(commit)):
        out.append("upstream.commit must be a 40-hex commit (a note, never a gate) or null")
    mode = data.get("mode")
    if mode == "frozen":
        if not str(data.get("reason") or "").strip():
            out.append("a frozen copy says why in one sentence (reason)")
    elif mode != "follow":
        out.append('mode must be "follow" or "frozen"')
    limit = data.get("max_age_days")
    if limit is not None and (type(limit) is not int or limit < 1):
        out.append("max_age_days must be a whole number of days")
    try:
        taken = dt.date.fromisoformat(str(data.get("taken", "")))
    except ValueError:
        out.append("taken must be the date of the copy (YYYY-MM-DD)")
    else:
        # A day of grace: the date is written where the copy is taken.
        if taken > today + dt.timedelta(days=1):
            out.append(f"taken is in the future ({taken})")
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        out.append("files must name every copied file with its SHA-256")
    elif not all(SHA256.match(str(digest)) for digest in files.values()):
        out.append("files must give each file's SHA-256")
    return out


def record_targets(rel: str, data: dict[str, Any]) -> dict[str, str | None]:
    """Each file a record names -> its path in the repository, None when it leaves it."""
    base = "" if data.get("root") == "." else posixpath.dirname(rel)
    out: dict[str, str | None] = {}
    files = data.get("files")
    for name in files if isinstance(files, dict) else ():
        target = posixpath.normpath(posixpath.join(base, str(name)))
        inside = not target.startswith(("../", "/")) and target not in ("..", ".")
        out[str(name)] = target if inside else None
    return out


def check_records(repo: cq.Repo, today: dt.date, report: cq.Report) -> None:
    """Every vendored copy of the tree is the bytes its record names."""
    for rel in repo.files:
        if PurePosixPath(rel).name != "SOURCE.json" or "fixtures" in PurePosixPath(rel).parts:
            continue
        try:
            data = json.loads(repo.text(rel))
        except (OSError, ValueError) as exc:
            report.add("record", rel, f"cannot be read: {exc}")
            continue
        if not is_record(data):
            schema = data.get("schema") if isinstance(data, dict) else None
            if str(schema).startswith(SCHEMA.partition("/")[0] + "/"):
                report.add("record", rel, f"schema {schema} is not {SCHEMA}")
            continue
        for problem in record_problems(data, today):
            report.add("record", rel, problem)
        for name, target in record_targets(rel, data).items():
            if target is None:
                report.add("record", rel, f"names {name}, outside this repository")
            elif not repo.exists(target):
                report.add("record", rel, f"names {target}, which is not in the tree")
            elif cq.sha256(repo.path(target).read_bytes()) != data["files"][name]:
                report.add(
                    "record",
                    target,
                    f"edited in place: it is not the copy {rel} records (change it where it"
                    " comes from, then refresh)",
                )


def load(repo: cq.Repo, data: dict[str, Any], report: cq.Report) -> dict[str, Any]:
    """The kit's own record as the fields check_quality.py's other checks read."""
    kit = data.get("kit")
    kit = kit if isinstance(kit, dict) else {}
    profiles = kit.get("profiles")
    if not isinstance(profiles, list) or "base" not in profiles:
        report.add(
            "record", cq.SOURCE_JSON, "kit.profiles must be a list of profiles that includes base"
        )
        profiles = ["base"]
    for name in profiles:
        if name not in cq.KNOWN_PROFILES:
            report.add("record", cq.SOURCE_JSON, f"unknown profile {name!r}")
    upstream = data.get("upstream")
    if not isinstance(upstream, dict) or upstream.get("repo") != cq.KIT_REPO:
        report.add("record", cq.SOURCE_JSON, f"upstream.repo must be {cq.KIT_REPO}")
    if data.get("root") != ".":
        report.add(
            "record", cq.SOURCE_JSON, 'root must be ".": the files are named from the top folder'
        )
    if data.get("mode") != "follow":
        report.add("record", cq.SOURCE_JSON, 'mode must be "follow"')
    return {
        "version": str(kit.get("version", "?")),
        "commit": None,
        "profiles": [str(p) for p in profiles],
        "files": [],
        "blocks": [],
    }


def check_configs(
    repo: cq.Repo, data: dict[str, Any], profiles: list[str], kit: cq.Kit, report: cq.Report
) -> None:
    """The kit's record holds the base configurations of its profiles, at released bytes."""
    want = base_configs(kit, profiles)
    files = data.get("files")
    have = {str(k): str(v) for k, v in files.items()} if isinstance(files, dict) else {}
    sources = data.get("sources")
    sources = sources if isinstance(sources, dict) else {}
    released: dict[str, list[str]] = json.loads(kit.read(DIGESTS).decode("utf-8"))
    refresh = "run the kit's tools/ecosystem.py refresh"
    for target in sorted(want.keys() - have.keys()):
        report.add("record", cq.SOURCE_JSON, f"the profiles call for {target}: {refresh}")
    for target in sorted(have.keys() - want.keys()):
        report.add("record", cq.SOURCE_JSON, f"records {target}, not a base configuration of them")
    for target in sorted(have.keys() & want.keys()):
        if sources.get(target) != want[target]:
            report.add(
                "record",
                cq.SOURCE_JSON,
                f"sources must say that {target} is the kit's {want[target]}",
            )
        if have[target] not in released.get(want[target], []):
            report.add(
                "record",
                target,
                f"its recorded digest is no release's {want[target]}: {refresh}",
            )
    for rel in repo.files:
        if cq.under(rel, cq.KIT_DIR) and rel not in cq.KIT_DIR_OWN and rel not in have:
            report.add(
                "kit-dir",
                rel,
                f"{cq.KIT_DIR} holds the base configurations, their record and the waivers only",
            )


def check_kit_code(repo: cq.Repo, kit: cq.Kit, report: cq.Report) -> None:
    """No kit script, managed block or drift caller is left: the kit is run, not held."""
    scripts = {
        cq.sha256(kit.read(str(entry["source"]))): str(entry["source"])
        for entry in kit.manifest().get("copy", [])
        if str(entry["source"]).endswith(".py")
    }
    for rel in repo.files:
        if rel.startswith(RETIRED_PATHS):
            report.add("kit-code", rel, "the kit is run, not held: remove it")
        elif rel.startswith(cq.KIT_DIR) and rel.endswith(".py"):
            report.add("kit-code", rel, "a kit script is run from the kit, never held: remove it")
        elif PurePosixPath(rel).name == cq.KIT_TEST_COPY[0]:
            report.add("kit-code", rel, "the drift test has nothing to compare: remove it")
        elif rel.endswith(".py") and cq.sha256(repo.path(rel).read_bytes()) in scripts:
            report.notes.append(f"{rel} holds the bytes of a kit script: run the kit's instead")
    for rel in MARKED_FILES:
        if not repo.exists(rel):
            continue
        for num, line in enumerate(repo.text(rel).splitlines(), 1):
            if cq.MARK_START.match(line) or cq.MARK_END.match(line):
                report.add(
                    "kit-code",
                    f"{rel}:{num}",
                    "a managed-block marker: the text is the repository's own now, drop the marker",
                )


# --------------------------------------------------------------------------
# Workflows


@dataclass(frozen=True)
class Workflow:
    """One workflow file, parsed."""

    rel: str
    data: dict[Any, Any]
    jobs: dict[str, dict[str, Any]]
    triggers: dict[str, Any]


def workflows(repo: cq.Repo) -> list[Workflow]:
    """The workflow files that parse (check_ci reports the others)."""
    out: list[Workflow] = []
    for rel in cq.workflow_files(repo):
        try:
            data = yaml.safe_load(repo.text(rel))
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        jobs = data.get("jobs")
        jobs = jobs if isinstance(jobs, dict) else {}
        kept = {str(k): v for k, v in jobs.items() if isinstance(v, dict)}
        out.append(Workflow(rel, data, kept, cq.workflow_triggers(data)))
    return out


def used(workflow: Workflow) -> Iterator[tuple[str, str]]:
    """(job id, reference) of every `uses:` of a workflow, jobs' and steps'."""
    for job_id, job in workflow.jobs.items():
        if "uses" in job:
            yield job_id, str(job["uses"])
        steps = job.get("steps")
        for step in steps if isinstance(steps, list) else ():
            if isinstance(step, dict) and "uses" in step:
                yield job_id, str(step["uses"])


def reference_problem(reference: str, branch: str, kit: cq.Kit) -> str | None:
    """Why a reference to the kit is not its workflow at its branch, or None."""
    found = KIT_REF.search(reference)
    if found is None:
        return None
    ref, path = found["ref"], found["path"]
    if not reference.startswith("kleidos-dev/.github/"):
        return f"{reference} must spell kleidos-dev/.github/ in lower case"
    if cq.SHA40.match(ref):
        return f"{path} is called at a commit: the kit is called by its name, @{branch}"
    if re.fullmatch(r"v\d+\.\d+.*", ref):
        return (
            f"{path} is called at the tag {ref}: a workflow called at an annotated tag cannot"
            f" call the kit's own workflows beside it; use the branch, @{branch}"
        )
    if ref != branch:
        return f"{path} is called at {ref}: the kit is called at @{branch} and nothing else"
    named = KIT_WORKFLOW.match(path)
    if named is None or (named["file"] not in ENTRY and not named["file"].startswith("reusable-")):
        return f"{path} is not a workflow the kit offers"
    try:
        kit.read(path)
    except OSError:
        return f"the kit has no {path}"
    return None


def check_references(
    repo: cq.Repo, found: list[Workflow], branch: str, kit: cq.Kit, report: cq.Report
) -> None:
    """Every reference to the kit is one of its workflows at the branch, exactly.

    zizmor's policy lets a reference to the kit be a name, any name; this is
    the check that holds it to the one branch. Workflows are read parsed, so
    no YAML spelling hides a reference; local actions are read as text.
    """
    for workflow in found:
        for job_id, reference in used(workflow):
            problem = reference_problem(reference, branch, kit)
            if problem:
                report.add("workflows", f"{workflow.rel} jobs.{job_id}", problem)
    for rel in repo.files:
        if PurePosixPath(rel).name not in ("action.yml", "action.yaml"):
            continue
        for num, line in enumerate(repo.text(rel).splitlines(), 1):
            if KIT_REF.search(line) and not line.lstrip().startswith("#"):
                report.add(
                    "workflows",
                    f"{rel}:{num}",
                    "an action cannot call the kit: a job of a workflow does",
                )


def callers(found: list[Workflow], self_ref: bool) -> dict[str, list[cq.Caller]]:
    """Kit workflow file name -> the jobs that call it (by ./ path in the kit's home)."""
    out: dict[str, list[cq.Caller]] = {}
    for workflow in found:
        if self_ref and PurePosixPath(workflow.rel).name in ENTRY:
            continue  # the kit's own insides, which its tests hold
        for job_id, job in workflow.jobs.items():
            reference = str(job.get("uses", ""))
            if self_ref:
                named = SELF_WORKFLOW.match(reference)
            else:
                remote = KIT_REF.fullmatch(reference)
                named = KIT_WORKFLOW.match(remote["path"]) if remote else None
            if named:
                caller = cq.Caller(workflow.rel, job_id, job, workflow.jobs, workflow.triggers)
                out.setdefault(named["file"], []).append(caller)
    return out


def required(repo: cq.Repo) -> dict[str, tuple[str, ...]]:
    """The kit workflows every repository calls -> the events their callers run on."""
    out = {
        QUICK: cq.DEFAULT_TRIGGERS,
        CHECK: cq.DEFAULT_TRIGGERS,
        COMMENT: cq.REQUIRED_TRIGGERS[COMMENT],
    }
    if repo.exists("sonar-project.properties"):
        out[SONAR] = cq.DEFAULT_TRIGGERS
    return out


def check_callers(
    repo: cq.Repo, by_file: dict[str, list[cq.Caller]], profiles: list[str], report: cq.Report
) -> None:
    """Each required kit workflow is called by a job that runs on every event it must."""
    for name, events in required(repo).items():
        calls = by_file.get(name, [])
        if not calls:
            report.add("workflows", ".github/workflows/", f"no workflow calls the kit's {name}")
            continue
        gaps = [cq.caller_gap(c, events) for c in calls]
        if all(gaps):
            for call, gap in zip(calls, gaps, strict=True):
                report.add(
                    "workflows",
                    f"{call.workflow} jobs.{call.job_id}",
                    f"calls {name} but {gap}, so the check may never run (no waiver)",
                )
    for call in by_file.get(CHECK, []):
        where = f"{call.workflow} jobs.{call.job_id}"
        given = call.job.get("with")
        given = given if isinstance(given, dict) else {}
        types = given.get("types", True)
        if "python" in profiles and (types is False or str(types).lower() == "false"):
            report.add("workflows", where, "types: false, but the tree holds Python (no waiver)")
        if "ts" in profiles and not str(given.get("node-directory") or "").strip():
            report.add("workflows", where, "node-directory is empty, but the tree holds TypeScript")
    local = local_hooks(repo)
    for call in by_file.get(QUICK, []):
        where = f"{call.workflow} jobs.{call.job_id}"
        given = call.job.get("with")
        given = given if isinstance(given, dict) else {}
        for hook in cq.refused_skips(str(given.get("skip", "")), set(KIT_HOOKS)):
            report.add(
                "workflows",
                where,
                f"skip names the kit hook {hook}: only the repository's own hooks may be skipped",
            )
        for hook in str(given.get("deny-hooks", "")).replace(",", " ").split():
            if hook not in local:
                report.add(
                    "workflows",
                    where,
                    f"deny-hooks names {hook}, which is not a local hook: no third party's code"
                    " reads the deny-list",
                )


def local_hooks(repo: cq.Repo) -> set[str]:
    """The ids and aliases of a repository's own hooks."""
    try:
        have = hook_lists(repo.text(".pre-commit-config.yaml"))
    except OSError, yaml.YAMLError:
        return set()
    return {hook_key(h["hook"]) for h in have if h["url"] == "local"}


def check_grants(
    found: list[Workflow], by_file: dict[str, list[cq.Caller]], report: cq.Report
) -> None:
    """A kit caller grants what the workflow needs, by name: no write, no inherited secret."""
    tops = {w.rel: w.data.get("permissions") for w in found}
    for name, calls in by_file.items():
        allowed = ALLOWED_PERMISSIONS.get(name, READ_CODE)
        for call in calls:
            where = f"{call.workflow} jobs.{call.job_id}"
            granted = call.job.get("permissions", tops.get(call.workflow))
            if not isinstance(granted, dict):
                report.add("workflows", where, f"must state permissions: at most {shown(allowed)}")
            else:
                extra = {k: v for k, v in granted.items() if v != "none" and allowed.get(k) != v}
                if extra:
                    report.add(
                        "workflows",
                        where,
                        f"grants {shown(extra)} to the kit's {name}: at most {shown(allowed)}",
                    )
            secrets = call.job.get("secrets")
            if secrets is None or (name == QUICK and secrets == {"deny": DENY_INPUT}):
                continue
            report.add(
                "workflows",
                where,
                f"passes secrets to the kit's {name}: only quick.yml takes one, as"
                f" deny: {DENY_INPUT}, never inherit",
            )


def shown(permissions: dict[str, str]) -> str:
    """A permissions mapping on one line."""
    return ", ".join(f"{k}: {v}" for k, v in permissions.items()) or "none"


def check_forgery(found: list[Workflow], report: cq.Report) -> None:
    """No workflow token can post the required check's name (checks or statuses: write)."""
    for workflow in found:
        scopes = [(workflow.rel, workflow.data.get("permissions"))]
        scopes += [
            (f"{workflow.rel} jobs.{job_id}", job.get("permissions"))
            for job_id, job in workflow.jobs.items()
        ]
        for where, granted in scopes:
            if granted == "write-all":
                named = ["write-all"]
            elif isinstance(granted, dict):
                named = [f"{k}: write" for k in FORGES_CHECKS if granted.get(k) == "write"]
            else:
                named = []
            for grant in named:
                report.add(
                    "permissions",
                    where,
                    f"{grant}: a job with it can post a passing {GATE} on any commit (no waiver)",
                )


# --------------------------------------------------------------------------
# The gate


def model_gate(kit: cq.Kit) -> dict[str, Any]:
    """The kit's own gate job, from its model CI."""
    model = yaml.safe_load(kit.read(MODEL_CI).decode("utf-8"))
    gate: dict[str, Any] = next(j for j in model["jobs"].values() if j["name"] == GATE)
    return gate


def words(value: Any) -> list[str]:
    """The job ids of a `needs:` or of MAY_SKIP: one, a list, or words in a string."""
    if isinstance(value, list):
        return [str(v) for v in value]
    return str(value or "").split()


def gate_job(workflow: Workflow) -> str | None:
    """The id of a workflow's gate job, or None."""
    return next((i for i, job in workflow.jobs.items() if job.get("name") == GATE), None)


def check_gate(found: list[Workflow], kit: cq.Kit, report: cq.Report) -> None:
    """One job named "✅ Check" needs every other job of its file and fails with any of them.

    It is the one required check of the repository, and GitHub counts a
    required check that was skipped as passed, so the job always runs and
    reads the result of each job it needs.
    """
    gates: list[tuple[Workflow, str]] = []
    for workflow in found:
        for job_id, job in workflow.jobs.items():
            name = str(job.get("name", ""))
            if name == GATE:
                gates.append((workflow, job_id))
            elif name.startswith(GATE[0]):
                report.add(
                    "gate",
                    f"{workflow.rel} jobs.{job_id}",
                    f"only the gate's name starts with {GATE[0]} (it is the required check)",
                )
    if not gates:
        report.add("gate", ".github/workflows/", f'no job is named "{GATE}", the required check')
        return
    for workflow, job_id in gates[1:]:
        report.add("gate", f"{workflow.rel} jobs.{job_id}", f'a second job named "{GATE}"')
    workflow, gate_id = gates[0]
    gate = workflow.jobs[gate_id]
    where = f"{workflow.rel} jobs.{gate_id}"
    for problem in [*gate_shape(gate, model_gate(kit)), *gate_needs(workflow, gate_id)]:
        report.add("gate", where, problem)
    for event in cq.DEFAULT_TRIGGERS:
        gap = (
            cq.trigger_gap(event, workflow.triggers[event])
            if event in workflow.triggers
            else f"{workflow.rel} does not run on {event}"
        )
        if gap:
            report.add("gate", where, gap)


def gate_shape(gate: dict[str, Any], model: dict[str, Any]) -> Iterator[str]:
    """How a gate job differs from the kit's model of it."""
    extra = sorted(str(k) for k in gate.keys() - GATE_KEYS)
    if extra:
        yield f"sets {', '.join(extra)}: the gate is the kit's model job and nothing more"
    if cq.normalized_if(gate.get("if", "")) != "always()":
        yield "needs `if: always()`: a required check that is skipped counts as passed"
    for key in ("runs-on", "permissions"):
        if gate.get(key) != model[key]:
            yield f"{key} must be {model[key] or '{}'}"
    steps = gate.get("steps")
    step = steps[0] if isinstance(steps, list) and len(steps) == 1 else None
    if not isinstance(step, dict):
        yield "has one step, the kit's"
        return
    wanted = model["steps"][0]
    if step.keys() - GATE_STEP_KEYS or step.get("shell") != wanted["shell"]:
        yield "its step sets name, shell: bash, env and run, as the kit's"
    if str(step.get("run", "")).strip() != wanted["run"].strip():
        yield "its step must run the kit's script, unchanged (quality/templates/run/ci.yml)"
    env = step.get("env")
    env = env if isinstance(env, dict) else {}
    if cq.normalized_if(env.get("NEEDS", "")) != "toJSON(needs)":
        yield "its step reads NEEDS: ${{ toJSON(needs) }}"
    if env.keys() - {"NEEDS", "MAY_SKIP"}:
        yield "its step's env holds NEEDS and MAY_SKIP only"


def gate_needs(workflow: Workflow, gate_id: str) -> Iterator[str]:
    """Which jobs of the file a gate does not need, or lets pass when skipped without a reason."""
    gate = workflow.jobs[gate_id]
    others = [job_id for job_id in workflow.jobs if job_id != gate_id]
    missing = sorted(set(others) - set(words(gate.get("needs"))))
    if missing:
        yield f"does not need {', '.join(missing)}: it needs every other job of its file"
    steps = gate.get("steps")
    step = steps[0] if isinstance(steps, list) and steps and isinstance(steps[0], dict) else {}
    env = step.get("env")
    may_skip = words(env.get("MAY_SKIP") if isinstance(env, dict) else "")
    for job_id in may_skip:
        job = workflow.jobs.get(job_id)
        if job is None:
            yield f"MAY_SKIP names {job_id}, which is not a job of this file"
        elif "if" not in job and not set(words(job.get("needs"))) & set(may_skip):
            yield f"MAY_SKIP names {job_id}, which has no condition: it is never skipped alone"
        elif cq.never_runs(job):
            yield f"MAY_SKIP names {job_id}, whose condition is false: it never runs"
        elif any(str(job.get("uses", "")).split("@")[0].endswith(f"/{n}") for n in (QUICK, CHECK)):
            yield f"MAY_SKIP names {job_id}: the kit's {QUICK} and {CHECK} always run"


# --------------------------------------------------------------------------
# Hooks and Dependabot


def hook_lists(text: str) -> list[dict[str, Any]]:
    """Every hook of a pre-commit configuration, each with its repository's url and rev."""
    parsed = yaml.safe_load(text)
    repos = parsed.get("repos") if isinstance(parsed, dict) else None
    out: list[dict[str, Any]] = []
    for entry in repos if isinstance(repos, list) else ():
        if not isinstance(entry, dict):
            continue
        hooks = entry.get("hooks")
        url = str(entry.get("repo", "")).lower().removesuffix(".git")
        out += [
            {"url": url, "rev": str(entry.get("rev", "")), "hook": hook}
            for hook in (hooks if isinstance(hooks, list) else ())
            if isinstance(hook, dict)
        ]
    return out


def hook_key(hook: dict[str, Any]) -> str:
    """A hook's alias, or its id."""
    return str(hook.get("alias") or hook.get("id"))


def canonical_hooks(kit: cq.Kit, profiles: list[str]) -> list[dict[str, Any]]:
    """The third-party hooks of the kit's canonical list for these profiles."""
    out: list[dict[str, Any]] = []
    for entry in kit.manifest().get("block", []):
        if entry.get("kind") == "pre-commit" and entry["profile"] in profiles:
            out += hook_lists("repos:\n" + cq.canonical_block(kit, entry))
    return [h for h in out if h["url"] != "local"]


def check_hooks(repo: cq.Repo, profiles: list[str], kit: cq.Kit, report: cq.Report) -> None:
    """The kit's hooks at a release tag, and its canonical third-party hooks unweakened."""
    rel = ".pre-commit-config.yaml"
    if not repo.exists(rel):
        return  # check_pre_commit_globals reports it
    try:
        have = hook_lists(repo.text(rel))
    except yaml.YAMLError as exc:
        report.add("hooks", rel, f"not valid YAML: {exc}")
        return
    mine = {hook_key(h["hook"]): h for h in have if h["url"] == KIT_HOOKS_URL}
    tag = re.compile(rf"{branch_of(kit.version())}\.\d+\.\d+")
    for hook_id, profile in KIT_HOOKS.items():
        if profile not in profiles:
            continue
        entry = mine.get(hook_id)
        if entry is None:
            report.add("hooks", rel, f"no {hook_id} hook from {KIT_HOOKS_URL}")
            continue
        if not tag.fullmatch(entry["rev"]):
            report.add(
                "hooks",
                rel,
                f"the kit's hooks are at {entry['rev'] or 'no rev'}: name a release tag,"
                f" {branch_of(kit.version())}.x.y (Dependabot moves it)",
            )
        changed = sorted(entry["hook"].keys() - {"id", "name", "alias", "verbose"})
        if changed:
            report.add(
                "hooks", rel, f"{hook_id} sets {', '.join(changed)}: take it as it is (no waiver)"
            )
    for want in canonical_hooks(kit, profiles):
        key = hook_key(want["hook"])
        found = [h["hook"] for h in have if h["url"] == want["url"] and hook_key(h["hook"]) == key]
        if not found:
            report.add("hooks", rel, f"no {key} hook from {want['url']}")
            continue
        for problem, weakening in hook_changes(key, found[0], want["hook"]):
            if weakening:
                report.weaken("pre-commit", problem, rel)
            else:
                report.add("hooks", rel, f"{problem} (no waiver)")
    for entry in have:
        if entry["url"] == "local" and "/quality/check_quality.py" in str(
            entry["hook"].get("entry", "")
        ):
            report.add("hooks", rel, "a local hook runs a held kit script: use the kit's hooks")


def hook_changes(
    key: str, have: dict[str, Any], want: dict[str, Any]
) -> Iterator[tuple[str, bool]]:
    """(what differs, whether a waiver can accept it) between a hook and the kit's."""
    for name in sorted((have.keys() | want.keys()) - {"id", "alias", "name", "verbose"}):
        if have.get(name) == want.get(name):
            continue
        if name in ("entry", "language", "stages"):
            yield f"{key} sets {name}: it may never run as the kit's does", False
        else:
            yield f"{key}:{name}:{have.get(name)}", True


def check_dependabot(repo: cq.Repo, report: cq.Report) -> None:
    """Dependabot moves the hook revisions, and leaves the kit's majors to a person."""
    rel = ".github/dependabot.yml"
    if not repo.exists(rel):
        return  # check_dependabot of check_quality.py reports it
    try:
        config = yaml.safe_load(repo.text(rel))
    except yaml.YAMLError:
        return
    updates = config.get("updates") if isinstance(config, dict) else None
    entries = [
        u
        for u in (updates if isinstance(updates, list) else ())
        if isinstance(u, dict) and u.get("package-ecosystem") == "pre-commit"
    ]
    if not entries:
        report.add("dependabot", rel, "no pre-commit ecosystem: it moves the hook revisions")
    for update in entries:
        ignored = [i for i in update.get("ignore") or () if isinstance(i, dict)]
        if not any(
            str(i.get("dependency-name", "")).lower().rstrip("*") == KIT_HOOKS_URL
            and "version-update:semver-major" in words(i.get("update-types"))
            for i in ignored
        ):
            report.add(
                "dependabot",
                rel,
                f'pre-commit must ignore "{KIT_HOOKS_URL}" for version-update:semver-major: a'
                " move to the kit's next major is a hand pull request with its fixes",
            )


# --------------------------------------------------------------------------
# Everything


def check_workflows(
    repo: cq.Repo, profiles: list[str], kit: cq.Kit, report: cq.Report, self_ref: bool
) -> None:
    """The workflow checks of the run form; the kit's home calls itself by ./ path."""
    found = workflows(repo)
    if not self_ref:
        check_references(repo, found, branch_of(kit.version()), kit, report)
    by_file = callers(found, self_ref)
    check_callers(repo, by_file, profiles, report)
    check_grants(found, by_file, report)
    check_forgery(found, report)
    check_gate(found, kit, report)
    for call in by_file.get(COMMENT, []):
        follows = call.triggers.get("workflow_run")
        named = follows.get("workflows") if isinstance(follows, dict) else None
        listed = [named] if isinstance(named, str) else words(named)
        gates = [str(w.data.get("name")) for w in found if gate_job(w)]
        if gates and not set(gates) & set(listed):
            report.add(
                "workflows",
                f"{call.workflow} jobs.{call.job_id}",
                f"follows {', '.join(listed) or 'no workflow'}, not {gates[0]}, whose run leaves"
                " the commit check's result",
            )
    outside = sorted(w.rel for w in found if "pull_request" in w.triggers and not gate_job(w))
    if outside:
        report.notes.append(f"run on pull requests outside {GATE}: {', '.join(outside)}")


def check(
    repo: cq.Repo, data: dict[str, Any], source: dict[str, Any], kit: cq.Kit, report: cq.Report
) -> None:
    """The checks only the run form has (check_records runs for it as well)."""
    profiles = source["profiles"]
    check_configs(repo, data, profiles, kit, report)
    check_kit_code(repo, kit, report)
    check_hooks(repo, profiles, kit, report)
    check_dependabot(repo, report)
    if "actions" in profiles:
        check_workflows(repo, profiles, kit, report, self_ref=False)


def hook_rev(repo: cq.Repo) -> str:
    """The revision of the kit's hooks a repository names, or "none"."""
    try:
        have = hook_lists(repo.text(".pre-commit-config.yaml"))
    except OSError, yaml.YAMLError:
        return "none"
    return next((h["rev"] for h in have if h["url"] == KIT_HOOKS_URL), "none")


def global_exclude(repo: cq.Repo) -> str:
    """The top-level `exclude` of the hook configuration, "" when it has none."""
    try:
        parsed = yaml.safe_load(repo.text(".pre-commit-config.yaml"))
    except OSError, yaml.YAMLError:
        return ""
    return str(parsed.get("exclude") or "") if isinstance(parsed, dict) else ""
