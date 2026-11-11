# SciCode-Verified dataset

This directory contains the source of truth and the derived v2.1 release for the corrected
SciCode test benchmark.

## Release snapshot

| Item | Value |
|---|---:|
| Main problems | 64 |
| Total subproblems | 290 |
| Scored subproblems | 287 |
| Problem files changed from upstream | 63 |
| Problems with target patches | 39 |
| Dataset version | v2.1 |

The three unscored subproblems (`13.6`, `62.1`, and `76.3`) are official SciCode skip steps. Their
reference implementations are inserted into the cumulative program for later steps, but they are
not generated or counted.

## v2.1 test-only update

Only step **62.5** changes from v2. Its test now requires the Hamiltonian and both
connection operators to be jointly related to the reference by one unitary basis
transformation. Comparing their spectra separately is not sufficient to enforce
this consistency. The existing energy, block-metadata, and spectral checks remain.
The new check retains `np.allclose` tolerances `rtol=1e-5`, `atol=1e-8` and applies
to this test's fixed four-dimensional, untruncated operator tuple.

The solver-visible prompts, function signatures, all gold targets, and all other
subproblem tests are unchanged. The v2 HDF5 download remains valid; its MD5 is
still `2b41a7df40ddc23ce651ec05b8ecb6f8`. The regenerated JSONL and manifest identify
the new version. The old `data` GitHub Release remains the historical v2 snapshot;
use the JSONL/manifest from the current checkout or the matching Hugging Face version.

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

`test_data_cleaned.h5` is approximately 1.1 GB and is intentionally not stored in Git. Download it
from the [v2 data release](https://github.com/flyingwagner/scicode-verified/releases/tag/data):

```bash
gh release download data \
  --repo flyingwagner/scicode-verified \
  --dir scicode_verified
```

Expected HDF5 MD5:

```text
2b41a7df40ddc23ce651ec05b8ecb6f8
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
