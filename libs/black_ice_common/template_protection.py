"""Model-inversion mitigation (STATUS.md gap: awareness only, no template
protection implemented). Applies a secret random orthogonal transform to
every embedding before it's stored in or queried against Qdrant — a form of
"cancelable biometrics" (Ratha et al.): someone who steals the vector DB gets
vectors in a rotated space they can't map back to real face-embedding space
without the secret, and if the secret ever leaks, generating a new one and
re-enrolling invalidates every previously-stored template (the "cancel"
part) — a real leak-recovery story a bare hash or encryption of the raw
embedding wouldn't give, since Qdrant needs to compute similarity on the
stored vectors directly and anything that changes distances at rest would
break matching.

Orthogonal specifically because it's the one class of transform that changes
every vector component while leaving cosine similarity between any two
vectors EXACTLY unchanged (a rotation/reflection preserves dot products and
norms) — matching quality is mathematically identical to the untransformed
case, not an approximation. This is not encryption: someone with both the
secret and a stolen vector can still recover the original fully. It raises
the bar from "read the DB, done" to "also need the secret" — that's what
template protection is for, not more.

Opt-in (`template_protection_enabled=False` by default) and NOT toggleable
after real enrollments exist without a full re-enroll: flipping it changes
every vector's coordinate space, so old and new vectors stop being
comparable to each other at all.
"""
import hashlib

import numpy as np

from black_ice_common.config import settings

_matrix: np.ndarray | None = None
_matrix_seed: str | None = None


def _orthogonal_matrix(seed: str, dim: int) -> np.ndarray:
    """Deterministic per seed — this runs independently in every service
    process (no shared state), so the same seed must always regenerate the
    identical matrix. QR-decomposing a seeded random Gaussian matrix is a
    standard way to sample a (numerically) orthogonal matrix; np.linalg.qr
    is itself deterministic for a given input, so no extra bookkeeping is
    needed beyond seeding the input consistently."""
    seed_int = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % (2**32)
    rng = np.random.RandomState(seed_int)
    q, _r = np.linalg.qr(rng.standard_normal((dim, dim)))
    return q


def _get_matrix() -> np.ndarray:
    global _matrix, _matrix_seed
    seed = settings.template_protection_seed
    if not seed:
        raise RuntimeError("template_protection_enabled is True but template_protection_seed is not set")
    if _matrix is None or _matrix_seed != seed:
        _matrix = _orthogonal_matrix(seed, settings.embedding_dim)
        _matrix_seed = seed
    return _matrix


def protect(embedding: np.ndarray) -> np.ndarray:
    """No-op unless settings.template_protection_enabled is True."""
    if not settings.template_protection_enabled:
        return embedding
    return embedding @ _get_matrix()
