# SciCode-Verified dataset

This directory contains the source of truth and the derived v2.2 release for the corrected
SciCode test benchmark.

## Release snapshot

| Item | Value |
|---|---:|
| Main problems | 64 |
| Total subproblems | 290 |
| Scored subproblems | 287 |
| Problem files changed from upstream | 63 |
| Problems with target patches | 40 |
| Dataset version | v2.2 |

The three unscored subproblems (`13.6`, `62.1`, and `76.3`) are official SciCode skip steps. Their
reference implementations are inserted into the cumulative program for later steps, but they are
not generated or counted.

## v2.2 field and spectrum checks

Step **55.4** now validates the numerical values of the final field `u` and its raw,
FFT-shifted structure factor `Sk`, in addition to the existing shapes and stripe
summaries. The reference arrays use the specified Euler-local / exact-Fourier
split for **10000 steps** (`dt=0.005`, `T=50`, unit grid spacing, seed 42).
The previous arrays matched 9999 steps. The new comparisons use
`np.allclose(..., atol=5e-9, rtol=5e-9)`.

Only `55.4/test1..6/var1` and `var2` change in the HDF5. The stripe flags/modes,
all other targets, solver-visible text, and function signatures are unchanged.
The frozen component arrays and their checksum live in `refs/p55_targets_10000.npz`
and `targets/55.json`; `refs/p55_ref.py` documents the numerical recipe. The normal
HDF5 builder applies the exact frozen arrays. See [ledger/R9.jsonl](../ledger/R9.jsonl).

Numerical validation covered five equivalent float64 implementations in both
grading environments for all six cases. All 132 checked array comparisons passed
the selected tolerance; all five stripe-forming cases rejected a one-step timing
error. The near-zero decay case intentionally retains an absolute-error floor.

Only 55.4 was re-executed for 37 saved programs under the two existing environments;
old and new checks received the same outputs. All **27 with-background runs** retain
their prior verdicts and totals. Five runs with complete no-background scores change:

| Model / run (no background) | Passed subproblems, old → v2.2 (of 287) | Passed main problems (of 64, unchanged) |
|---|---:|---:|
| DeepSeek V4 Flash Preview / run1 | 189 → 188 | 27 |
| DeepSeek V4 Pro Preview / run2 | 196 → 195 | 30 |
| DeepSeek V4 Pro Preview / run3 | 199 → 198 | 33 |
| GPT-5.5 / run4 | 237 → 236 | 42 |
| Gemini 3.5 Flash / run4 | 231 → 230 | 33 |

Four other scored no-background runs already failed 55.4 and remain unchanged.
One Fable 5 no-background run has generated code but no full historical score;
it fails the new check, and no aggregate score is claimed for it.

**Condition-specific limitation:** the explicit mixed-scheme prescription is in
`step_background` and is withheld in no-background evaluation. The five changed
runs use other time integrators (ETD/IMEX/semi-implicit), not merely different
floating-point implementations. Failure to match this particular reference must
not automatically be interpreted as an incorrect scientific algorithm. Their 55.1
steps already failed, so the additional 55.4 failures do not change main-problem totals.

Use matching **v2.2 JSONL, manifest, and HDF5** together. Existing generations can
be reused, but cached 55.4 verdicts must be refreshed and totals recomputed. Old
run artifacts and the HF `v2`/`v2.1` versions are retained for reproducibility.

## v2.1 test-only update

The following describes the historical v2 → v2.1 change; v2.2 additionally changes
the 55.4 reference arrays as described above.

Only step **62.5** changes from v2. Its test now requires the Hamiltonian and both
connection operators to be jointly related to the reference by one unitary basis
transformation. Comparing their spectra separately is not sufficient to enforce
this consistency. The existing energy, block-metadata, and spectral checks remain.
The new check retains `np.allclose` tolerances `rtol=1e-5`, `atol=1e-8` and applies
to this test's fixed four-dimensional, untruncated operator tuple.

