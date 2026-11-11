# Evaluation harness

`run_deepseek_eval.py` is the canonical SciCode-Verified runner. Despite its historical filename,
it supports multiple OpenAI-compatible providers and arbitrary model slugs. It reproduces
SciCode's cumulative prompting and all-or-nothing main-problem scoring while adding:

- manifest-bound dataset loading;
- resumable, per-step generation caches;
- generation-only and grading-only operation;
- 1,800-second isolated grading processes;
- multi-environment OR scoring for scientific-Python compatibility.

## Install

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install openai h5py numpy scipy matplotlib sympy huggingface_hub
```

Download the v2.2 grading targets before evaluating the current dataset:

```bash
hf download shhu2001/SciCode-Verified test_data_cleaned.h5 \
  --repo-type dataset --revision v2.2 --local-dir scicode_verified
```

## Minimal run

```bash
export DEEPSEEK_API_KEY="..."

python eval_clean/run_deepseek_eval.py \
  --model pro \
  --dataset cleaned \
  --background on \
  --run experiment-01 \
  --workers 8
```

Use `--only 58` for a one-problem smoke test. Use the same `--run` tag to resume an interrupted
run; existing generated steps are reused.

The runner accepts registered aliases shown by `--help`, a raw OpenRouter slug such as
`vendor/model`, or an endpoint-specific slug together with `--provider`.

```bash
export OPENROUTER_API_KEY="..."
python eval_clean/run_deepseek_eval.py \
  --model vendor/model \
  --dataset cleaned \
  --background on \
  --run openrouter-model
```

Provider base URLs can be overridden with their corresponding environment variables, including
`ALI_API_URL`, `ARK_API_URL`, `META_API_URL`, and `LOCAL_API_URL`.

## Dataset modes

| Mode | Input | Use |
|---|---|---|
| `--dataset cleaned` | SciCode-Verified JSONL + corrected HDF5 | Standard benchmark evaluation |
| `--dataset original` | Pristine upstream JSONL + HDF5 | Matched before/after research only |

The cleaned mode verifies both released artifacts against `scicode_verified/manifest.json`.
Original mode verifies the upstream files against pinned hashes. It requires an upstream SciCode
checkout at `SciCode/`; standard cleaned evaluation does not.

Both modes contain the same 64 main problems and 287 scored subproblems. The harness, prompts,
timeouts, and scoring rule are identical; only the benchmark data changes.

## Background conditions

```bash
--background on       # expert-written scientific background is visible
--background off      # background is withheld
```

Omit the flag to run both conditions. Report them separately.

## Multi-environment scoring

Scientific code can be correct while using APIs that changed between NumPy/SciPy releases.
For the canonical protocol, grade every saved step in a 2024-era and a 2025-era environment and
accept it if either produces the correct result:

```bash
python eval_clean/run_deepseek_eval.py \
  --model vendor/model \
  --dataset cleaned \
  --background on \
  --run experiment-01 \
  --envs \
    2024:/path/to/scipy-2024/bin/python \
    2025:/path/to/scipy-2025/bin/python \
  --full-envs
```

`--full-envs` evaluates both environments even after the first pass and records the complete
per-environment breakdown. Without explicit `--envs`, the runner uses configured
`SCICODE_GRADE_ENVS` entries when available and otherwise falls back to the current interpreter.

## Separate generation from grading

Generation needs an API key; grading needs CPU time and the released HDF5. The two stages can run
on different machines.

Generate:

```bash
python eval_clean/run_deepseek_eval.py \
  --model vendor/model \
  --dataset cleaned \
  --background on \
  --run experiment-01 \
  --generate-only
```

Grade later by repeating the same command without `--generate-only` and with the desired
`--envs`. Cached `<step>.code.py` files are reused, so the grading pass makes no model API calls.

For already-generated runs, the standalone re-grader is equivalent:

```bash
python eval_clean/regrade_multienv.py \
  --run experiment-01 \
  --models vendor/model \
  --dataset cleaned \
  --bg with_bg \
  --workers 32 \
  --envs \
    2024:/path/to/scipy-2024/bin/python \
    2025:/path/to/scipy-2025/bin/python
```

## Outputs

```text
eval_clean/ds_runs/<run>/<dataset>_<model>/<with_bg|no_bg>/
├── results.json
└── <problem-id>/
    ├── <step>.raw.json
    ├── <step>.code.py
    └── <step>.score.json
```

`results.json` records subproblem and whole-problem accuracy. Each score file records the
pass/fail decision and the per-environment verdicts.

## Other scripts

| Script | Purpose |
|---|---|
| `build_clean_h5.py` | Rebuild the corrected HDF5 from upstream data and 40 target patches |
| `regrade_multienv.py` | Re-score cached generations in explicitly selected environments |
| `regrade_fixed_output.py` | Cross-grade original-run outputs against corrected tests and targets |
| `run_cleaned_eval.sh` | Compatibility wrapper for an upstream SciCode `inspect_ai` checkout |
| `normalize_targets.py` | Normalize target-patch representation during dataset maintenance |

`run_cleaned_eval.sh` is a secondary compatibility path and requires the full upstream repository.
For a standalone SciCode-Verified checkout, use `run_deepseek_eval.py`.
