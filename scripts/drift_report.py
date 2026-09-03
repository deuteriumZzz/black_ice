"""Accuracy drift monitoring (spec: "Drift monitoring точности со временем").
Production has no ground truth to measure accuracy against directly, so this
watches a proxy instead: whether the distribution of match scores against the
*same enrolled gallery* has shifted between a baseline window and a recent one.
A shift can mean the embedding model is drifting, the population at the camera
changed, lighting/camera hardware changed, or the gallery itself grew stale —
this flags *that something changed*, it doesn't diagnose which.

Meant to run periodically (K8s CronJob, like scripts/purge_expired.py) and push
results to a Prometheus Pushgateway so a normal Prometheus alert rule can fire
on it — a CronJob's own process doesn't live long enough for Prometheus to
scrape it directly.
"""
import argparse
import datetime
import logging

import numpy as np
from scipy.stats import ks_2samp

from black_ice_common.db import AuditLog, SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("drift_report")


def detect_score_drift(baseline_scores: np.ndarray, recent_scores: np.ndarray, ks_pvalue_threshold: float = 0.01) -> dict:
    """Two-sample Kolmogorov-Smirnov test on confirmed-match cosine-similarity
    scores. A low p-value means the two windows are unlikely to be the same
    underlying distribution — i.e. something about the scoring behavior shifted."""
    if len(baseline_scores) < 30 or len(recent_scores) < 30:
        return {"insufficient_data": True, "baseline_n": len(baseline_scores), "recent_n": len(recent_scores)}

    stat, pvalue = ks_2samp(baseline_scores, recent_scores)
    return {
        "insufficient_data": False,
        "baseline_n": len(baseline_scores),
        "recent_n": len(recent_scores),
        "baseline_mean": float(np.mean(baseline_scores)),
        "recent_mean": float(np.mean(recent_scores)),
        "ks_statistic": float(stat),
        "ks_pvalue": float(pvalue),
        "drift_detected": bool(pvalue < ks_pvalue_threshold),
    }


def unknown_rate(matched_flags: list[bool]) -> float:
    if not matched_flags:
        return 0.0
    return 1.0 - (sum(matched_flags) / len(matched_flags))


def _fetch_window(session, start: datetime.datetime, end: datetime.datetime):
    rows = session.query(AuditLog).filter(AuditLog.ts >= start, AuditLog.ts < end).all()
    scores = np.array([r.score for r in rows if r.matched])
    matched_flags = [r.matched for r in rows]
    return scores, matched_flags


def push_to_gateway(pushgateway_url: str, result: dict, baseline_unknown_rate: float, recent_unknown_rate: float) -> None:
    from prometheus_client import CollectorRegistry, Gauge, push_to_gateway as _push

    registry = CollectorRegistry()
    Gauge("black_ice_drift_ks_statistic", "KS statistic between baseline/recent match-score distributions", registry=registry).set(
        result.get("ks_statistic", 0.0)
    )
    Gauge("black_ice_drift_ks_pvalue", "KS test p-value", registry=registry).set(result.get("ks_pvalue", 1.0))
    Gauge("black_ice_drift_detected", "1 if drift detected this run, else 0", registry=registry).set(1 if result.get("drift_detected") else 0)
    Gauge("black_ice_drift_unknown_rate_baseline", "fraction of UNKNOWN decisions, baseline window", registry=registry).set(baseline_unknown_rate)
    Gauge("black_ice_drift_unknown_rate_recent", "fraction of UNKNOWN decisions, recent window", registry=registry).set(recent_unknown_rate)
    _push(pushgateway_url, job="black_ice_drift", registry=registry)


def run(baseline_days_ago: tuple[int, int] = (14, 7), recent_days: int = 1, pushgateway_url: str | None = None) -> dict:
    now = datetime.datetime.utcnow()
    baseline_start = now - datetime.timedelta(days=baseline_days_ago[0])
    baseline_end = now - datetime.timedelta(days=baseline_days_ago[1])
    recent_start = now - datetime.timedelta(days=recent_days)

    with SessionLocal() as session:
        baseline_scores, baseline_flags = _fetch_window(session, baseline_start, baseline_end)
        recent_scores, recent_flags = _fetch_window(session, recent_start, now)

    result = detect_score_drift(baseline_scores, recent_scores)
    baseline_unknown = unknown_rate(baseline_flags)
    recent_unknown = unknown_rate(recent_flags)
    result["baseline_unknown_rate"] = baseline_unknown
    result["recent_unknown_rate"] = recent_unknown

    log.info("drift report: %s", result)

    if pushgateway_url and not result["insufficient_data"]:
        push_to_gateway(pushgateway_url, result, baseline_unknown, recent_unknown)

    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pushgateway-url", default=None, help="e.g. http://pushgateway:9091")
    parser.add_argument("--recent-days", type=int, default=1)
    args = parser.parse_args()
    run(recent_days=args.recent_days, pushgateway_url=args.pushgateway_url)


if __name__ == "__main__":
    main()
