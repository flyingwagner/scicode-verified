"""Assemble the released dataset FROM the SSOT (verify-with-human invariant 3:
derive-only). Never hand-edit problems_test.jsonl — edit scicode_verified/problems/<id>.json
and re-run this.

Inputs (SSOT):
  scicode_verified/problems/<id>.json   per-problem text state
  scicode_verified/targets/<id>.json    target patches (SSOT for the h5)
Outputs (derived):
  scicode_verified/problems_test.jsonl  problems sorted by int(problem_id),
                                        compact (ensure_ascii=False, default
                                        separators), trailing newline — the exact
                                        format of the original release.
  scicode_verified/manifest.json        version + md5 of every released file,
                                        so the consumer can refuse stale data.

This script does NOT rebuild the h5 (that is eval_clean/build_clean_h5.py); it
records the h5's md5 in the manifest if the file is present.
"""
import json, os, hashlib, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VDIR = os.path.join(ROOT, 'scicode_verified')
PROB = os.path.join(VDIR, 'problems')
TARG = os.path.join(VDIR, 'targets')
JSONL = os.path.join(VDIR, 'problems_test.jsonl')
H5 = os.path.join(VDIR, 'test_data_cleaned.h5')
MANIFEST = os.path.join(VDIR, 'manifest.json')
VERSION = os.environ.get('DATASET_VERSION', 'v2.2')


def md5_file(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def md5_bytes(b):
    return hashlib.md5(b).hexdigest()


def main():
    files = [fn for fn in os.listdir(PROB) if fn.endswith('.json')]
    objs = [json.load(open(os.path.join(PROB, fn), encoding='utf-8')) for fn in files]
    objs.sort(key=lambda o: int(o['problem_id']))

    # compact lines, exactly matching the original release format
    lines = [json.dumps(o, ensure_ascii=False) for o in objs]
    body = '\n'.join(lines) + '\n'
    with open(JSONL, 'w', encoding='utf-8') as f:
        f.write(body)

    # manifest: md5 of the released jsonl, every target patch, and the h5 if built
    targets_md5 = {}
    if os.path.isdir(TARG):
        for fn in sorted(os.listdir(TARG)):
            if fn.endswith('.json'):
                targets_md5[fn] = md5_file(os.path.join(TARG, fn))
    manifest = {
        'version': VERSION,
        'n_problems': len(objs),
        'problem_order': [str(o['problem_id']) for o in objs],
        'problems_test_jsonl_md5': md5_bytes(body.encode('utf-8')),
        'targets_md5': targets_md5,
        'targets_set_md5': md5_bytes(json.dumps(targets_md5, sort_keys=True).encode()),
        'h5_md5': md5_file(H5) if os.path.exists(H5) else None,
    }
    with open(MANIFEST, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
        f.write('\n')

    print(f'assembled {len(objs)} problems -> {JSONL}')
    print(f'  jsonl md5  : {manifest["problems_test_jsonl_md5"]}')
    print(f'  targets    : {len(targets_md5)} patches, set md5 {manifest["targets_set_md5"][:12]}')
    print(f'  h5 md5     : {manifest["h5_md5"]}')
    print(f'wrote {MANIFEST}')


if __name__ == '__main__':
    main()
