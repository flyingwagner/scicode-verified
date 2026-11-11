"""Flat, single-pass build of the cleaned test_data.h5.

Design (replaces the layered build_h5.py -> build_h5_round2.py chain):
  - SRC     : the ORIGINAL, downloaded SciCode test_data.h5 (never modified).
  - TARGETS : ONE consolidated patch folder (all rounds merged at problem level;
              later rounds already folded in by the merge step). Only CHANGED tests
              are stored here; everything else is copied verbatim from SRC.
  - OUT     : the cleaned h5, rebuilt from scratch every run.

There is NO intermediate cleaned h5 and NO round nesting: the cleaned dataset is
fully defined by (original h5) + (this one targets/ folder). To reproduce, download
the original h5 and run this script.

Patch formats (one .json per problem in TARGETS):
  FLAT      : {"<step>": {"<test_idx>": value, ...}}                       (only changed tests)
  NESTED    : {"problem_id":.., "targets": {"<step>": [v0, v1, ...] | {"<idx>": v}}, ..}
  TRANSFORM : targets[step] == {"_transform":.., ..} when the new arrays are too large to
              inline (28.3: square the Intensity component -> |E|^2); applied in-place.
Complex numbers are encoded {"__complex__": [re, im]}.

Usage:
  python3 eval_clean/build_clean_h5.py
  # overrides: SRC=... TARGETS=... OUT=... python3 eval_clean/build_clean_h5.py
"""
import h5py, json, os, re, shutil, numpy as np

ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC     = os.environ.get('SRC',     os.path.join(ROOT, 'SciCode/eval/data/test_data.h5'))
TARGETS = os.environ.get('TARGETS', os.path.join(ROOT, 'scicode_verified/targets'))
OUT     = os.environ.get('OUT',     os.path.join(ROOT, 'scicode_verified/test_data_cleaned.h5'))
STEP = re.compile(r'^\d+\.\d+$')

assert os.path.exists(SRC), f"original h5 not found: {SRC} (download it first — see README)"
assert os.path.abspath(OUT) != os.path.abspath(SRC), "OUT must differ from SRC (never clobber the original)"
os.makedirs(os.path.dirname(OUT), exist_ok=True)


def conv(v):
    if isinstance(v, dict) and '__complex__' in v: return complex(v['__complex__'][0], v['__complex__'][1])
    if isinstance(v, list): return [conv(x) for x in v]
    return v


# --- gather ALL patches from the single consolidated folder ---
patches = {}      # step -> {test_idx(int): value}
transforms = {}   # step -> transform spec dict
for fn in sorted(os.listdir(TARGETS)):
    if not fn.endswith('.json'): continue
    d = json.load(open(os.path.join(TARGETS, fn)))
    # FLAT top-level step keys
    for step, idxs in d.items():
        if STEP.match(step) and isinstance(idxs, dict):
            patches.setdefault(step, {}).update({int(k): conv(v) for k, v in idxs.items()})
    # NESTED under "targets"
    if isinstance(d.get('targets'), dict):
        for step, vals in d['targets'].items():
            if not STEP.match(step): continue
            if isinstance(vals, dict) and '_transform' in vals:
                transforms[step] = vals
            elif isinstance(vals, list):
                patches.setdefault(step, {}).update({i: conv(v) for i, v in enumerate(vals)})
            elif isinstance(vals, dict):
                patches.setdefault(step, {}).update({int(k): conv(v) for k, v in vals.items()
                                                     if str(k).lstrip('-').isdigit()})


def write_test(f, step, testno, value, nvars):
    gp = f'{step}/test{testno}'
    if gp in f: del f[gp]
    g = f.create_group(gp)
    comps = list(value) if (nvars > 1 and isinstance(value, (list, tuple)) and len(value) == nvars) else [value]
    for i, c in enumerate(comps):
        g.create_dataset(f'var{i+1}', data=np.array(c))


# --- per-step test_cases counts from the SSOT (to trim orphan h5 targets) ---
PROB_DIR = os.path.join(ROOT, 'scicode_verified', 'problems')
SKIP_STEPS = {'13.6', '62.1', '76.3'}
step_ntc = {}
if os.path.isdir(PROB_DIR):
    for fn in os.listdir(PROB_DIR):
        if not fn.endswith('.json'):
            continue
        d = json.load(open(os.path.join(PROB_DIR, fn)))
        for s in d.get('sub_steps', []):
            step_ntc[str(s.get('step_number'))] = len(s.get('test_cases') or [])

shutil.copy(SRC, OUT)
print(f"SRC     = {SRC}")
print(f"TARGETS = {TARGETS}")
print(f"OUT     = {OUT}\n")

