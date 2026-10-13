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
    # LH's current detail specifies the administratively published closing
    # date while an attached first-come PDF may say "until further notice".
    # Prefer only that explicit official detail field, never a posting expiry.
    detail = [r for r in candidates if r.get("source") == "lh_official_detail" and r.get("status") in {"fixed", "range"}
              and r.get("evidence_location") == "#sta_ctrtDt" and r.get("source_hash")]
    documents = [r for r in candidates if r.get("document_hash")]
    candidates = detail or documents or candidates
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


def _review_basis_supported(scope: dict[str, Any]) -> bool:
    if scope.get("review_version") == "generic-admission-2026-10-12-public-v1":
        return scope.get("completion_basis") == "current_document_clause_coverage"
    if scope.get("completion_basis") == "document_structure_reviewed_standard_branch":
        return True
    return False


def _public_review_references(scope: dict[str, Any]) -> set[str] | None:
    references = set()
    for topic in scope.get("topics", []):
        if topic.get("required", True) and topic.get("status") == "verified":
            ids = topic.get("rule_ids")
            if not isinstance(ids, list) or not ids or any(not isinstance(value, str) or not value for value in ids):
                return None
            references.update(ids)
    for branch in scope.get("branches", []):
        if branch.get("required", True) and "rule_ids" in branch:
            ids = branch["rule_ids"]
            if not isinstance(ids, list) or not ids or any(not isinstance(value, str) or not value for value in ids):
                return None
            references.update(ids)
    return references


def _public_scope_bound(scope: dict[str, Any], metadata: dict[str, Any], rules: list[dict[str, Any]]) -> bool:
    if scope.get("review_version") != "generic-admission-2026-10-12-public-v1":
        return True
    digest = metadata.get("document_hash")
    references = _public_review_references(scope)
    actual = {rule.get("id") for rule in rules if rule.get("verification") == "official"
              and rule.get("document_hash") == digest and not is_metadata(rule)
              and rule.get("effect") not in {"priority", "instruction", "procedure"}
              and rule.get("purpose") not in {"first_rank", "second_rank", "selection"}}
    return bool(digest and scope.get("reviewed_document_hash") == digest and references and references <= actual)


def coverage_scope_complete(scope: Any) -> bool:
    """Validate completion flags without ignoring malformed source metadata."""
    if not isinstance(scope, dict) or scope.get("complete") is not True:
        return False
    for single, plural in (("supply_type", "supply_types"), ("unit_type", "unit_types")):
        if scope.get(single) is not None and not isinstance(scope[single], str):
            return False
        if scope.get(plural) is not None and (not isinstance(scope[plural], list) or
                                            any(not isinstance(value, str) or not value for value in scope[plural])):
            return False
    topics = scope.get("topics", [])
    if not isinstance(topics, list) or any(not isinstance(topic, dict) for topic in topics):
        return False
    if any(type(topic.get("required", True)) is not bool or
           topic.get("required", True) and topic.get("status") not in {"verified", "not_applicable"}
           for topic in topics):
        return False
    missing = scope.get("missing_topics", [])
    if not isinstance(missing, list) or missing:
        return False
    version = scope.get("review_version")
    if version is not None and not isinstance(version, str):
        return False
    if (scope.get("completion_basis") == "current_document_clause_coverage"
            and version != "generic-admission-2026-10-12-public-v1"):
        return False
    if isinstance(version, str) and version.startswith("generic-admission-"):
        pages = scope.get("reviewed_pages")
        count = scope.get("verified_rule_count")
        if version == "generic-admission-2026-10-12-public-v1":
            branches = scope.get("branches")
            if (not isinstance(scope.get("reviewed_document_hash"), str) or not scope["reviewed_document_hash"]
                    or scope.get("source_gaps") != [] or not isinstance(branches, list) or not branches
                    or any(not isinstance(branch, dict) or type(branch.get("required", True)) is not bool
                           or branch.get("required", True) and branch.get("status") != "verified"
                           for branch in branches)):
                return False
            references = _public_review_references(scope)
            if not references or len(references) != count:
                return False
        return bool(_review_basis_supported(scope)
                    and isinstance(pages, list) and pages
                    and all(type(page) is int and page > 0 for page in pages)
                    and type(count) is int and count > 0
                    and "missing_topics" in scope)
    return True


def generic_admission_coverage_complete(rule: dict[str, Any]) -> bool:
    """Only a complete source review of every offered branch replaces all facts."""
    scopes, offered = rule.get("scopes"), rule.get("offered_supply_types")
    if (rule.get("kind") != "condition_coverage" or rule.get("status") != "complete"
            or rule.get("source") != "official_document_parser" or rule.get("verification") != "official"
            or not isinstance(rule.get("document_hash"), str) or not rule["document_hash"]
            or not isinstance(rule.get("evidence_url"), str) or not rule["evidence_url"].strip()
            or not isinstance(scopes, list) or not scopes
            or not isinstance(offered, list) or not offered
            or any(not isinstance(supply, str) or not supply for supply in offered)):
        return False
    if not all(coverage_scope_complete(scope)
               and isinstance(scope.get("review_version"), str)
               and scope["review_version"].startswith("generic-admission-")
               and (scope.get("review_version") != "generic-admission-2026-10-12-public-v1"
                    or scope.get("reviewed_document_hash") == rule["document_hash"])
               and isinstance(scope.get("supply_type"), str)
               and not scope.get("unit_type") and not scope.get("unit_types")
               for scope in scopes):
        return False
    return set(offered) == {scope["supply_type"] for scope in scopes}


