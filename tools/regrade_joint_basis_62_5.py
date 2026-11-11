#!/usr/bin/env python3
"""Regrade only cached 62.5 outputs; preserve every existing verdict and generation.

Run old and new assertions on the SAME returned operator tuple in each environment.
Rebuild versioned full-run summaries by overlaying the new 62.5 verdict on saved
verdicts for all other steps. Never invoke a model or evaluate another subproblem.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

STEP = "62.5"
SKIP = {"13.6", "62.1", "76.3"}
MARKER = "__SCICODE_625_RESULT__"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def md5(path):
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path):
    return json.loads(path.read_text())


def baseline(run, universe):
    """Prefer later per-step caches, report conflicts, then fill from valid results.

    The old results.json can predate a complete multienv regrade; it is never
    allowed to overwrite a later per-step verdict. Missing entries remain unknown.
    """
    by_step, sources, conflicts = {}, {}, []
    summary_file = run / "results.json"
    summary_steps = {}
    if summary_file.exists():
        data = load(summary_file)
        if not data.get("summary", {}).get("generate_only", False):
            summary_steps = {s: v for p in data.get("results", [])
                             for s, v in p.get("steps", {}).items() if isinstance(v, bool)}
    for sid in universe:
        choices = []
        for suffix in ("score.json", "multienv.json"):
            p = run / sid.split(".")[0] / f"{sid}.{suffix}"
            if p.exists():
                data = load(p)
                if isinstance(data.get("passed"), bool):
                    if data.get("per_env"):
                        assert data["passed"] == any(data["per_env"].values()), str(p)
                    choices.append((p.stat().st_mtime_ns, suffix == "multienv.json", p, data["passed"]))
        if choices:
            latest = max(choices, key=lambda c: (c[0], c[1]))
            by_step[sid], sources[sid] = latest[3], str(latest[2].relative_to(run))
            distinct = {c[3] for c in choices}
            if sid in summary_steps:
                distinct.add(summary_steps[sid])
            if len(distinct) > 1:
                conflicts.append({"step_id": sid, "selected": latest[3],
                                  "source": sources[sid], "results_json": summary_steps.get(sid),
                                  "caches": [{"path": str(c[2].relative_to(run)), "mtime_ns": c[0],
                                              "passed": c[3]} for c in choices]})
        elif sid in summary_steps:
            by_step[sid], sources[sid] = summary_steps[sid], "results.json"
    return by_step, sources, conflicts


def totals(verdicts, universe):
    missing = [s for s in universe if s not in verdicts]
    if missing:
        return {"complete": False, "known_steps": len(verdicts), "missing_steps": missing,
                "steps_correct": None, "problems_correct": None}
    pids = sorted({s.split(".")[0] for s in universe}, key=int)
    return {"complete": True, "steps_total": len(universe), "problems_total": len(pids),
            "steps_correct": sum(verdicts[s] for s in universe),
            "problems_correct": sum(all(verdicts[s] for s in universe if s.split(".")[0] == pid)
                                    for pid in pids)}


def run_environment(py, cumulative, setup, old_assertions, new_assertions, h5, timeout):
    # The code and assertions are executed only in an isolated child process/cwd.
    code = f'''import json, traceback
import h5py
import numpy as np
_result = {{}}
try:
    with h5py.File({str(h5)!r}, "r") as _file:
        _g = _file["62.5/test1"]
        _target = (_g["var1"][()], _g["var2"][()],
                   {{k: _g["var3"][k][()] for k in ("H", "conn_Sz", "conn_Sp")}},
                   _g["var4"][()])
    _ns = {{"__name__": "__cached_solution__", "target": _target}}
    exec(compile({cumulative!r}, "<saved cumulative code>", "exec"), _ns)
    exec(compile({setup!r}, "<62.5 setup>", "exec"), _ns)
    for _label, _assertions in [("old", {old_assertions!r}), ("new", {new_assertions!r})]:
        _state = dict(_ns)
        try:
            exec(compile(_assertions, "<62.5 " + _label + " checks>", "exec"), _state)
            _result[_label] = {{"passed": True}}
        except Exception as _exc:
            _result[_label] = {{"passed": False, "error": type(_exc).__name__ + ": " + str(_exc),
                              "traceback": traceback.format_exc(limit=5)}}
        if _label == "new" and "_basis_U" in _state:
            _u = _state["_basis_U"]
            _result["joint_diagnostics"] = {{
                "unitarity_residual_fro": float(np.linalg.norm(_u.conj().T @ _u - np.eye(_u.shape[0]))),
                "operator_residuals_fro": [float(np.linalg.norm(_u.conj().T @ a @ _u - b))
                                          for a, b in zip(_state["_ref_ops"], _state["_out_ops"])],
            }}
except Exception as _exc:
    _result = {{"execution_error": type(_exc).__name__ + ": " + str(_exc),
               "traceback": traceback.format_exc(limit=5),
               "old": {{"passed": False}}, "new": {{"passed": False}}}}
print({MARKER!r} + json.dumps(_result))
'''
    child_env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                     MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    # No provider credentials are needed to execute already saved programs.
    for key in list(child_env):
        if any(word in key.upper() for word in ("API_KEY", "ACCESS_KEY", "TOKEN", "SECRET", "PASSWORD")):
            child_env.pop(key)
    with tempfile.TemporaryDirectory(prefix="scicode-625-") as work:
        try:
            proc = subprocess.run([str(py), "-c", code], capture_output=True, text=True,
                                  timeout=timeout, cwd=work, env=child_env)
        except subprocess.TimeoutExpired:
            return {"execution_error": "timeout", "old": {"passed": False}, "new": {"passed": False}}
    lines = [line[len(MARKER):] for line in proc.stdout.splitlines() if line.startswith(MARKER)]
    if not lines:
        return {"execution_error": "child produced no verdict", "returncode": proc.returncode,
                "stderr": proc.stderr[-2000:], "old": {"passed": False}, "new": {"passed": False}}
    return json.loads(lines[-1])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs-root", type=Path, required=True)
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--ledger", type=Path, required=True)
    ap.add_argument("--h5", type=Path, required=True)
    ap.add_argument("--envs", nargs="+", required=True, help="label:/path/to/python")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()
    manifest = load(args.manifest)
    assert md5(args.dataset) == manifest["problems_test_jsonl_md5"]
    assert md5(args.h5) == manifest["h5_md5"]
    problems = [json.loads(line) for line in args.dataset.read_text().splitlines() if line.strip()]
    universe = [s["step_number"] for p in problems for s in p["sub_steps"] if s["step_number"] not in SKIP]
    assert len(universe) == 287
    problem = next(p for p in problems if str(p["problem_id"]) == "62")
    entry = next(json.loads(line) for line in args.ledger.read_text().splitlines()
                 if json.loads(line).get("field") == "sub_steps[4].test_cases[0]")
    old_test, new_test = entry["before"], problem["sub_steps"][4]["test_cases"][0]
    assert entry["after"] == new_test and new_test.startswith(old_test)
    split_marker = "a, b, c, d = target\n"
    old_setup, old_tail = old_test.split(split_marker, 1)
    new_setup, new_tail = new_test.split(split_marker, 1)
    assert old_setup == new_setup
    old_assertions, new_assertions = split_marker + old_tail, split_marker + new_tail
    envs = [(e.split(":", 1)[0], Path(e.split(":", 1)[1])) for e in args.envs]
    assert len({lab for lab, _ in envs}) == len(envs)
    env_versions = {}
    for lab, py in envs:
        proc = subprocess.run([str(py), "-c", "import sys,numpy,scipy,h5py,json;print(json.dumps({'python':sys.version.split()[0],'numpy':numpy.__version__,'scipy':scipy.__version__,'h5py':h5py.__version__}))"],
                              capture_output=True, text=True, check=True, timeout=30)
        env_versions[lab] = json.loads(proc.stdout)
    assert not args.output.exists(), "Choose a fresh output directory; do not overwrite a previous audit."
    args.output.mkdir(parents=True)
    run_dirs = sorted({p.parent for pattern in ("**/cleaned_*/with_bg/62", "**/cleaned_*/no_bg/62")
                       for p in args.runs_root.glob(pattern) if p.is_dir()})
    eligible, missing_generation = [], []
    for run in run_dirs:
        files = [run / "62" / f"62.{i}.code.py" for i in range(1, 6)]
        missing = [str(p.relative_to(run)) for p in files if not p.exists()]
        if missing:
            missing_generation.append({"run": str(run.relative_to(args.runs_root)), "missing": missing})
        else:
            eligible.append((run, files))
    print(f"{len(eligible)} complete outputs; {len(missing_generation)} incomplete directories", flush=True)

    def work(item):
        run, files = item
        rel = run.relative_to(args.runs_root)
        old_verdicts, sources, conflicts = baseline(run, universe)
        monitored = files + sorted(run.glob("*/*.score.json")) + sorted(run.glob("*/*.multienv.json"))
        if (run / "results.json").exists():
            monitored.append(run / "results.json")
        hashes = {str(p.relative_to(run)): digest(p) for p in monitored}
        cumulative = problem["required_dependencies"] + "\n\n" + "\n\n".join(p.read_text() for p in files)
        outcomes = {lab: run_environment(py, cumulative, old_setup, old_assertions, new_assertions,
                                        args.h5, args.timeout) for lab, py in envs}
        old_pass = any(d["old"]["passed"] for d in outcomes.values())
        new_pass = any(d["new"]["passed"] for d in outcomes.values())
        assert not new_pass or old_pass, "New checks unexpectedly weakened old checks"
        new_verdicts = dict(old_verdicts, **{STEP: new_pass})
        result = {
            "run": str(rel), "legacy": "legacy" in rel.parts,
            "step_id": STEP, "dataset_version": manifest["version"],
            "historical_62_5": old_verdicts.get(STEP), "old_reexecuted": old_pass,
            "new_reexecuted": new_pass, "new_check_changes_same_output": old_pass != new_pass,
            "historical_reexecution_disagrees": old_verdicts.get(STEP) is not None and old_verdicts[STEP] != old_pass,
            "per_env": outcomes, "baseline": totals(old_verdicts, universe),
            "updated": totals(new_verdicts, universe),
            "baseline_cache_conflicts": conflicts, "baseline_verdict_sources": sources,
            "input_sha256": hashes,
        }
        result["existing_caches_unchanged"] = all(digest(run / path) == sha for path, sha in hashes.items())
        assert result["existing_caches_unchanged"]
        dest = args.output / rel
        dest.mkdir(parents=True)
        (dest / "62.5.joint_basis.json").write_text(json.dumps(result, indent=2) + "\n")
        # Full versioned summary: only the 62.5 entry is replaced, all other
        # verdicts are reused. Unknown entries remain null, never fabricated failures.
        full = {"summary": result["updated"], "dataset_version": manifest["version"],
                "only_regraded_step": STEP, "results": []}
        for p in problems:
            scored = [s["step_number"] for s in p["sub_steps"] if s["step_number"] not in SKIP]
            verdicts = {sid: new_verdicts.get(sid) for sid in scored}
            full["results"].append({"problem_id": str(p["problem_id"]), "steps": verdicts,
                                    "problem_correct": all(verdicts.values()) if all(v is not None for v in verdicts.values()) else None})
        (dest / "results.v2.1.json").write_text(json.dumps(full, indent=2) + "\n")
        print(f"{rel}: cached={result['historical_62_5']} old={old_pass} new={new_pass}", flush=True)
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = [f.result() for f in as_completed([pool.submit(work, item) for item in eligible])]
    records.sort(key=lambda r: r["run"])
    report = {"dataset_version": manifest["version"], "dataset_md5": manifest["problems_test_jsonl_md5"],
              "h5_md5": manifest["h5_md5"], "new_test_sha256": hashlib.sha256(new_test.encode()).hexdigest(),
              "envs": env_versions, "only_regraded_step": STEP,
              "model_api_calls": 0, "old_scores_overwritten": False,
              "records": records, "missing_generation": missing_generation}
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Finished. Report:", args.output / "report.json", flush=True)


if __name__ == "__main__":
    main()