with h5py.File(OUT, 'a') as f:
    skey = lambda s: (int(s.split('.')[0]), int(s.split('.')[1]))
    for step in sorted(patches, key=skey):
        nvars = len([k for k in f[f'{step}/test1'].keys()])
        for idx, val in sorted(patches[step].items()):
            write_test(f, step, idx + 1, val, nvars)
    # transform-spec patches, applied against the copied-in original arrays
    for step in sorted(transforms, key=skey):
        spec = transforms[step]

        # --- 55.4: frozen arrays at the prescribed terminal time (10000 steps).
        # Stripe flags/modes and every other target remain untouched.
        if spec.get('_type') == 'swift_hohenberg_fixed_time_arrays':
            assert step == '55.4'
            import importlib.util
            ref_path = os.path.join(ROOT, 'scicode_verified', 'refs', 'p55_ref.py')
            rspec = importlib.util.spec_from_file_location('p55_ref', ref_path)
            ref = importlib.util.module_from_spec(rspec)
            rspec.loader.exec_module(ref)
            ref.apply_frozen_arrays(f, spec, ROOT)
            print('  transform 55.4: loaded six frozen (u, Sk) pairs at 10000 steps; stripe targets unchanged')
            continue

        # --- 13.9: regenerate derivatives target with the corrected A_z inner-boundary parity ---
        if spec.get('_type') == 'maxwell_az_parity_fix':
            import importlib.util
            ref_path = os.path.join(ROOT, 'scicode_verified', 'refs', 'p13_ref.py')
            rspec = importlib.util.spec_from_file_location('p13_ref', ref_path)
            ref = importlib.util.module_from_spec(rspec)
            rspec.loader.exec_module(ref)
            setups = ref.field_setups()
            for i, fields in enumerate(setups):
                mw = ref.Maxwell(50, 2)
                out = ref.derivatives(mw, fields)
                gp = f'{step}/test{i+1}'
                old = np.asarray(f[f'{gp}/var1'][()])
                # faithfulness self-check: the reference must match the prior gold target on
                # the 6 UNAFFECTED components; only A_z (component 5) may change.
                for c in (0, 1, 2, 3, 4, 6):
                    md = float(np.abs(np.asarray(out[c]) - old[c]).max())
                    assert md < 1e-9, f'{step} test{i+1} comp{c} drifted {md:.2e} (ref not faithful to gold)'
                az = float(np.abs(np.asarray(out[5]) - old[5]).max())
                assert az > 1e-3, f'{step} test{i+1} A_z unchanged ({az:.2e}) — fix not applied'
                # MINIMAL diff: keep gold's exact bytes for the 6 unaffected components,
                # splice in ONLY the corrected A_z (component 5).
                fixed = old.copy()
                fixed[5] = np.asarray(out[5])
                if gp in f:
                    del f[gp]
                f.create_group(gp).create_dataset('var1', data=fixed)
            print(f'  transform {step}: regenerated {len(setups)} tests with corrected A_z parity (-,-,-) (self-check OK)')
            continue

        # --- 13.10: update_fields(derivatives(...)) — inherits 13.9's A_z fix via the linear update ---
        if spec.get('_type') == 'maxwell_az_parity_fix_step10':
            import importlib.util
            ref_path = os.path.join(ROOT, 'scicode_verified', 'refs', 'p13_ref.py')
            rspec = importlib.util.spec_from_file_location('p13_ref', ref_path)
            ref = importlib.util.module_from_spec(rspec)
            rspec.loader.exec_module(ref)
            setups = ref.step10_setups()
            for i, (fields, factor, dt) in enumerate(setups):
                mw = ref.Maxwell(50, 2)
                fd = ref.derivatives(mw, fields)
                out = ref.update_fields(mw, list(fields), fd, factor, dt)
                gp = f'{step}/test{i+1}'
                old = np.asarray(f[f'{gp}/var1'][()])
                for c in (0, 1, 2, 3, 4, 6):
                    md = float(np.abs(np.asarray(out[c]) - old[c]).max())
                    assert md < 1e-9, f'{step} test{i+1} comp{c} drifted {md:.2e} (ref not faithful to gold)'
                az = float(np.abs(np.asarray(out[5]) - old[5]).max())
                assert az > 1e-3, f'{step} test{i+1} A_z unchanged ({az:.2e}) — fix not applied'
                fixed = old.copy()
                fixed[5] = np.asarray(out[5])
                if gp in f:
                    del f[gp]
                f.create_group(gp).create_dataset('var1', data=fixed)
            print(f'  transform {step}: regenerated {len(setups)} tests via update_fields w/ corrected A_z (self-check OK)')
            continue

        # --- 13.11/13.12/13.13/13.15: evolution-test redesign (R5). Converged RK4 reference
        #     on physical inputs; targets are field states (11/13), a scalar ‖divE‖ (12), or a
        #     constraint series (15). See targets/13.json + p13_ref.py + the R5 design doc. ---
        if spec.get('_type') == 'maxwell_evolution_ref':
            import importlib.util
            ref_path = os.path.join(ROOT, 'scicode_verified', 'refs', 'p13_ref.py')
            rspec = importlib.util.spec_from_file_location('p13_ref', ref_path)
            ref = importlib.util.module_from_spec(rspec)
            rspec.loader.exec_module(ref)
            for i, tc in enumerate(spec['tests']):
                fn = getattr(ref, tc['fn'])
                if tc['fn'] in ('ref_stepper', 'ref_integrate'):
                    val = np.asarray(fn(tc['config']))
                    # non-vacuity self-check: config1 develops only a SMALL E_z (sub-dominant;
                    # z-physics is incidental), config2 makes E_z DOMINANT so the A_z/E_z parity
                    # bug is detectable with large margin.
                    ez = float(np.abs(val[2]).max())
                    if tc['config'] == 1:
                        assert ez < 0.05, f'{step} test{i+1} config1 E_z={ez:.2e} unexpectedly large'
                    else:
                        assert ez > 0.1, f'{step} test{i+1} config2 E_z={ez:.2e} should be >0.1 (z-excited)'
                    assert np.all(np.isfinite(val)), f'{step} test{i+1} non-finite reference'
                elif tc['fn'] == 'ref_check_constraint':
                    val = np.asarray(float(fn(tc['which'])))
                    assert np.isfinite(val), f'{step} test{i+1} non-finite constraint'
                elif tc['fn'] == 'ref_main_series':
                    val = np.asarray(fn(tc['n_grid'], tc['x_out']))
                    assert val.ndim == 1 and np.all(np.isfinite(val)) and np.all(val >= 0), \
                        f'{step} test{i+1} bad series {val}'
                else:
                    raise ValueError(f'{step}: unknown maxwell_evolution_ref fn {tc["fn"]}')
                gp = f'{step}/test{i+1}'
                if gp in f:
                    del f[gp]
                f.create_group(gp).create_dataset('var1', data=val)
            # cross-test self-checks
            if step == '13.12':
                dip = float(np.asarray(f[f'{step}/test1/var1'][()]))
                lin = float(np.asarray(f[f'{step}/test2/var1'][()]))
                assert dip < lin, f'13.12 dipole constraint {dip} should be < linear {lin}'
            print(f'  transform {step}: regenerated {len(spec["tests"])} tests via maxwell_evolution_ref (self-check OK)')
            continue

        # --- 8.1: regenerate (T, filtered_image) with a STRICT cross-band boundary ---
        if spec.get('_type') == 'cshband_pass_strict':
            from numpy.fft import fft2, ifft2, fftshift, ifftshift
            tests = spec['tests']
            for i, tc in enumerate(tests):
                mat = np.array(tc['matrix'], dtype=float)
                ty, tx = tc['tile']
                img = np.tile(mat, (ty, tx))
                bw = tc['bandwidth']
                m, n = img.shape
                u = np.arange(n) - n // 2
                v = np.arange(m) - m // 2
                U, V = np.meshgrid(u, v)
                T = ((np.abs(U) > bw) & (np.abs(V) > bw)).astype(float)
                filt = np.real(ifft2(ifftshift(fftshift(fft2(img)) * T)))
                gp = f'{step}/test{i+1}'
                if gp in f:
                    del f[gp]
                g = f.create_group(gp)
                g.create_dataset('var1', data=T)
                g.create_dataset('var2', data=filt)
            print(f'  transform {step}: regenerated {len(tests)} tests with strict cross-band boundary (>)')
            continue

        # --- 28.1: regenerate (P1,P2) with the prompt's Fresnel transfer-function method ---
        if spec.get('_type') == 'gaussian_fresnel_tf':
            for i, c in enumerate(spec['configs']):
                N, Ld, w0, z, L = c['N'], c['Ld'], c['w0'], c['z'], c['L']
                M = N + 1
                x = np.linspace(-L / 2.0, L / 2.0, M); dx = L / N
                X, Y = np.meshgrid(x, x, indexing='ij')
                E0 = np.exp(-(X**2 + Y**2) / w0**2)
                fx = np.fft.fftfreq(M, d=dx); FX, FY = np.meshgrid(fx, fx, indexing='ij')
                H = np.exp(-1j * np.pi * Ld * z * (FX**2 + FY**2))
                Ep = np.fft.ifft2(np.fft.fft2(E0) * H)
                dA = (L / N)**2
                P1 = float(np.sum(np.abs(E0)) * dA); P2 = float(np.sum(np.abs(Ep)) * dA)
                gp = f'{step}/test{i+1}'
                if gp in f:
                    del f[gp]
                g = f.create_group(gp)
                g.create_dataset('var1', data=P1); g.create_dataset('var2', data=P2)
            exp = spec.get('verify_P2_fresnel')
            if exp:
                got = [float(np.asarray(f[f'{step}/test{i+1}/var2'][()])) for i in range(len(exp))]
                assert all(abs(a - b) < 1e-9 for a, b in zip(got, exp)), f'{step} P2 mismatch: {got} != {exp}'
            print(f'  transform {step}: regenerated {len(spec["configs"])} tests via Fresnel-TF (P2-check OK)')
            continue

        # --- 40.3: regenerate final u with the physically self-consistent split-operator scheme ---
        if spec.get('_type') == 'split_operator_physical':
            def _sd(target, u, dx):
                n = len(u)
                if target == 0: l, r = u[0], u[1]
                elif target == n - 1: l, r = u[target - 1], u[target]
                else: l, r = u[target - 1], u[target + 1]
                return (r - 2 * u[target] + l) / (dx * dx)
            def _strang(u, dt, dx, alpha):
                uh = u + 0.5 * dt * u**2
                d = np.array([_sd(i, uh, dx) for i in range(len(u))])
                ut = uh + dt * alpha * d
                return ut + 0.5 * dt * ut**2
            for i, c in enumerate(spec['configs']):
                CFL, T, dt, alpha = c['CFL'], c['T'], c['dt'], c['alpha']
                N = round(2 / (dt / CFL)) + 2
                x = np.linspace(-1, 1, N); dx = x[1] - x[0]
                u = np.where(x < 0, -1.0, 1.0)
                for _ in range(round(T / dt)): u = _strang(u, dt, dx, alpha)
                gp = f'{step}/test{i+1}'
                if gp in f: del f[gp]
                f.create_group(gp).create_dataset('var1', data=u)
            exp = spec.get('verify_first3')
            if exp:
                for i, e in enumerate(exp):
                    got = [float(v) for v in f[f'{step}/test{i+1}/var1'][()][:3]]
                    assert all(abs(a - b) < 1e-5 for a, b in zip(got, e)), f'{step} test{i+1}: {got} != {e}'
            print(f'  transform {step}: regenerated {len(spec["configs"])} tests via physical split-operator (real dx + exact-T)')
            continue

        # --- 28.3 legacy: var3 -> var3**2 ---
        squared = 0
        for t in sorted([k for k in f[step] if k.startswith('test')], key=lambda t: int(t[4:])):
            g = f[f'{step}/{t}']
            if 'var3' not in g: continue
            arr = np.asarray(g['var3'][()])
            if arr.ndim == 2 and np.issubdtype(arr.dtype, np.floating):
                del g['var3']; g.create_dataset('var3', data=arr ** 2); squared += 1
        exp = spec.get('verify_corner_new_intensity')
        if exp:
            got = [float(np.asarray(f[f'{step}/test{i+1}/var3'][()]).flat[0]) for i in range(len(exp))]
            assert all(abs(a - b) < 1e-9 for a, b in zip(got, exp)), f'{step} corner mismatch: {got} != {exp}'
        print(f'  transform {step}: squared Intensity in {squared} tests (corner-check OK)')

    # --- trim orphan tests: h5 must not have more test{N} than the SSOT has test_cases ---
    trimmed = []
    for sn, ntc in sorted(step_ntc.items(), key=lambda kv: skey(kv[0])):
        if sn in SKIP_STEPS or sn not in f:
            continue
        h5tests = sorted((k for k in f[sn] if k.startswith('test')), key=lambda x: int(x[4:]))
        if len(h5tests) < ntc:
            print(f'  WARNING: {sn} has {len(h5tests)} h5 targets but {ntc} test_cases (MISSING target!)')
        for t in h5tests:
            if int(t[4:]) > ntc:
                del f[f'{sn}/{t}']
                trimmed.append(f'{sn}/{t}')
    if trimmed:
        print(f'  trimmed {len(trimmed)} orphan test target(s): {", ".join(trimmed)}')

print(f'wrote {OUT} with {len(patches)} patched steps and {len(transforms)} transform steps')

# sanity: tests added in cleaning + transform landed
with h5py.File(OUT, 'r') as f:
    for step in ['37.1', '37.2', '45.3', '79.1', '73.9']:
        if step in f:
            print(f'  {step}: tests =', sorted([k for k in f[step] if k.startswith('test')], key=lambda t: int(t[4:])))
    if '28.3' in f:
        print('  28.3 var3 corners =', [round(float(np.asarray(f[f'28.3/test{i}/var3'][()]).flat[0]), 9) for i in (1, 2, 3)])
