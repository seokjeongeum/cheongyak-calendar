"""Applicant regions read from an actual eligibility sentence, not a site address."""
from __future__ import annotations

import re


def normalize_region_text(text: str) -> str:
    # PDF line wraps can split a municipality or a fixed legal term. Only
    # these reviewed words are joined; arbitrary Korean whitespace is kept.
    text = re.sub(r"화\s*성\s*(?:특\s*례\s*시|시)", "화성시", text)
    text = re.sub(r"우선공\s*급", "우선공급", text)
    return re.sub(r"\s+", " ", text).strip()


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