The solver-visible prompts, function signatures, all gold targets, and all other
subproblem tests are unchanged in v2.1. For that version the v2 HDF5 remains valid; its MD5 is
still `2b41a7df40ddc23ce651ec05b8ecb6f8`. The regenerated JSONL and manifest identify
the new version. The old `data` GitHub Release remains the historical v2 snapshot;
use the JSONL/manifest and HDF5 from the matching Hugging Face version.

For existing model runs, preserve generated `*.code.py` files and regrade **62.5
only**, then recompute subproblem/main-problem totals from the saved verdicts.
Merely resuming a run will reuse cached verdicts and does not apply the new test.
[`tools/regrade_joint_basis_62_5.py`](../tools/regrade_joint_basis_62_5.py) compares
old and new checks on the same cached output under the supplied environments and
writes versioned summaries separately, without overwriting old scores or making
model API calls. Its source documents the command-line options.

The exact before/after test and rationale are recorded in
[`ledger/R8.jsonl`](../ledger/R8.jsonl). Regression tests can be run without the
large HDF5 file:

```bash
python -m unittest discover -s tests -p 'test_joint_basis_62_5.py' -v
```

Validation on saved outputs: all **37** available complete 62.5 programs were
executed under both existing scientific-Python environments (NumPy 1.26.4 /
SciPy 1.13.1 and NumPy 2.4.2 / SciPy 1.17.1). Old and new checks received the same
returned tuple within each execution. All 37 old/new OR verdicts agreed (30 pass,
7 fail). For the **36** runs with complete historical grading, both subproblem
and main-problem totals were unchanged after replacing only the 62.5 verdict.
The remaining generated-only run passed both checks but has no full-score baseline.
This audit includes background/no-background settings, repeated runs, and six
legacy runs; it involved no new model generations. Synthetic regression tests
additionally accept 50 common unitary changes of basis and reject 50 inconsistent
operator-basis constructions that the previous separate-spectrum check accepted.

## Files

### Source of truth

| Path | Contents |
|---|---|
| `problems/<id>.json` | Canonical prompt, background, substeps, function headers, tests, and return lines |
| `targets/<id>.json` | Corrected target values or reproducible target transforms |
| `refs/` | Reference code used by target transforms |

Edit only these source files when changing the dataset.

### Derived release artifacts

| Path | Produced by | Contents |
|---|---|---|
| `problems_test.jsonl` | `tools/assemble.py` | Flattened 64-problem evaluation dataset |
| `manifest.json` | `tools/assemble.py` | Dataset version and content hashes |
| `test_data_cleaned.h5` | `eval_clean/build_clean_h5.py` | Corrected frozen grading targets |

`test_data_cleaned.h5` is approximately 1.1 GB and is intentionally not stored in Git.
Download the matching [v2.2 Hugging Face release](https://huggingface.co/datasets/shhu2001/SciCode-Verified/tree/v2.2):

```bash
hf download shhu2001/SciCode-Verified test_data_cleaned.h5 \
  --repo-type dataset --revision v2.2 --local-dir scicode_verified
```

Expected HDF5 MD5:

```text
32c5602f2bf08393f917f03ff0b80d40
```

The evaluation harness refuses to run when the released JSONL or HDF5 does not match
`manifest.json`.

## Maintenance workflow

After editing the source of truth:

```bash
# Required after prompt/problem changes
python tools/assemble.py

# Required after target changes; needs upstream SciCode/eval/data/test_data.h5
python eval_clean/build_clean_h5.py

# Required before release; use the ledger round containing the change
python tools/verify.py --scope full --round <ROUND>
```

Each accepted change must also have a provenance record in `ledger/<round>.jsonl`.

The verification gate enforces:

- derived JSONL equals the per-problem source files;
- every ledger decision is present in the release;
- every release change is represented in the ledger;
- prompt-only rounds do not silently alter target data;
- executable headers and tests parse successfully.

Never edit `problems_test.jsonl`, `manifest.json`, or `test_data_cleaned.h5` by hand.
