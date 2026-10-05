"""Explicit general-supply allocation tables; no region/area legal-rate guesses."""
from __future__ import annotations

import hashlib
import re
from .supply_inventory import canonical_unit


def parse_selection_rules(pages: list[dict], *, url: str, digest: str, rules: list[dict], parser_version: str) -> list[dict]:
    rank_applies = not any(r.get("kind") == "rank_applicability" and r.get("status") == "not_applicable" for r in rules)
    kinds = {r["housing_kind"] for r in rules if r.get("housing_kind") in {"private", "national", "not_applicable"}
             and r.get("verification") == "official"}
    housing_kind = next(iter(kinds)) if len(kinds) == 1 else "unknown"
    private = rank_applies and housing_kind == "private"
    cutoff = next((r.get("criterion_date") for r in rules if r.get("criterion_date")), None)
    all_inventory = [s for r in rules if r.get("kind") == "offered_supplies" and r.get("verification") == "official" for s in r.get("supplies", []) if s.get("supply_count") is None or s["supply_count"] > 0]
    inventory = [s for s in all_inventory if s.get("supply_type") == "일반공급" and (s.get("supply_count") or 0) > 0]
    area_sets = {}
    for rule in rules:
        if rule.get("kind") != "unit_exclusive_areas" or rule.get("verification") != "official":
            continue
        for unit in rule.get("units", []):
            if isinstance(unit.get("exclusive_area_sqm"), (int, float)):
                area_sets.setdefault(canonical_unit(unit.get("unit_type")), set()).add(unit["exclusive_area_sqm"])
    areas = {unit: next(iter(values)) for unit, values in area_sets.items() if len(values) == 1}
    if not cutoff or not all_inventory:
        return []
    result = []

    def make(kind, page, quote, **fields):
        identity = f"{digest}:{kind}:{page}:{fields}:{quote}"
        return {"id": hashlib.sha256(identity.encode()).hexdigest()[:16], "kind": kind, "effect": "metadata", "supply_type": "일반공급", "verification": "official", "source": "official_document_parser", "document_hash": digest, "parser_version": parser_version, "criterion_date": cutoff, "housing_kind": housing_kind, "evidence_url": url, "evidence_page": page, "evidence_text": quote, **fields}

    for page in pages:
        text = re.sub(r"\s+", " ", page["text"])
        # A regional quota table has its own column names. A points percentage
        # or newborn priority percentage must never become a regional quota.
        quota = re.search(r"(?:동일순위\s*내|우선공급\s*단계별)\s*지역우선\s*공급기준(.{0,1800})", text)
        if quota and re.search(r"지역구분\s+우선공급\s*비율", quota[1]):
            table_text = quota[1].split("※", 1)[0]
            shares = []
            patterns = [("local", r"해당\s*(?:주택건설)?지역"), ("other_gyeonggi", r"기타\s*경기(?:지역)?"), ("other", r"기타지역(?!\s*경기)")]
            for area, name in patterns:
                match = re.search(name + r"[^%]{0,100}?(\d{1,3})\s*%", table_text)
                if match:
                    shares.append({"residence_area": area, "percent": int(match[1])})
            if len(shares) >= 2 and any(s["residence_area"] == "local" for s in shares) and sum(s["percent"] for s in shares) == 100 and all(0 <= s["percent"] <= 100 for s in shares):
                result.append(make("regional_allocation", page["page"], quota.group(0)[:1500], supply_type=None,
                    supply_types=sorted({s["supply_type"] for s in all_inventory}),
                    unit_types=sorted({s["unit_type"] for s in all_inventory if s.get("unit_type")}) or None,
                    allocation_method="regional_quota", regional_shares=shares, local_share_percent=next(s["percent"] for s in shares if s["residence_area"] == "local")))
        # Require the actual selection order, not an admission/overseas example.
        order = re.search(r"(?:■\s*)?①\s*지역\s*[:：]\s*(해당지역\s*거주자.{0,260}?(?:→|⇒|->)\s*기타지역\s*거주자[^■]{0,150})", text)
        if rank_applies and inventory and order and "regional_allocation" not in {r.get("kind") for r in rules + result}:
            result.append(make("regional_allocation", page["page"], order.group(0), allocation_method="region_priority", local_share_percent=None))
        # Area-band tables must explicitly name the pair of percentage columns.
        # PDFs sometimes emit column numbers/units after the words. Normalize
        # these exact table layouts only, without filling in legal defaults.
        normalized = re.sub(r"1\s*/\s*전용면적별\s*순위", "전용면적별 1순위", text)
        normalized = re.sub(r"전용면적\s*(초과|이하)\s*(이하)?\s*(\d+(?:\.\d+)?)\s*(\d+(?:\.\d+)?)?\s*㎡\s*(㎡)?",
            lambda m: f"전용면적 {m[3]}㎡ {m[1]}" + (f" {m[4]}㎡ {m[2]}" if m[2] and m[4] else ""), normalized)
        table = re.search(r"전용면적별\s*1\s*순위\s*가점제\s*/?\s*추첨제\s*적용비율(.{0,1300}?)(?:가점\s*산정기준|가점항목|■)", normalized)
        if not private or not table or not re.search(r"가점제\s+추첨제", table.group(1)):
            continue
        band = re.compile(r"전용면적\s*(\d+(?:\.\d+)?)\s*(?:㎡|m²|제곱미터)\s*(이하|초과)(?:\s*(\d+(?:\.\d+)?)\s*(?:㎡|m²|제곱미터)\s*(이하))?")
        matches = list(band.finditer(table.group(1)))
        for i, match in enumerate(matches):
            row = table.group(1)[match.start():matches[i + 1].start() if i + 1 < len(matches) else len(table.group(1))]
            percentages = re.findall(r"(?<![\d.])(\d{1,3})\s*%", row)
            if len(percentages) == 2:
                points, lottery = map(int, percentages)
            elif len(percentages) == 1 and re.search(r"\s-\s+100\s*%", row):
                points, lottery = 0, 100
            elif len(percentages) == 1 and re.search(r"100\s*%\s+-", row):
                points, lottery = 100, 0
            else:
                continue
            if points + lottery != 100 or max(points, lottery) > 100:
                continue
            low = float(match[1]) if match[2] == "초과" else 0
            high = float(match[3]) if match[3] else float(match[1]) if match[2] == "이하" else None
            units = sorted({canonical_unit(s["unit_type"]) for s in inventory if isinstance(areas.get(canonical_unit(s.get("unit_type"))), (int, float)) and areas[canonical_unit(s["unit_type"])] > low and (high is None or areas[canonical_unit(s["unit_type"])] <= high)})
            if not units:
                continue
            anchor = text.find("전용면적별")
            quote = text[anchor:anchor + 1300] if anchor >= 0 else text[:1300]
            result.append(make("selection_method", page["page"], quote, unit_types=units, rank=1, points_percent=points, lottery_percent=lottery, min_area_exclusive=low, max_area_inclusive=high, tie_break="account_duration_then_lottery" if re.search(r"가점\s*→\s*[^■]{0,40}가입기간\s*→\s*[④➃]?\s*추첨", text) else "unknown"))
    return result
