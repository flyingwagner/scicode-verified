"""Regression tests for the actual 55.4 assertions and frozen-array loader.

No model execution, long time integration, or large released HDF5 is required.
The tests use the small frozen NPZ and temporary HDF5 fixtures only.

Run from the repository root:
    python -m unittest discover -s tests -p 'test_sh_55_4.py' -v
"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import h5py
import numpy as np
from scipy.signal import find_peaks


ROOT = Path(__file__).resolve().parents[1]
ASSERT_MARKER = "assert u_out.shape"
STRIPE_FLAGS = (True, True, False, True, True, True)
STRIPE_MODES = (0.48871712319742033, 0.48871712319742033, 0.0,
                0.37764504974346114, 0.9552198317040488, 1.977082907480473)


def assertion_suffix(test):
    assert test.count(ASSERT_MARKER) == 1
    return ASSERT_MARKER + test.split(ASSERT_MARKER, 1)[1]


def snapshot(handle):
    """Record all dataset bytes/types/shapes and group/dataset attributes."""
    result = {"/": ("group", dict(handle.attrs))}

    def record(name, obj):
        if isinstance(obj, h5py.Dataset):
            value = np.asarray(obj[()])
            result[name] = ("dataset", str(obj.dtype), obj.shape,
                            value.tobytes(), dict(obj.attrs))
        else:
            result[name] = ("group", dict(obj.attrs))

    handle.visititems(record)
    return result


class SH554Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        problem = json.loads((ROOT / "scicode_verified/problems/55.json").read_text())
        step = next(s for s in problem["sub_steps"] if s["step_number"] == "55.4")
        assert len(step["test_cases"]) == 6
        assert problem["general_tests"] == step["test_cases"]
        ledger = [json.loads(line) for line in (ROOT / "ledger/R9.jsonl").read_text().splitlines()
                  if line.strip()]
        cls.new_checks, cls.old_checks = [], []
        for i, test in enumerate(step["test_cases"]):
            entry = next(e for e in ledger if str(e["id"]) == "55"
                         and e["field"] == f"sub_steps[3].test_cases[{i}]")
            assert entry["after"] == test
            assert test.startswith(entry["before"])
            cls.new_checks.append(compile(assertion_suffix(test), f"<v2.2 55.4 case {i+1}>", "exec"))
            cls.old_checks.append(compile(assertion_suffix(entry["before"]), f"<v2.1 55.4 case {i+1}>", "exec"))

        cls.target_spec = json.loads((ROOT / "scicode_verified/targets/55.json").read_text())["targets"]["55.4"]
        with np.load(ROOT / cls.target_spec["file"], allow_pickle=False) as data:
            cls.fields = [(data[f"test{i}_u"].copy(), data[f"test{i}_Sk"].copy())
                          for i in range(1, 7)]
        spec = importlib.util.spec_from_file_location("p55_reference_under_test",
                                                     ROOT / "scicode_verified/refs/p55_ref.py")
        cls.reference = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.reference)

    def output(self, case):
        u, sk = self.fields[case]
        return [u.copy(), sk.copy(), STRIPE_FLAGS[case], STRIPE_MODES[case]]

    def execute(self, case, output, *, legacy=False):
        target = (*self.fields[case], STRIPE_FLAGS[case], STRIPE_MODES[case])
        ns = {"np": np, "N": self.fields[case][0].shape[0], "target": target,
              "u_out": output[0], "Sk_out": output[1],
              "if_form_stripes": output[2], "stripe_mode": output[3]}
        exec(self.old_checks[case] if legacy else self.new_checks[case], ns)

    def reject(self, case, output, *, legacy=False):
        with self.assertRaises((AssertionError, ValueError, TypeError)):
            self.execute(case, output, legacy=legacy)

    def test_all_six_frozen_outputs_pass(self):
        for case in range(6):
            with self.subTest(case=case+1):
                self.execute(case, self.output(case), legacy=True)
                self.execute(case, self.output(case))

    def test_frozen_fields_and_spectra_are_consistent(self):
        for case, (u, sk) in enumerate(self.fields):
            with self.subTest(case=case+1):
                np.testing.assert_allclose(sk, np.fft.fftshift(np.abs(np.fft.fft2(u))**2),
                                           atol=5e-9, rtol=5e-9)

    def test_stripe_summaries_match_frozen_fields(self):
        # Only FFT/histogram/peak analysis, not a new numerical evolution.
        for case, (_, sk) in enumerate(self.fields):
            n = sk.shape[0]
            q0 = self.target_spec["cases"][case]["q0"]
            k = np.fft.fftshift(2 * np.pi * np.fft.fftfreq(n, d=1.0))
            kr = np.sqrt(k[:, None]**2 + k[None, :]**2)
            counts, edges = np.histogram(kr, bins=n//2)
            sums, _ = np.histogram(kr, bins=n//2, weights=sk)
            profile = sums / np.maximum(counts, 1)
            centers = 0.5 * (edges[:-1] + edges[1:])
            peaks, _ = find_peaks(profile, height=1e-12)
            flag, mode = False, 0.0
            if len(peaks):
                closest = peaks[np.argmin(np.abs(centers[peaks] - q0))]
                if abs(centers[closest] - q0) <= 0.5*q0:
                    flag, mode = True, float(centers[closest])
            with self.subTest(case=case+1):
                self.assertEqual(flag, STRIPE_FLAGS[case])
                self.assertAlmostEqual(mode, STRIPE_MODES[case], places=12)

    def test_wrong_field_with_correct_spectrum_and_summary_is_rejected(self):
        for case in range(6):
            with self.subTest(case=case+1):
                out = self.output(case)
                out[0][0, 0] += 1e-3
                self.execute(case, out, legacy=True)
                self.reject(case, out)

    def test_wrong_spectrum_with_correct_field_and_summary_is_rejected(self):
        for case in range(6):
            with self.subTest(case=case+1):
                out = self.output(case)
                out[1][0, 0] += 1.0
                self.execute(case, out, legacy=True)
                self.reject(case, out)

    def test_consistent_zero_arrays_with_stripe_summaries_are_rejected(self):
        for case in (0, 1, 3, 4, 5):
            with self.subTest(case=case+1):
                out = self.output(case)
                out[0].fill(0)
                out[1].fill(0)
                self.execute(case, out, legacy=True)
                self.reject(case, out)

    def test_near_zero_decay_retains_absolute_error_floor(self):
        out = self.output(2)
        out[0].fill(0)
        out[1].fill(0)
        self.execute(2, out)

    def test_roundoff_sized_perturbations_are_accepted(self):
        for case in range(6):
            with self.subTest(case=case+1):
                out = self.output(case)
                out[0] = out[0]*(1 + 1e-12) + 1e-12
                out[1] = out[1]*(1 + 1e-12) + 1e-12
                self.execute(case, out)

    def test_wrong_stripe_flag_is_still_rejected(self):
        for case in range(6):
            with self.subTest(case=case+1):
                out = self.output(case)
                out[2] = not out[2]
                self.reject(case, out, legacy=True)
                self.reject(case, out)

    def test_wrong_stripe_mode_is_still_rejected(self):
        for case in range(6):
            with self.subTest(case=case+1):
                out = self.output(case)
                out[3] += 0.1
                self.reject(case, out, legacy=True)
                self.reject(case, out)

    def test_wrong_array_shape_is_rejected(self):
        for field in (0, 1):
            out = self.output(0)
            out[field] = out[field][:-1]
            self.reject(0, out, legacy=True)
            self.reject(0, out)

    def test_nonfinite_arrays_are_rejected(self):
        for field in (0, 1):
            for invalid in (np.nan, np.inf, -np.inf):
                with self.subTest(field=field, invalid=invalid):
                    out = self.output(0)
                    out[field][0, 0] = invalid
                    self.execute(0, out, legacy=True)
                    self.reject(0, out)

    def make_h5_fixture(self, path):
        with h5py.File(path, "w") as handle:
            handle.attrs["release_note"] = "preserve root attributes"
            for i, (u, sk) in enumerate(self.fields, 1):
                g = handle.create_group(f"55.4/test{i}")
                g.attrs["note"] = f"preserve test{i} attributes"
                d = g.create_dataset("var1", data=np.full_like(u, 7.0))
                d.attrs["unit"] = "order parameter"
                g.create_dataset("var2", data=np.full_like(sk, 9.0))
                g.create_dataset("var3", data=np.bool_(STRIPE_FLAGS[i-1]))
                g.create_dataset("var4", data=np.float64(STRIPE_MODES[i-1]))
            handle.create_dataset("55.1/test1/var1", data=np.arange(4.0))
            handle.create_dataset("62.5/test1/var1", data=np.int32(2))

    def test_loader_changes_only_twelve_arrays(self):
        with tempfile.TemporaryDirectory(prefix="scicode-554-test-") as tmp:
            path = Path(tmp) / "fixture.h5"
            self.make_h5_fixture(path)
            with h5py.File(path, "a") as handle:
                before = snapshot(handle)
                self.reference.apply_frozen_arrays(handle, deepcopy(self.target_spec), ROOT)
                after = snapshot(handle)
                changed = {k for k in before if before[k] != after[k]}
                expected = {f"55.4/test{i}/var{j}" for i in range(1, 7) for j in (1, 2)}
                self.assertEqual(before.keys(), after.keys())
                self.assertEqual(changed, expected)
                for i, fields in enumerate(self.fields, 1):
                    for j, values in enumerate(fields, 1):
                        np.testing.assert_array_equal(handle[f"55.4/test{i}/var{j}"][()], values)
                # An idempotent second application must leave all data intact.
                self.reference.apply_frozen_arrays(handle, deepcopy(self.target_spec), ROOT)
                self.assertEqual(after, snapshot(handle))

    def test_loader_rejects_wrong_checksum_before_any_write(self):
        with tempfile.TemporaryDirectory(prefix="scicode-554-hash-") as tmp:
            path = Path(tmp) / "fixture.h5"
            self.make_h5_fixture(path)
            spec = deepcopy(self.target_spec)
            spec["sha256"] = "0" * 64
            with h5py.File(path, "a") as handle:
                before = snapshot(handle)
                with self.assertRaisesRegex(AssertionError, "checksum mismatch"):
                    self.reference.apply_frozen_arrays(handle, spec, ROOT)
                self.assertEqual(before, snapshot(handle))

    def test_loader_requires_checksum(self):
        with tempfile.TemporaryDirectory(prefix="scicode-554-nohash-") as tmp:
            path = Path(tmp) / "fixture.h5"
            self.make_h5_fixture(path)
            spec = deepcopy(self.target_spec)
            del spec["sha256"]
            with h5py.File(path, "a") as handle:
                before = snapshot(handle)
                with self.assertRaises(KeyError):
                    self.reference.apply_frozen_arrays(handle, spec, ROOT)
                self.assertEqual(before, snapshot(handle))

    def test_loader_rejects_a_different_time_contract(self):
        with tempfile.TemporaryDirectory(prefix="scicode-554-time-") as tmp:
            path = Path(tmp) / "fixture.h5"
            self.make_h5_fixture(path)
            spec = deepcopy(self.target_spec)
            spec["steps"] = 9999
            with h5py.File(path, "a") as handle:
                before = snapshot(handle)
                with self.assertRaises(AssertionError):
                    self.reference.apply_frozen_arrays(handle, spec, ROOT)
                self.assertEqual(before, snapshot(handle))


if __name__ == "__main__":
    unittest.main()
