"""Binding of primary documents that do not name the manager.

Exchange certificates are issued to the fund (KFGD) by KASE and carry only
deal numbers and a trading account, so the manager (ЧДУ) is identified by the
deal numbers of its Trade Report.  The certificate may be uploaded before or
after the Trade Report, therefore binding is attempted in both directions.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date
from typing import Iterable, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.db_models import SourceDocument, Trade


def _close_enough(a: str, b: str) -> bool:
    """Deal numbers recognised by OCR may differ in a single digit."""
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 1


def _cert_deal_ids(doc: SourceDocument) -> list[str]:
    try:
        meta = json.loads(doc.parse_meta_json or "{}")
    except (TypeError, ValueError):
        return []
    ids = meta.get("deal_ids") or [d.get("deal_id") for d in meta.get("deals") or []]
    return [str(i) for i in ids if i]


def cdu_from_deal_ids(db: Session, deal_ids: Iterable[str],
                      around: Optional[date] = None) -> Optional[int]:
    """The manager whose active trades carry most of the given deal numbers."""
    ids = {str(i).strip() for i in deal_ids if i}
    if not ids:
        return None
    q = select(Trade.cdu_id, Trade.deal_id).where(Trade.deal_id.is_not(None), Trade.is_active.is_(True))
    if around is not None:
        q = q.where(Trade.trade_date == around)
    rows = db.execute(q).all()
    votes: Counter = Counter()
    for cdu_id, deal_id in rows:
        d = str(deal_id).strip()
        if d in ids:
            votes[cdu_id] += 2
        elif any(_close_enough(d, i) for i in ids):
            votes[cdu_id] += 1
    if not votes:
        return None
    (best, score), *rest = votes.most_common()
    if rest and rest[0][1] == score:
        logger.warning("Certificate deals match several managers equally: {}", dict(votes))
        return None
    return best


def bind_certificate(db: Session, doc: SourceDocument) -> Optional[int]:
    if doc.cdu_id is not None or doc.doc_type != "CERTIFICATE":
        return doc.cdu_id
    cdu_id = cdu_from_deal_ids(db, _cert_deal_ids(doc), doc.doc_date) \
        or cdu_from_deal_ids(db, _cert_deal_ids(doc))
    if cdu_id:
        doc.cdu_id = cdu_id
        logger.info("Certificate #{} bound to CDU {} by deal numbers", doc.id, cdu_id)
    return cdu_id


def bind_orphan_certificates(db: Session, trade_date: Optional[date] = None) -> int:
    """Bind unbound certificates (e.g. uploaded before the Trade Report)."""
    q = select(SourceDocument).where(
        SourceDocument.doc_type == "CERTIFICATE",
        SourceDocument.cdu_id.is_(None),
        SourceDocument.parse_status == "OK",
    )
    if trade_date is not None:
        q = q.where((SourceDocument.doc_date == trade_date) | SourceDocument.doc_date.is_(None))
    bound = 0
    for doc in db.execute(q).scalars().all():
        if bind_certificate(db, doc):
            bound += 1
    if bound:
        db.flush()
    return bound
