"""Compares the shadow model's decisions against the primary model's, correlated
by (frame_id, track_id) — both consumers evaluated the exact same detected face,
just through different embedding models and galleries. Run this before promoting
a shadow model to primary (spec: "Shadow-mode деплой новой модели эмбеддингов
перед переключением").

Usage: python scripts/shadow_report.py [--model-version buffalo_s]
"""
import argparse
import logging
from collections import Counter

from black_ice_common.db import AuditLog, SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("shadow_report")


def compare(model_version: str) -> dict:
    with SessionLocal() as session:
        primary_rows = session.query(AuditLog).filter(AuditLog.model_version == "primary", AuditLog.frame_id.isnot(None)).all()
        shadow_rows = session.query(AuditLog).filter(AuditLog.model_version == model_version, AuditLog.frame_id.isnot(None)).all()

    shadow_by_key = {(r.frame_id, r.track_id): r for r in shadow_rows}

    outcomes = Counter()
    compared = 0
    for primary in primary_rows:
        shadow = shadow_by_key.get((primary.frame_id, primary.track_id))
        if shadow is None:
            continue
        compared += 1
        if primary.matched == shadow.matched and primary.identity_id == shadow.identity_id:
            outcomes["agree"] += 1
        elif primary.matched and not shadow.matched:
            outcomes["primary_matched_shadow_did_not"] += 1
        elif shadow.matched and not primary.matched:
            outcomes["shadow_matched_primary_did_not"] += 1
        else:
            outcomes["both_matched_different_identity"] += 1

    agreement_rate = outcomes["agree"] / compared if compared else None
    result = {"compared": compared, "agreement_rate": agreement_rate, **outcomes}
    log.info("shadow vs primary (%s): %s", model_version, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-version", default="buffalo_s")
    args = parser.parse_args()
    compare(args.model_version)


if __name__ == "__main__":
    main()
