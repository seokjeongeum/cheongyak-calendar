"""Applicant regions read from an actual eligibility sentence, not a site address."""
from __future__ import annotations

import re

from .reviewed_sources import reviewed_source_for_document


def normalize_region_text(text: str) -> str:
    # PDF line wraps can split a municipality or a fixed legal term. Only
    # these reviewed words are joined; arbitrary Korean whitespace is kept.
    text = re.sub(r"화\s*성\s*(?:특\s*례\s*시|시)", "화성시", text)
    text = re.sub(r"우선공\s*급", "우선공급", text)
    return re.sub(r"\s+", " ", text).strip()


def reviewed_applicant_regions(pages, *, url, digest, cutoff, make):
    """A current hash-bound paragraph can resolve a layout-split region list.

    This review does not certify the rest of the document or its supply table.
    A changed PDF must be read afresh instead of inheriting these boundaries.
    """
    source = reviewed_source_for_document(url, digest)
    review = source.get("applicant_region_review") if source else None
    if not review or cutoff != source.get("announcement_date"):
        return []
    page = next((p for p in pages if p["page"] == review["page"]), None)
    if not page:
        return []
    text = normalize_region_text(page["text"])
    anchor = re.search(r"(?:최초\s*)?입주자모집공고일\s*현재[^■▌]{0,1200}", text)
    if not anchor:
        return []
    quote = anchor.group(0).strip()
    fields = {"regions": review["regions"], "scope_complete": True,
              "priority_applicable": review["priority_applicable"],
              "local_priority": {**review["local_priority"], "criterion_date": cutoff}}
    military = review.get("military_exception")
    military_reviews = ([military] if military else []) + review.get("additional_military_exceptions", [])
    for military in military_reviews:
        military_page = next((p for p in pages if p["page"] == military["page"]), None)
        # This exact reviewed Hanyang page draws '(1순위, 2순위)' between
        # '10' and '년' in the content stream. The hash review fixes the value;
        # the bounded anchor retains the actual source text for the reader.
        quotes = list(re.finditer(str(military["min_years"]) + r"[^■▌]{0,80}?년\s*이상[^■▌]{0,700}", normalize_region_text(military_page["text"]))) if military_page else []
        if military.get("recommendation_required"):
            # The earlier 25-year phrase concerns submission method only; this
            # exception is the later recommendation-dependent local waiver.
            quotes = [match for match in quotes if all(term in re.sub(r"\s+", "", match.group(0))
                       for term in ("국방부", "추천", "해당지역거주자격"))]
        military_quote = quotes[0] if quotes else None
        if not military_quote:
            return []
        fields.setdefault("exceptions", []).append(make("military_service_years", effect="metadata", require_as_of_date=True,
            min_years=military["min_years"], currently_serving=military["currently_serving"],
            residence_area=military["residence_area"],
            **({"recommendation_required": True, "recommendation_authority": military["recommendation_authority"]} if military.get("recommendation_required") else {}),
            quote=military_quote.group(0), page=military["page"]))
    if review.get("source_regions"):
        # Both former provinces are explicitly included in this clause, so
        # their full union is the current merged province. A single former
        # province would not establish this broader scope.
        if cutoff < "2026-07-01" or not all(name in quote for name in ("광주광역시", "전라남도")):
            return []
        fields["source_regions"] = review["source_regions"]
        fields["region_mapping_basis"] = "explicit_union_of_former_provinces"
    mapping_page = review["local_priority"].get("mapping_page")
    if mapping_page:
        mapping = next((p for p in pages if p["page"] == mapping_page), None)
        if not mapping:
            return []
        mapping_text = normalize_region_text(mapping["text"])
        names = [item["region_name"].split()[-1] for item in review["local_priority"].get("regions", [])]
        if not names or not all(name in mapping_text for name in names) or "기존 광주광역시" not in mapping_text:
            return []
        start = max(0, mapping_text.find("전남광주통합특별시 북구") - 40)
        fields["local_priority"]["mapping_evidence"] = {
            "evidence_page": mapping_page, "evidence_url": url, "document_hash": digest,
            "evidence_text": mapping_text[start:start + 500],
        }
    return [make("applicant_regions", effect="metadata", quote=quote, page=page["page"], **fields)]


def explicit_applicant_regions(pages, *, cutoff, make, provinces, method=None):
    result = []
    for page in pages:
        text = normalize_region_text(page["text"])
        date_label = r"(?:분양|모집)광고일" if method == "officetel" else r"(?:최초\s*)?(?:입주자\s*모집공고일|분양광고일)"
        pattern = (date_label +
                   r"(?:\s*\([^)]{0,30}\))?\s*현재\s*[^■Ÿ•]{0,700}?(?:청약이\s*가능|신청\s*가능|신청할\s*수|신청자격|무주택\s*세대(?:구성원|주))[^■Ÿ•]{0,180}")
        for match in re.finditer(pattern, text):
            quote = match.group(0)
            dated = re.search(r"\(\s*(20\d{2})[.년/-]\s*(\d{1,2})[.월/-]\s*(\d{1,2})", quote)
            if dated and "-".join((dated[1], dated[2].zfill(2), dated[3].zfill(2))) != cutoff:
                continue
            fields = {"scope_complete": True, "priority_applicable": False}
            if re.search(r"(?:대한민국|국내|전국)(?:\([^)]*\))?에?\s*거주", quote):
                fields.update(unrestricted=True, domestic_only=True)
            else:
                grouped = re.search(r"수도권\s*[\[(]([^\])]+)[\])](?:에|에서)?\s*거주", quote)
                names = [name for name in provinces if name in grouped[1]] if grouped else [
                    name for name in provinces if re.search(re.escape(name) + r"(?:에|에서)?\s*거주", quote)]
                if grouped and set(names) != {"경기도", "서울특별시", "인천광역시"}:
                    continue
                if not grouped and set(names) != {name for name in provinces if name in quote}:
                    # A comma-separated list can put the single '거주' after
                    # its last province. Reading only that last province would
                    # falsely narrow the complete applicant scope.
                    continue
                if not names:
                    continue
                fields["regions"] = [{"region_code": provinces[name], "region_name": name} for name in names]
                priority = re.search(r"(?:해당\s*주택건설지역인\s*)?화성시\s*거주자가?\s*우선", quote)
                if priority:
                    fields.update(priority_applicable=True, local_priority={"region_code": "41590", "region_name": "경기도 화성시", "min_months": 0, "criterion_date": cutoff})
            result.append(make("applicant_regions", effect="metadata", quote=quote, page=page["page"], **fields))
    # Multiple copies of the same scope do not become competing rules.
    unique = {}
    for rule in result:
        key = (str(rule.get("regions")), rule.get("unrestricted"), str(rule.get("local_priority")))
        unique.setdefault(key, rule)
    return list(unique.values())
