import numpy as np


class Popularity:
    """The bar to beat: every user gets the same ranking, most-interacted-with items first."""

    name = "popularity"

    def fit(self, split, **_):
        self.counts = np.asarray(split.train.astype(bool).sum(axis=0)).ravel().astype(np.float32)
        return self

    def score(self, users):
        return np.tile(self.counts, (len(users), 1))
