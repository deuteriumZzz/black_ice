def is_match(score: float, threshold: float) -> bool:
    """Access decision: score is cosine similarity in [-1, 1]. Open-set: below
    threshold means UNKNOWN, never "closest guess" (spec section 4)."""
    return score >= threshold
