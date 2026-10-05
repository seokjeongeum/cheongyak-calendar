"""Official classification metadata, separate from eligibility requirements.

The existing JSON rules column holds this metadata so old databases need no
schema migration. A source's housing label is never inferred from its provider.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.schemas import ApplicationMethodEvidencePublic, ContractSchedulePublic, HousingKindEvidencePublic, OfferedSupplyPublic, QualificationContextPublic, RankApplicabilityPublic


CONTEXT_FLAGS = ("public_housing", "speculation_zone", "subscription_overheated", "weakened_area", "capital_region")
METADATA_KINDS = {"housing_classification", "qualification_context", "rank_applicability", "rank_requirements", "application_method", "contract_schedule", "selection_method", "winning_scores", "applicant_regions", "regional_allocation", "supply_financial_terms", "unit_exclusive_areas", "offered_supplies", "condition_coverage", "document_diagnostics"}
APPLICATION_METHODS = {"apt_ranked", "unranked_after", "optional_supply", "cancelled_resupply", "first_come", "officetel"}


def public_contract_schedule(rules: list[dict[str, Any]], *, contract_events: list[dict] | None = None) -> ContractSchedulePublic:
    """Project verified schedules; event callers supply only official contracts."""
    candidates = [r for r in rules if r.get("kind") == "contract_schedule" and r.get("verification") == "official"]
    documents = [r for r in candidates if r.get("document_hash")]
    candidates = documents or candidates
    valid = []
    for row in candidates:
        status = row.get("status")
        try:
            start = date.fromisoformat(str(row["start_date"])[:10]) if row.get("start_date") else None
            end = date.fromisoformat(str(row["end_date"])[:10]) if row.get("end_date") else None
        except ValueError:
            continue
        if status not in {"fixed", "range", "ongoing", "unknown"}:
            continue
        if status in {"fixed", "range", "ongoing"} and (start is None or (status != "ongoing" and (end is None or end < start))):
            continue
        valid.append({**row, "start_date": start, "end_date": end})
    identities = {(r["status"], r["start_date"], r["end_date"]) for r in valid}
    if valid:
        if len(identities) != 1:
            return ContractSchedulePublic(evidence_text="공식 출처의 계약 일정이 서로 달라 추가 확인이 필요합니다.")
        return ContractSchedulePublic(**{k: valid[0].get(k) for k in ContractSchedulePublic.model_fields})
    if candidates:
        return ContractSchedulePublic(evidence_text="공식 계약 일정의 날짜 형식을 확인하지 못했습니다.")
    events = contract_events or []
    identities = {(row.get("start_date"), row.get("end_date") or row.get("start_date")) for row in events}
    if len(identities) != 1:
        return ContractSchedulePublic()
    start, end = next(iter(identities))
    row = events[0]
    return ContractSchedulePublic(status="fixed" if start == end else "range", start_date=start, end_date=end,
        verification="official", source=row.get("source"), evidence_url=row.get("evidence_url"),
        evidence_text=row.get("evidence_text") or "공식 API가 제공한 계약 일정")


def is_metadata(rule: dict[str, Any]) -> bool:
    # Recognize the reserved kinds even when a legacy producer omitted effect.
    return rule.get("effect") == "metadata" or rule.get("kind") in METADATA_KINDS


def requirements_complete(rules: list[dict[str, Any]], declared: bool) -> bool:
    """Classification alone and unverified nested conditions cannot certify a notice."""
    requirements = [rule for rule in rules if not is_metadata(rule)]

    def verified(rule: dict[str, Any]) -> bool:
        if rule.get("verification") != "official":
            return False
        # These are the branch forms accepted by the browser evaluator. Empty
        # groups are not evidence of eligibility, and no inherited verification
        # can accidentally promote an AI-derived child condition.
        if rule.get("kind") in {"all", "any", "not", "condition_group"}:
            children = rule.get("conditions")
            if not isinstance(children, list) or not children:
                return False
            return all(isinstance(child, dict) and not is_metadata(child) and verified(child) for child in children)
        return True

    coverage = [rule for rule in rules if rule.get("kind") == "condition_coverage" and rule.get("verification") == "official"]
    if coverage:
        scopes = [scope for item in coverage for scope in item.get("scopes", [])]
        declared = bool(scopes and all(scope.get("complete") is True and all(
            not topic.get("required", True) or topic.get("status") in {"verified", "not_applicable"}
            for topic in scope.get("topics", [])
        ) for scope in scopes))
    return bool(declared and requirements and all(verified(rule) for rule in requirements))


def public_offered_supplies(rules: list[dict[str, Any]]) -> list[OfferedSupplyPublic] | None:
    """An absent inventory differs from an official inventory with zero rows."""
    candidates = [rule for rule in rules if rule.get("kind") == "offered_supplies" and rule.get("verification") == "official"
                  and isinstance(rule.get("supplies"), list)]
    documents = [rule for rule in candidates if rule.get("document_hash")]
    candidates = documents or candidates
    if not candidates:
        return None
    unique = {}
    for candidate in candidates:
        for row in candidate["supplies"]:
            if not isinstance(row, dict) or (row.get("supply_count") is not None and (not isinstance(row.get("supply_count"), int) or row["supply_count"] <= 0)):
                continue
            fields = {key: row.get(key, candidate.get(key)) for key in OfferedSupplyPublic.model_fields}
            if fields.get("verification") != "official" or not fields.get("supply_type"):
                continue
            identity = (fields["supply_type"], fields.get("unit_type"))
            unique.setdefault(identity, OfferedSupplyPublic(**fields))
    return list(unique.values())


def merge_poll_rules(previous: list[dict[str, Any]], incoming: list[dict[str, Any]], *, metadata_only: bool) -> list[dict[str, Any]]:
    """Refresh metadata without deleting previously verified/document conditions."""
    incoming_metadata = {rule.get("kind") for rule in incoming if is_metadata(rule)}
    replaced_document_metadata = {rule.get("kind") for rule in incoming if is_metadata(rule) and rule.get("source") == "official_document_parser"}
    previous_metadata = []
    for rule in previous:
        if not is_metadata(rule):
            continue
        preserve_document = bool(metadata_only and rule.get("source") == "official_document_parser" and
                                 rule.get("verification") == "official" and rule.get("document_hash") and
                                 rule.get("kind") not in replaced_document_metadata)
        if rule.get("kind") not in incoming_metadata or preserve_document:
            retained = rule
            if preserve_document and rule.get("kind") == "qualification_context" and "qualification_context" in incoming_metadata:
                # Source flags are refreshed by this poll. Keep only the
                # independently reviewed document's cutoffs/public-housing
                # fact, not a copied snapshot of obsolete API flags. The
                # caller already retires parser data on URL/hash replacement.
                protected = {key: value for key, value in (rule.get("value") or {}).items()
                             if key in {"original_announcement_date", "application_announcement_date", "application_criterion_date", "application_criterion_basis", "rule_effective_date"}
                             or (key == "public_housing" and value is True)}
                retained = {**rule, "value": protected}
            previous_metadata.append(retained)
    result = [*previous_metadata, *incoming]
    if metadata_only:
        result = [rule for rule in previous if not is_metadata(rule)] + result

    # A later corrected announcement must not restart a residence/account
    # qualification clock. Preserve the original date as metadata only.
    original_dates = []
    for rule in [*previous, *incoming]:
        if rule.get("kind") == "qualification_context":
            raw = (rule.get("value") or {}).get("original_announcement_date")
            if raw:
                try:
                    original_dates.append(date.fromisoformat(str(raw)[:10]).isoformat())
                except ValueError:
                    pass
    if original_dates:
        for rule in result:
            if rule.get("kind") == "qualification_context":
                rule["value"] = {**(rule.get("value") or {}), "original_announcement_date": min(original_dates)}
    return result


def public_classification(rules: list[dict[str, Any]]) -> tuple[str, HousingKindEvidencePublic | None, QualificationContextPublic]:
    classifications = [rule for rule in rules if rule.get("kind") == "housing_classification" and is_metadata(rule)]
    official = [rule for rule in classifications if rule.get("verification") == "official" and rule.get("housing_kind") in {"private", "national", "not_applicable"}]
    values = {rule["housing_kind"] for rule in official}
    evidence = None
    housing_kind = "unknown"
    if len(values) == 1:
        housing_kind = next(iter(values))
        evidence = HousingKindEvidencePublic(**{field: official[0].get(field) for field in HousingKindEvidencePublic.model_fields})
    elif len(values) > 1:
        evidence = HousingKindEvidencePublic(verification="unknown", evidence_text="공식 출처의 민영·국민주택 구분이 서로 달라 추가 확인이 필요합니다.")
    elif classifications:
        raw = classifications[0]
        evidence = HousingKindEvidencePublic(**{**{field: raw.get(field) for field in HousingKindEvidencePublic.model_fields}, "verification": "unknown"})

    contexts = [rule.get("value") for rule in rules if rule.get("kind") == "qualification_context" and is_metadata(rule) and rule.get("verification") == "official" and isinstance(rule.get("value"), dict)]
    merged: dict[str, Any] = {}
    for field in CONTEXT_FLAGS:
        values = {context[field] for context in contexts if isinstance(context.get(field), bool)}
        merged[field] = next(iter(values)) if len(values) == 1 else None
    dates = set()
    for context in contexts:
        raw = context.get("rule_effective_date")
        if raw:
            try:
                dates.add(date.fromisoformat(str(raw)[:10]))
            except ValueError:
                pass
    merged["rule_effective_date"] = next(iter(dates)) if len(dates) == 1 else None
    original_dates = []
    for context in contexts:
        raw = context.get("original_announcement_date")
        if raw:
            try:
                original_dates.append(date.fromisoformat(str(raw)[:10]))
            except ValueError:
                pass
    merged["original_announcement_date"] = min(original_dates) if original_dates else None
    for field in ("application_announcement_date", "application_criterion_date"):
        values = set()
        for context in contexts:
            raw = context.get(field)
            try:
                if raw: values.add(date.fromisoformat(str(raw)[:10]))
            except ValueError:
                pass
        merged[field] = next(iter(values)) if len(values) == 1 else None
    bases = {context["application_criterion_basis"] for context in contexts
             if context.get("application_criterion_basis") in {"announcement", "contract_date", "application_date"}}
    merged["application_criterion_basis"] = next(iter(bases)) if len(bases) == 1 else None
    return housing_kind, evidence, QualificationContextPublic(**merged)


def public_rank_applicability(rules: list[dict[str, Any]]) -> RankApplicabilityPublic:
    candidates = [r for r in rules if r.get("kind") == "rank_applicability" and is_metadata(r) and r.get("verification") == "official"]
    # A reviewed current document is more specific than an API operation's
    # general grouping (e.g. ordinary APT versus 신혼희망타운).
    document = [r for r in candidates if r.get("document_hash")]
    candidates = document or candidates
    statuses = {r.get("status") for r in candidates if r.get("status") in {"applicable", "not_applicable"}}
    if len(statuses) != 1:
        return RankApplicabilityPublic()
    chosen = candidates[0]
    return RankApplicabilityPublic(**{key: chosen.get(key) for key in RankApplicabilityPublic.model_fields if key in chosen})


def public_application_method(rules: list[dict[str, Any]]) -> tuple[str, ApplicationMethodEvidencePublic | None]:
    candidates = [r for r in rules if r.get("kind") == "application_method" and is_metadata(r) and r.get("verification") == "official" and r.get("value") in APPLICATION_METHODS]
    documents = [r for r in candidates if r.get("document_hash")]
    candidates = documents or candidates
    values = {r["value"] for r in candidates}
    if len(values) != 1:
        return "unknown", None
    chosen = candidates[0]
    return chosen["value"], ApplicationMethodEvidencePublic(**{key: chosen.get(key) for key in ApplicationMethodEvidencePublic.model_fields if key in chosen})


def public_selection_methods(rules: list[dict]) -> list[dict]:
    return [r for r in rules if r.get('kind') in {'selection_method', 'regional_allocation'} and r.get('verification') == 'official' and is_metadata(r)]


def public_winning_scores(rules: list[dict]) -> list[dict]:
    return [row for r in rules if r.get('kind') == 'winning_scores' and r.get('verification') == 'official' for row in r.get('rows', []) if isinstance(row, dict) and row.get('verification') == 'official']
