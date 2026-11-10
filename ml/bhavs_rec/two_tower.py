"""Two-tower retrieval model in PyTorch (runs on Apple Silicon `mps`, CUDA or CPU).

  item tower: item-id embedding + content features (genres...)            -> MLP -> unit vector
  user tower: user-id embedding + mean of the user's history item vectors -> MLP -> unit vector
  score(u, i) = cosine(user_vec, item_vec)

Training uses IN-BATCH negatives: for a batch of (user, positive item) pairs, every other user's positive item
is a negative for this user (a softmax over the batch). Popular items appear more often as in-batch negatives, so we
apply the logQ correction (subtract log of item sampling probability), and mask duplicates of the true item.
The target item is hidden from the user's own history input, otherwise the model could just copy it.
"""
import copy

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn


def pick_device():
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _history(split, length):
    """[n_users, length] most recent TRAIN items per user, padded with -1."""
    order = np.lexsort((split.train_t, split.train_u))
    u, i = split.train_u[order], split.train_i[order]
    hist = np.full((split.n_users, length), -1, dtype=np.int64)
    starts = np.r_[0, np.flatnonzero(np.diff(u)) + 1] if len(u) else np.array([], dtype=int)
    ends = np.r_[starts[1:], len(u)] if len(u) else np.array([], dtype=int)
    for s, e in zip(starts, ends, strict=True):
        h = i[max(s, e - length):e]
        hist[u[s], :len(h)] = h
    return hist


class _Net(nn.Module):
    def __init__(self, n_users, n_items, n_feat, dim):
        super().__init__()
        self.item_emb = nn.Embedding(n_items, dim)
        self.user_emb = nn.Embedding(n_users, dim)
        self.feat = nn.Linear(n_feat, dim, bias=False) if n_feat else None
        self.item_mlp = nn.Sequential(nn.Linear(dim, dim), nn.ReLU(), nn.Linear(dim, dim))
        self.user_mlp = nn.Sequential(nn.Linear(dim, dim), nn.ReLU(), nn.Linear(dim, dim))
        for e in (self.item_emb, self.user_emb):
            nn.init.normal_(e.weight, std=0.05)

    def item_base(self, ids, feats):
        x = self.item_emb(ids)
        return x + self.feat(feats[ids]) if self.feat is not None else x

    def item_vec(self, ids, feats):
        b = self.item_base(ids, feats)
        return F.normalize(b + self.item_mlp(b), dim=-1)

    def user_vec(self, uids, hist, feats, hide=None):
        valid = hist >= 0
        if hide is not None:
            valid = valid & (hist != hide[:, None])
        base = self.item_base(hist.clamp(min=0), feats) * valid.unsqueeze(-1)
        mean = base.sum(1) / valid.sum(1, keepdim=True).clamp(min=1)
        x = self.user_emb(uids) + mean
        return F.normalize(x + self.user_mlp(x), dim=-1)


class TwoTower:
    name = "two_tower"

    def __init__(self, dim=64, epochs=40, lr=2e-3, batch=2048, temp=0.07, hist_len=50, weight_decay=0.0,
                 seed=0, device=None, patience=4, eval_every=2, verbose=False):
        self.__dict__.update({"dim": dim, "epochs": epochs, "lr": lr, "batch": batch, "temp": temp, "hist_len": hist_len,
                                  "weight_decay": weight_decay, "seed": seed, "patience": patience, "eval_every": eval_every,
                                  "verbose": verbose})
        self.device = device or pick_device()

    def fit(self, split, item_features=None, eval_fn=None, **_):
        torch.manual_seed(self.seed)
        rng = np.random.default_rng(self.seed)
        dev = self.device
        feats_np = item_features if item_features is not None and item_features.shape[1] else None
        self.feats = torch.tensor(feats_np if feats_np is not None else np.zeros((split.n_items, 0), np.float32), device=dev)
        self.net = _Net(split.n_users, split.n_items, 0 if feats_np is None else feats_np.shape[1], self.dim).to(dev)
        self.hist = torch.tensor(_history(split, self.hist_len), device=dev)
        pop = np.bincount(split.train_i, minlength=split.n_items).astype(np.float64) + 1.0
        logq = torch.tensor(np.log(pop / pop.sum()), dtype=torch.float32, device=dev)
        opt = torch.optim.Adam(self.net.parameters(), lr=self.lr, weight_decay=self.weight_decay)
        tu = torch.tensor(split.train_u, device=dev)
        ti = torch.tensor(split.train_i, device=dev)
        tw = torch.tensor(split.train_w / max(1e-9, split.train_w.mean()), dtype=torch.float32, device=dev)
        n = len(split.train_u)
        best, best_state, bad = -1.0, None, 0
        self.history_log = []
        for epoch in range(1, self.epochs + 1):
            self.net.train()
            perm = torch.tensor(rng.permutation(n), device=dev)
            total = 0.0
            for s in range(0, n - self.batch + 1, self.batch):
                idx = perm[s:s + self.batch]
                u, i, w = tu[idx], ti[idx], tw[idx]
                uv = self.net.user_vec(u, self.hist[u], self.feats, hide=i)
                iv = self.net.item_vec(i, self.feats)
                logits = uv @ iv.T / self.temp - logq[i][None, :]
                same = (i[:, None] == i[None, :]) & ~torch.eye(len(i), dtype=torch.bool, device=dev)
                logits = logits.masked_fill(same, float("-inf"))
                loss = (F.cross_entropy(logits, torch.arange(len(i), device=dev), reduction="none") * w).mean()
                opt.zero_grad()
                loss.backward()
                opt.step()
                total += float(loss.detach())
            if eval_fn is not None and epoch % self.eval_every == 0:
                self._cache = None
                metric = eval_fn(self)["recall@10"]
                self.history_log.append((epoch, total, metric))
                if self.verbose:
                    print(f"  epoch {epoch:3d} loss {total:9.1f} val recall@10 {metric:.4f}", flush=True)
                if metric > best:
                    best, bad, best_state = metric, 0, copy.deepcopy(self.net.state_dict())
                else:
                    bad += 1
                    if bad >= self.patience:
                        break
        if best_state is not None:
            self.net.load_state_dict(best_state)
        self.best_val = best
        self._cache = None
        return self

    @torch.no_grad()
    def _vectors(self):
        if getattr(self, "_cache", None) is None:
            self.net.eval()
            dev = self.device
            n_items = self.net.item_emb.num_embeddings
            iv = self.net.item_vec(torch.arange(n_items, device=dev), self.feats)
            n_users = self.net.user_emb.num_embeddings
            uvs = []
            for s in range(0, n_users, 4096):
                u = torch.arange(s, min(n_users, s + 4096), device=dev)
                uvs.append(self.net.user_vec(u, self.hist[u], self.feats))
            self._cache = (torch.cat(uvs), iv)
        return self._cache

    def score(self, users):
        uv, iv = self._vectors()
        return (uv[torch.as_tensor(users, device=self.device)] @ iv.T).cpu().numpy()

    def item_vectors(self):
        return self._vectors()[1].cpu().numpy()
