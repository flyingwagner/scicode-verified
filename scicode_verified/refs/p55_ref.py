"""Reference recipe and frozen-target loader for 55.4 (v2.2).

The distributed NPZ contains only the final u and Sk at 10000 steps. This module
documents their deterministic construction and lets the HDF5 builder apply the
exact frozen arrays without recomputing unrelated targets.
"""
from pathlib import Path
import hashlib

import numpy as np

CASES = ((100, 0.7, 0.5), (100, 0.2, 0.5), (100, -0.5, 0.5),
         (200, 0.7, 0.4), (200, 0.7, 1.0), (200, 0.7, 2.0))


def final_fields(n, epsilon, q0, *, dt=0.005, n_steps=10000, seed=42):
    """Prescribed Euler-local + exact Fourier split, unit grid, float64."""
    u = np.random.RandomState(seed).rand(n, n)
    k = 2 * np.pi * np.fft.fftfreq(n, d=1.0)
    k2 = k[:, None] ** 2 + k[None, :] ** 2
    prop = np.exp(dt * (2 * k2 / q0 ** 2 - k2 ** 2 / q0 ** 4))
    for _ in range(n_steps):
        u1 = u + dt * (epsilon * u - u - u ** 3)
        u = np.fft.ifft2(np.fft.fft2(u1) * prop).real
    sk = np.fft.fftshift(np.abs(np.fft.fft2(u)) ** 2)
    return u, sk


def apply_frozen_arrays(handle, spec, repo_root):
    """Replace only 55.4's u/Sk datasets; retain stripe and all other targets."""
    assert spec['_type'] == 'swift_hohenberg_fixed_time_arrays'
    assert spec['steps'] == 10000 and spec['dt'] == 0.005 and spec['T'] == 50.0
    assert spec['dx'] == 1.0 and spec['seed'] == 42
    assert [(x['N'], x['epsilon'], x['q0']) for x in spec['cases']] == list(CASES)
    root = Path(repo_root).resolve()
    path = (root / spec['file']).resolve()
    assert root in path.parents, 'Frozen target path must stay inside the repository'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == spec['sha256'], 'Frozen target checksum mismatch'
    with np.load(path, allow_pickle=False) as arrays:
        expected = {f'test{i}_{field}' for i in range(1, 7) for field in ('u', 'Sk')}
        assert set(arrays.files) == expected
        for i, (n, _, _) in enumerate(CASES, 1):
            u, sk = arrays[f'test{i}_u'], arrays[f'test{i}_Sk']
            for value in (u, sk):
                assert value.shape == (n, n) and value.dtype == np.dtype('float64')
                assert np.isfinite(value).all()
            assert np.allclose(sk, np.fft.fftshift(np.abs(np.fft.fft2(u)) ** 2),
                               atol=5e-9, rtol=5e-9), 'Field/spectrum mismatch'
            for var, value in (('var1', u), ('var2', sk)):
                dataset = handle[f'55.4/test{i}/{var}']
                assert dataset.shape == value.shape and dataset.dtype == value.dtype
                dataset[...] = value


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='Fresh NPZ path; compare regenerated arrays to the frozen release within tolerance')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Refusing to overwrite an existing file')
    values = {}
    for i, (n, epsilon, q0) in enumerate(CASES, 1):
        values[f'test{i}_u'], values[f'test{i}_Sk'] = final_fields(n, epsilon, q0)
    np.savez_compressed(args.output, **values)
    print(args.output)