def retire_reviewed_document_candidates(rules: list[dict[str, Any]], *, digest: str,
                                        parser_version: str) -> list[dict[str, Any]]:
    """A whole-source review supersedes uncertain interpretations of those bytes.

    This retires only derived condition candidates. Source metadata and every
    candidate from another or unidentified document remain available, as do
    partial reviews. Prices and source history are outside this rule operation.
    """
    if not isinstance(digest, str) or not digest.strip() or not parser_version:
        return rules
    def superseded_candidate(rule):
        return (rule.get("verification") in {"ai_unverified", "auto_unverified"}
                and rule.get("document_hash") == digest and not is_metadata(rule))
    if not any(superseded_candidate(rule) for rule in rules):
        return rules
    reviewed = [rule for rule in rules if rule.get("source") == "official_document_parser"
                and rule.get("verification") == "official" and rule.get("document_hash") == digest
                and rule.get("parser_version") == parser_version]
    has_admission = any(not is_metadata(rule) and rule.get("kind") != "unparsed"
                        and rule.get("effect") not in {"priority", "procedure", "instruction"}
                        and rule.get("purpose") not in {"first_rank", "second_rank", "selection"}
                        for rule in reviewed)
    complete_review = any(generic_admission_coverage_complete(rule)
                         and all(scope.get("reviewed_document_hash") == digest for scope in rule["scopes"])
                         for rule in reviewed)
    if (not has_admission or not complete_review
            or not requirements_complete(reviewed, False)):
        return rules
    return [rule for rule in rules if not superseded_candidate(rule)]


def source_bound_waivers(rule: dict[str, Any], *, digest: str, parser_version: str) -> list[tuple[str, dict[str, Any]]]:
    """Explicit source exemptions can replace one fact in an otherwise partial review."""
    if (rule.get("kind") != "condition_coverage" or rule.get("source") != "official_document_parser"
            or rule.get("verification") != "official" or rule.get("document_hash") != digest
            or rule.get("parser_version") != parser_version
            or rule.get("status") in {"unreadable", "unsupported", "error"}
            or not isinstance(rule.get("evidence_url"), str) or not rule["evidence_url"].strip()
            or not isinstance(rule.get("scopes"), list)):
        return []
    waivers = []
    for scope in rule["scopes"]:
        if (not isinstance(scope, dict) or not isinstance(scope.get("review_version"), str)
                or not scope["review_version"].startswith("generic-admission-")
                or not isinstance(scope.get("supply_type"), str) or not scope["supply_type"]
                or not _review_basis_supported(scope)
                or not isinstance(scope.get("reviewed_pages"), list) or not scope["reviewed_pages"]
                or not all(type(page) is int and page > 0 for page in scope["reviewed_pages"])
                or not isinstance(scope.get("topics"), list)):
            continue
        for topic in scope["topics"]:
            if (not isinstance(topic, dict) or topic.get("status") != "not_applicable"
                    or topic.get("required") is not False
                    or not isinstance(topic.get("waived_rule_kind"), str) or not topic["waived_rule_kind"]
                    or type(topic.get("evidence_page")) is not int or topic["evidence_page"] not in scope["reviewed_pages"]
                    or not isinstance(topic.get("evidence_text"), str) or not topic["evidence_text"].strip()):
                continue
            waivers.append((topic["waived_rule_kind"], {**scope, **topic}))
    return waivers


def source_bound_superseded_kinds(rule: dict[str, Any], *, digest: str, parser_version: str) -> list[str]:
    """A source-reviewed model can explicitly replace an older condition kind."""
    kinds = rule.get("supersedes_rule_kinds")
    if (rule.get("source") != "official_document_parser" or rule.get("verification") != "official"
            or rule.get("document_hash") != digest or rule.get("parser_version") != parser_version
            or is_metadata(rule) or rule.get("kind") == "unparsed"
            or rule.get("status") in {"partial", "unreadable", "unsupported", "error"}
            or not isinstance(kinds, list) or not kinds or any(not isinstance(kind, str) or not kind for kind in kinds)
            or type(rule.get("evidence_page")) is not int or rule["evidence_page"] <= 0
            or not isinstance(rule.get("evidence_url"), str) or not rule["evidence_url"].strip()
            or not isinstance(rule.get("evidence_text"), str) or not rule["evidence_text"].strip()):
        return []
    return kinds


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
        declared = all(isinstance(item.get("scopes"), list) and item["scopes"]
                       and all(coverage_scope_complete(scope)
                               and _public_scope_bound(scope, item, rules)
                               for scope in item["scopes"])
                       for item in coverage)
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
