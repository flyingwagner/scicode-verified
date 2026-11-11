"""Regression tests for the released 62.5 verifier; no model calls or large H5.

Run from the repository root:
    python -m unittest discover -s tests -p 'test_joint_basis_62_5.py' -v

The test executes the actual assertion suffix of the dataset's test case,
with synthetic Block outputs. Its reference tuple is the same full-space
two-spin Heisenberg problem, represented in the product basis. No gold
numerical artifacts are required to exercise the verifier.
"""

from pathlib import Path
from types import SimpleNamespace
import json
import unittest

import numpy as np
from scipy.sparse import csr_matrix


ROOT = Path(__file__).resolve().parents[1]
KEYS = ("H", "conn_Sz", "conn_Sp")
CALL_LINE = "newblock, energy = dmrg_module(sys, env, m, model_d)\n"
REJECTION_ERRORS = (AssertionError, ValueError, np.linalg.LinAlgError)


def assertion_suffix(test):
    assert test.count(CALL_LINE) == 1
    return test.split(CALL_LINE, 1)[1]


def fixture():
    sz = np.diag([0.5, -0.5])
    sp = np.array([[0.0, 1.0], [0.0, 0.0]])
    sm = sp.T
    h = np.kron(sz, sz) + 0.5 * (np.kron(sp, sm) + np.kron(sm, sp))
    return {"H": h, "conn_Sz": np.kron(np.eye(2), sz),
            "conn_Sp": np.kron(np.eye(2), sp)}


def random_unitary(rng, complex_values=True):
    a = rng.standard_normal((4, 4))
    if complex_values:
        a = a + 1j * rng.standard_normal((4, 4))
    q, _ = np.linalg.qr(a)
    return q


def rotate(ops, u):
    return {k: u.conj().T @ a @ u for k, a in ops.items()}


class JointBasis625Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        problem = json.loads((ROOT / "scicode_verified/problems/62.json").read_text())
        step = next(s for s in problem["sub_steps"] if s["step_number"] == "62.5")
        assert len(step["test_cases"]) == 1
        cls.new_assertions = compile(assertion_suffix(step["test_cases"][0]),
                                     "<released 62.5 assertions>", "exec")
        entries = [json.loads(line) for line in (ROOT / "ledger/R8.jsonl").read_text().splitlines()
                   if line.strip()]
        entry = next(e for e in entries if e["id"] == "62"
                     and e["field"] == "sub_steps[4].test_cases[0]")
        assert entry["after"] == step["test_cases"][0]
        cls.old_assertions = compile(assertion_suffix(entry["before"]),
                                     "<v2 62.5 assertions>", "exec")

    def setUp(self):
        self.ref = fixture()
        # The energy is independently checked, not used to fit the basis map.
        self.energy = -1.61602540378444

    def execute(self, operators, *, legacy=False, energy=None, length=2, basis_size=4):
        ns = {
            "np": np,
            "newblock": SimpleNamespace(length=length, basis_size=basis_size,
                                        operator_dict=operators),
            "energy": self.energy if energy is None else energy,
            "target": (2, 4, self.ref, self.energy),
        }
        exec(self.old_assertions if legacy else self.new_assertions, ns)
        return ns

    def reject(self, operators, **kwargs):
        with self.assertRaises(REJECTION_ERRORS):
            self.execute(operators, **kwargs)

    def test_identity(self):
        self.execute(self.ref)

    def test_permutation_and_sign_changes(self):
        u = np.eye(4)[:, [2, 0, 3, 1]] @ np.diag([-1.0, 1.0, -1.0, 1.0])
        self.execute(rotate(self.ref, u))

    def test_complex_phase_changes(self):
        u = np.diag(np.exp(1j * np.array([0.1, 0.7, 1.8, -2.3])))
        self.execute(rotate(self.ref, u))

    def test_common_real_orthogonal_transform(self):
        self.execute(rotate(self.ref, random_unitary(np.random.default_rng(625), False)))

    def test_50_common_complex_unitaries(self):
        rng = np.random.default_rng(625)
        for i in range(50):
            with self.subTest(case=i):
                self.execute(rotate(self.ref, random_unitary(rng)))

    def test_50_inconsistent_rotations_pass_old_but_fail_new(self):
        rng = np.random.default_rng(626)
        for i in range(50):
            with self.subTest(case=i):
                out = rotate(self.ref, random_unitary(rng))
                v = random_unitary(rng)
                out["conn_Sz"] = v.conj().T @ self.ref["conn_Sz"] @ v
                self.execute(out, legacy=True)
                self.reject(out)

    def test_transposed_ladder_operator_passes_old_but_fails_new(self):
        out = {k: a.copy() for k, a in self.ref.items()}
        out["conn_Sp"] = out["conn_Sp"].T
        self.execute(out, legacy=True)
        self.reject(out)

    def test_ladder_only_conjugation_passes_old_but_fails_new(self):
        out = rotate(self.ref, random_unitary(np.random.default_rng(627)))
        out["conn_Sp"] = out["conn_Sp"].conj()
        self.execute(out, legacy=True)
        self.reject(out)

    def test_nonhermitian_hamiltonian_passes_old_but_fails_new(self):
        out = {k: a.copy() for k, a in self.ref.items()}
        # eigvalsh uses the lower triangle by default: corrupting only the
        # upper triangle is invisible to the old spectral check.
        out["H"][0, 1] += 0.2
        self.execute(out, legacy=True)
        self.reject(out)

    def test_sparse_outputs(self):
        out = rotate(self.ref, random_unitary(np.random.default_rng(628), False))
        self.execute({k: csr_matrix(a) for k, a in out.items()})

    def test_roundoff_level_noise_is_accepted(self):
        rng = np.random.default_rng(629)
        out = rotate(self.ref, random_unitary(rng))
        for k in out:
            out[k] += 1e-12 * (rng.standard_normal((4, 4))
                               + 1j * rng.standard_normal((4, 4)))
        self.execute(out)

    def test_wrong_energy_is_rejected(self):
        self.reject(self.ref, energy=self.energy + 0.1)

    def test_wrong_block_metadata_is_rejected(self):
        self.reject(self.ref, length=3)
        self.reject(self.ref, basis_size=3)

    def test_wrong_shape_is_rejected(self):
        out = {k: a.copy() for k, a in self.ref.items()}
        out["H"] = out["H"][:2, :2]
        self.reject(out)

    def test_nonfinite_output_is_rejected(self):
        for invalid in (np.nan, np.inf):
            with self.subTest(invalid=invalid):
                out = {k: a.copy() for k, a in self.ref.items()}
                out["conn_Sp"][0, 0] = invalid
                self.reject(out)

    def test_fixture_has_one_dimensional_joint_intertwiner(self):
        # The single-vector SVD construction is justified for this fixture,
        # not a claim about arbitrary reducible operator tuples.
        matrices = list(self.ref.values())
        matrices += [a.conj().T for a in matrices]
        constraints = np.vstack([
            (np.kron(np.eye(4), a) - np.kron(a.T, np.eye(4)))
            / max(1.0, np.linalg.norm(a, "fro"))
            for a in matrices
        ])
        singular_values = np.linalg.svd(constraints, compute_uv=False)
        self.assertEqual(np.count_nonzero(singular_values < 1e-10), 1)
        self.assertGreater(singular_values[-2], 0.5)


if __name__ == "__main__":
    unittest.main()
