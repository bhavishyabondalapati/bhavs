"""Implicit-feedback ALS (Hu, Koren & Volinsky 2008), written from scratch with numpy so every step is visible.

Model: preference p_ui = 1 for observed pairs; confidence c_ui = 1 + alpha * w_ui (w = engagement, 1 for plain
implicit). Minimise  sum_ui c_ui (p_ui - x_u . y_i)^2 + reg (|X|^2 + |Y|^2)  by alternating exact solves:
    x_u = (Y'Y + alpha * Y_u' W_u Y_u + reg I)^-1  (1 + alpha w) summed over u's items
Only the observed items enter the per-user correction, so a sweep costs O(nnz * f^2), not O(users * items).
"""
import numpy as np


def _solve_side(R, fixed, reg, alpha):
    f = fixed.shape[1]
    gram = fixed.T @ fixed + reg * np.eye(f, dtype=np.float64)
    out = np.zeros((R.shape[0], f), dtype=np.float64)
    indptr, indices, data = R.indptr, R.indices, R.data
    for u in range(R.shape[0]):
        s, e = indptr[u], indptr[u + 1]
        if s == e:
            continue
        y = fixed[indices[s:e]]
        w = data[s:e].astype(np.float64)
        a = gram + alpha * (y.T * w) @ y
        b = ((1.0 + alpha * w)[:, None] * y).sum(axis=0)
        out[u] = np.linalg.solve(a, b)
    return out


class ALS:
    name = "als"

    def __init__(self, factors=64, reg=0.1, alpha=20.0, iterations=15, seed=0):
        self.factors, self.reg, self.alpha, self.iterations, self.seed = factors, reg, alpha, iterations, seed

    def fit(self, split, **_):
        rng = np.random.default_rng(self.seed)
        R, Rt = split.train.tocsr(), split.train.T.tocsr()
        self.X = np.zeros((split.n_users, self.factors))
        self.Y = rng.normal(0, 0.1, (split.n_items, self.factors))
        for _ in range(self.iterations):
            self.X = _solve_side(R, self.Y, self.reg, self.alpha)
            self.Y = _solve_side(Rt, self.X, self.reg, self.alpha)
        return self

    def score(self, users):
        return self.X[users] @ self.Y.T

    def item_vectors(self):
        v = self.Y
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
