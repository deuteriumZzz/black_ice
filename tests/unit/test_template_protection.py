import numpy as np
import pytest

import black_ice_common.config as config
import black_ice_common.template_protection as tp


@pytest.fixture(autouse=True)
def _reset_matrix_cache(monkeypatch):
    monkeypatch.setattr(tp, "_matrix", None)
    monkeypatch.setattr(tp, "_matrix_seed", None)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def test_protect_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(config.settings, "template_protection_enabled", False)

    embedding = np.random.default_rng(1).standard_normal(512)
    assert np.array_equal(tp.protect(embedding), embedding)


def test_protect_preserves_cosine_similarity_exactly(monkeypatch):
    monkeypatch.setattr(config.settings, "template_protection_enabled", True)
    monkeypatch.setattr(config.settings, "template_protection_seed", "test-seed-1")
    monkeypatch.setattr(config.settings, "embedding_dim", 512)

    rng = np.random.default_rng(42)
    a = rng.standard_normal(512)
    b = rng.standard_normal(512)

    raw_similarity = _cosine(a, b)
    protected_similarity = _cosine(tp.protect(a), tp.protect(b))

    assert protected_similarity == pytest.approx(raw_similarity, abs=1e-9)


def test_protect_actually_changes_the_vector(monkeypatch):
    monkeypatch.setattr(config.settings, "template_protection_enabled", True)
    monkeypatch.setattr(config.settings, "template_protection_seed", "test-seed-1")
    monkeypatch.setattr(config.settings, "embedding_dim", 512)

    embedding = np.random.default_rng(7).standard_normal(512)
    protected = tp.protect(embedding)

    assert not np.allclose(protected, embedding), "a real transform must not just echo the input back"
    assert np.linalg.norm(protected) == pytest.approx(np.linalg.norm(embedding), abs=1e-9), "orthogonal transform preserves vector norm"


def test_protect_is_deterministic_for_the_same_seed(monkeypatch):
    monkeypatch.setattr(config.settings, "template_protection_enabled", True)
    monkeypatch.setattr(config.settings, "template_protection_seed", "test-seed-1")
    monkeypatch.setattr(config.settings, "embedding_dim", 512)

    embedding = np.random.default_rng(3).standard_normal(512)
    first = tp.protect(embedding)
    # force recomputation of the cached matrix to prove it's the seed, not caching, driving this
    tp._matrix = None
    tp._matrix_seed = None
    second = tp.protect(embedding)

    assert np.allclose(first, second)


def test_different_seeds_are_not_cross_compatible(monkeypatch):
    """This is the "cancelable" property: a leaked seed can be rotated to a
    new one, and vectors protected under the old seed no longer match
    against ones protected under the new seed for the same underlying face."""
    monkeypatch.setattr(config.settings, "template_protection_enabled", True)
    monkeypatch.setattr(config.settings, "embedding_dim", 512)
    embedding = np.random.default_rng(9).standard_normal(512)

    monkeypatch.setattr(config.settings, "template_protection_seed", "seed-a")
    tp._matrix, tp._matrix_seed = None, None
    protected_a = tp.protect(embedding)

    monkeypatch.setattr(config.settings, "template_protection_seed", "seed-b")
    tp._matrix, tp._matrix_seed = None, None
    protected_b = tp.protect(embedding)

    assert not np.allclose(protected_a, protected_b)
    # a query protected under the NEW seed against a template stored under the
    # OLD seed must not spuriously look similar - similarity should collapse
    # toward "unrelated vectors" territory, not stay near 1.0.
    assert abs(_cosine(protected_a, protected_b)) < 0.3


def test_protect_raises_clearly_when_enabled_without_a_seed(monkeypatch):
    monkeypatch.setattr(config.settings, "template_protection_enabled", True)
    monkeypatch.setattr(config.settings, "template_protection_seed", None)

    with pytest.raises(RuntimeError, match="template_protection_seed"):
        tp.protect(np.random.default_rng(0).standard_normal(512))
