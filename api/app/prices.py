"""Project checked dwelling totals, installments and fees from public metadata."""
from __future__ import annotations

import json
from pydantic import ValidationError

from app.schemas import CostPublic, PricePublic
from app.extract.price_tables import PRICE_PARSER_VERSION, PRICE_METADATA_KINDS, UNVERIFIED


def current_price_rule(rule: dict, notice) -> bool:
    """A supplemental price document needs the primary's explicit bundle proof."""
    digest = notice.get("document_hash") if isinstance(notice, dict) else notice.document_hash
    rules = notice.get("rules", []) if isinstance(notice, dict) else notice.rules or []
    if not digest or not rule.get("document_hash") or not rule.get("evidence_url"):
        return False
    if rule.get("document_hash") == digest:
        return True
    if (rule.get("kind") not in PRICE_METADATA_KINDS | {"unit_exclusive_areas"}
            or rule.get("source_document_role") != "price_table"
            or rule.get("selected_document_hash") != digest):
        return False
    return any(bundle.get("kind") == "document_bundle" and bundle.get("verification") == "official"
               and bundle.get("source") == "official_document_parser"
               and bundle.get("document_hash") == digest
               and any(entry.get("role") == "price_table" and entry.get("document_hash") == rule.get("document_hash")
                       and entry.get("url") == rule.get("evidence_url")
                       and entry.get("selected_document_hash") == digest
                       for entry in bundle.get("documents", bundle.get("entries", [])) if isinstance(entry, dict))
               for bundle in rules)


def _cost(value: dict, parent: dict) -> CostPublic | None:
    amount = value.get("amount_krw")
    if type(amount) is not int or amount < 0 or value.get("verification") != "official":
        return None
    if (value.get("document_hash") != parent.get("document_hash") or value.get("evidence_url") != parent.get("evidence_url")
            or not value.get("evidence_url") or not value.get("evidence_text")
            or type(value.get("evidence_page")) is not int or value["evidence_page"] < 1):
        return None
    try:
        return CostPublic(**{key: value[key] for key in CostPublic.model_fields if key in value})
    except ValidationError:
        return None


def project_prices(prices: list[PricePublic], rules: list[dict], preferred_hash: str | None = None) -> tuple[list[PricePublic], list[CostPublic]]:
    accepted = [rule for rule in rules if rule.get("verification") == "official"
                and rule.get("source") == "official_document_parser"
                and rule.get("price_parser_version") == PRICE_PARSER_VERSION
                and rule.get("document_hash") and rule.get("evidence_url")]
    repairs = {rule["document_hash"] for rule in accepted if rule.get("kind") == "price_extraction"
               and rule.get("identity_confirmed") is True}
    # Old model candidates stay in NoticeRevision but cannot reappear through
    # another source's aggregate after the identical bytes were reinterpreted.
    result = [price for price in prices if not (price.verification in UNVERIFIED and price.document_hash in repairs)]
    details = [entry for rule in accepted if rule.get("kind") == "price_details" for entry in rule.get("entries", [])
               if isinstance(entry, dict) and entry.get("document_hash") == rule.get("document_hash")]
    details.sort(key=lambda entry: entry.get("document_hash") != preferred_hash)
    seen: dict[tuple[str, str], str] = {}
    for entry in details:
        amount = entry.get("amount_krw")
        dwelling = entry.get("dwelling_identity")
        identifier = dwelling or entry.get("price_row_key")
        key = ("dwelling" if dwelling else "tier", identifier)
        digest = entry.get("document_hash")
        if (not isinstance(identifier, str) or not identifier or not isinstance(entry.get("unit_type"), str) or type(amount) is not int or amount <= 0
                or entry.get("verification") != "official" or not entry.get("evidence_text")):
            continue
        components = [_cost(component, entry) for component in entry.get("payment_components", []) if isinstance(component, dict)]
        if (not components or any(c is None for c in components)
                or len({c.kind for c in components if c is not None}) != len(components)
                or any(c.kind not in {"down_payment", "interim_payment", "balance", "housing_fund"} for c in components if c is not None)
                or sum(c.amount_krw for c in components if c is not None) != amount):
            continue
        matching = [price for price in result if price.unit_type == entry.get("unit_type")
                    and price.amount_krw == amount and price.price_kind in {"sale", "sale_total"}
                    and price.document_hash == entry.get("document_hash")]
        if key in seen:
            if seen[key] != digest:
                result = [price for price in result if not any(price is row for row in matching)]
            continue
        seen[key] = digest
        if matching:
            price = matching[0]
            result = [p for p in result if p is price or p not in matching]
        else:
            # The JSON row is itself a checked official total; this also makes
            # readers compatible during a staged collector/API deployment.
            price = PricePublic(source="official_conditions", unit_type=entry["unit_type"], price_kind="sale_total",
                                amount_krw=amount, verification="official", area_sqm=entry.get("exclusive_area_sqm"),
                                evidence_url=entry.get("evidence_url"), evidence_text=entry.get("evidence_text"),
                                document_hash=entry.get("document_hash"), basis_label=entry.get("basis_label") or "동·호별 총분양가")
            result.append(price)
        for field in ("exclusive_area_sqm", "supply_area_sqm", "dwelling_identity", "unit_type_code", "building", "room"):
            setattr(price, field, entry.get(field))
        if price.exclusive_area_sqm is not None:
            price.area_basis = "exclusive"
        price.evidence_page = entry.get("evidence_page")
        price.payment_components = [c for c in components if c is not None]
    costs, cost_keys = [], set()
    for rule in accepted:
        if rule.get("kind") != "additional_costs":
            continue
        for entry in rule.get("entries", []):
            if not isinstance(entry, dict):
                continue
            cost = _cost(entry, rule)
            if cost is None:
                continue
            key = json.dumps(cost.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
            if key not in cost_keys:
                cost_keys.add(key)
                costs.append(cost)
    return result, costs
