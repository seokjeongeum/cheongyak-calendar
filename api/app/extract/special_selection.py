"""Special-supply selection facts from each actual qualification section.

Income stage percentages are not regional quotas, and a province quota is not
the share reserved for its host municipality. Only explicit wording is read.
"""
from __future__ import annotations

import re

from .supply_inventory import canonical_unit


def special_selection_rules(sections, *, inventory, rules, make):
    from .official_rules import PROVINCES

    result = []
    base_regions = next((r for r in rules if r.get("kind") == "applicant_regions"
                         and r.get("verification") == "official" and not r.get("supply_type")), None)
    for section in sections:
        supply = section["supply_type"]
        if supply == "일반공급":
            continue
        units = sorted({canonical_unit(row["unit_type"]) for row in inventory
                        if row.get("supply_type") == supply and row.get("unit_type")
                        and (row.get("supply_count") or 0) > 0})
        if not units:
            continue
        page_texts = {}
        for line in section["lines"]:
            page_texts.setdefault(line["page"], []).append(line["text"])
        page_texts = {page: re.sub(r"\s+", " ", " ".join(lines)) for page, lines in page_texts.items()}
        order_fields = {}
        for line in section["lines"]:
            order = re.search(r"당첨자\s*선정\s*순서\s*[:：]\s*([^■※]{0,300})", line["text"])
            if order:
                steps = [re.sub(r"^[①②③④⑤⑥⑦⑧⑨]\s*", "", part.strip()).strip()
                         for part in re.split(r"→|⇒|->", order[1].strip())]
                if len(steps) > 1 and all(steps):
                    order_fields = {"selection_order": steps, "selection_order_evidence_page": line["page"],
                                    "selection_order_evidence_text": order.group(0).strip()}
                    break
        for page, text in page_texts.items():
            lottery_exception = re.search(r"(\d+)단계에서\s*경쟁이\s*있는\s*경우\s*순위와\s*관계없이\s*해당지역\s*거주자\s*\([^)]*\)에게\s*우선공급하고,\s*경쟁이\s*있는\s*경우\s*추첨으로\s*선정", text)
            if lottery_exception:
                order_fields["selection_stage_exceptions"] = [{
                    "stage_number": int(lottery_exception[1]), "selection_order": ["지역", "추첨"],
                    "rank_applies": False, "evidence_page": page, "evidence_text": lottery_exception.group(0),
                }]
            advance = re.search(r"각\s*단계별\s*낙첨자는\s*다음\s*단계\s*공급대상에\s*포함됨", text)
            if advance:
                order_fields.update(income_stage_unsuccessful_applicants_advance=True,
                                    income_stage_carry_forward_evidence_page=page,
                                    income_stage_carry_forward_evidence_text=advance.group(0))

        if supply == "기관추천 특별공급":
            for page, text in page_texts.items():
                recommendation = re.search(r"(?:관계|해당)기관의\s*장이\s*정하는\s*우선순위에\s*따라\s*공급[^■]{0,220}", text)
                eligible = re.search(r"기관추천\s*특별공급\s*확정대상자\s*및\s*예비대상자[^■]{0,260}?신청가능[^■]{0,200}", text)
                if recommendation and eligible:
                    result.append(make("regional_allocation", page, recommendation.group(0).strip(),
                        supply_type=supply, unit_types=units, allocation_method="institution_recommendation",
                        local_share_percent=None, selection_order=["추천기관의 우선순위"],
                        recommendation_evidence_page=page, recommendation_evidence_text=eligible.group(0).strip()))
                    break
            continue

        for page, text in page_texts.items():
            # A numbered geographic stage may be ①, ②, or ③ depending on
            # whether income and supply-specific rank come before geography.
            region = re.search(r"[①②③④⑤]\s*지역\s*[:：]\s*해당지역\s*거주자\s*\(([^)]*)\)\s*(?:→|⇒|->)\s*기타지역\s*거주자\s*\([^)]*\)", text)
            if region:
                local_name = re.sub(r"\s*거주자\s*$", "", region[1]).strip()
                local = (base_regions or {}).get("local_priority")
                local_region = local if isinstance(local, dict) and local_name in str(local.get("region_name", "")) else {"region_name": local_name}
                result.append(make("regional_allocation", page, region.group(0), supply_type=supply,
                    unit_types=units, allocation_method="region_priority", local_share_percent=None,
                    local_region=local_region, **order_fields))
                break
            if supply != "다자녀가구 특별공급":
                continue
            quota = re.search(r"[①②③④⑤]\s*지역\s*[:：]\s*해당시\s*[·ㆍ.]\s*도\s*거주자\s*(\d{1,3})\s*%\s*\(([^)]*)\)\s*(?:→|⇒|->)\s*기타지역\s*거주자\s*(\d{1,3})\s*%\s*\(([^)]*)\)", text)
            if not quota or int(quota[1]) + int(quota[3]) != 100 or max(int(quota[1]), int(quota[3])) > 100:
                continue
            first_names = [name for name in PROVINCES if name in quota[2]]
            second_names = [name for name in PROVINCES if name in quota[4]]
            # The supported 수도권 table explicitly includes all of 경기도,
            # not merely a municipality whose label begins with 경기도.
            if first_names != ["경기도"] or set(second_names) != {"서울특별시", "인천광역시"} or not re.search(r"(?:및\s*)경기도\s*거주자", quota[2]):
                continue
            first_priority = re.search(r"경쟁이\s*있는\s*경우\s*([^()]{1,35}?)\s*거주자\s*우선", text)
            advance = re.search(r"경기도\s*거주자가\s*50%\s*우선공급에서\s*낙첨될\s*경우[^■]{0,650}?다시\s*경쟁[^■]{0,200}?우선공급\s*요건은\s*적용되지\s*않습니다", text)
            fields = {
                "regional_shares": [
                    {"residence_area": "local_and_other_gyeonggi", "percent": int(quota[1]),
                     "label": re.sub(r"\s*거주자\s*$", "", quota[2]).strip(), "region_codes": ["41"]},
                    {"residence_area": "other", "percent": int(quota[3]),
                     "label": re.sub(r"\s*거주자\s*$", "", quota[4]).strip(), "region_codes": ["11", "28"]},
                ],
                **order_fields,
            }
            if first_priority:
                local_name = first_priority[1].strip()
                local = (base_regions or {}).get("local_priority")
                fields.update(local_priority_within_first_quota=True,
                              local_region=local if isinstance(local, dict) and local_name in str(local.get("region_name", "")) else {"region_name": local_name},
                              first_quota_priority_evidence_text=first_priority.group(0),
                              first_quota_priority_evidence_page=page)
            if advance:
                fields.update(unsuccessful_applicants_advance=True, local_priority_in_remaining_quota=False,
                              remaining_quota_evidence_text=advance.group(0), remaining_quota_evidence_page=page)
            quote = quota.group(0) + (" " + advance.group(0) if advance else "")
            result.append(make("regional_allocation", page, quote, supply_type=supply, unit_types=units,
                allocation_method="regional_quota", local_share_percent=None, **fields))
            # Preserve independently verified admission facts while adding the
            # province bucket that this particular special quota requires.
            if base_regions and first_priority and isinstance(base_regions.get("local_priority"), dict):
                local = base_regions["local_priority"]
                if first_priority[1].strip() in str(local.get("region_name", "")):
                    region_fields = {key: base_regions[key] for key in (
                        "regions", "scope_complete", "local_priority", "priority_applicable", "exceptions")
                        if key in base_regions}
                    result.append(make("applicant_regions", page, quota.group(0), supply_type=supply,
                        unit_types=units, other_gyeonggi={"region_code": "41", "region_name": "경기도"},
                        **region_fields))
            break
    return result
