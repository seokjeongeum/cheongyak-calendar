"""Applicant geography from operative sentences in the current document.

Administrative names/codes are reference data. No project, document hash, page
number, publication ID or project address chooses an applicant region.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def region_catalog():
    return json.loads(Path(__file__).with_name("administrative_regions.json").read_text())


@lru_cache(maxsize=1)
def _normalization_patterns():
    names = [r["name"] for r in region_catalog()["provinces"] + region_catalog()["districts"]]
    names += [name[:-1] + "특례시" for name in names if name.endswith("시")]
    return [(re.compile(r"\s*".join(map(re.escape, name.replace(" ", "")))), name.replace("특례시", "시"))
            for name in sorted(set(names), key=len, reverse=True) if len(name) >= 3]


def normalize_region_text(text: str) -> str:
    # Join only catalog names and legal terms, rather than arbitrary words.
    for pattern, name in _normalization_patterns():
        text = pattern.sub(name, text)
    text = re.sub(r"우선공\s*급", "우선공급", text)
    for token in ("거주", "우선", "청약", "신청", "장기복무"):
        text = re.sub(r"\s*".join(map(re.escape, token)), token, text)
    return re.sub(r"\s+", " ", text).strip()


def _flat(text):
    return re.sub(r"\s+", "", text).replace("특례시", "시")


def _region_names(text, cutoff, provinces):
    """Resolve only literal region names in a bounded applicant clause."""
    value = _flat(text)
    catalog = region_catalog()
    province_rows = [{"code": code, "name": name} for name, code in provinces.items()]
    province_rows += [r for r in catalog["provinces"] if r["name"] not in provinces and r.get("validFrom", "") <= cutoff]
    found_provinces = sorted([(m.start(), r) for r in province_rows for m in re.finditer(re.escape(r["name"]), value)], key=lambda item: item[0])
    found = []
    for index, row in found_provinces:
        # A qualified city is not an applicant scope covering its province.
        suffix = value[index + len(row["name"]):]
        city = re.match(r"([가-힣]+(?:시|군|구))(?=에|거주|\d+(?:년|개월)|[·,ㆍ、)(]|$)", suffix)
        # A PDF can omit the separator in "충청남도 대전광역시". An
        # adjacent literal province is another applicant territory, not an
        # unknown city qualified by the preceding province.
        adjacent_province = any(suffix.startswith(other["name"]) for other in province_rows)
        if city and not adjacent_province and not re.match(r"(?:및|또는|에|거주|이거나|하거나)", suffix):
            if not any(_flat(district["name"]) == city[1] and district.get("validFrom", "") <= cutoff
                       for district in catalog["districts"]):
                # Even if another listed territory is known, dropping this
                # municipality would produce a falsely complete narrower OR.
                return []
            continue
        found.append({"region_code": row["code"], "region_name": row["name"]})
    districts = [r for r in catalog["districts"] if r.get("validFrom", "") <= cutoff and _flat(r["name"]) in value]
    for row in districts:
        name = _flat(row["name"])
        at = value.find(name)
        # Parent-city entries intentionally survive alongside their ordinary
        # districts only when the source names the city, not a subdistrict.
        if any(_flat(r["name"]).startswith(name) and len(_flat(r["name"])) > len(name) and _flat(r["name"]) in value for r in districts):
            continue
        preceding = [r for index, r in found_provinces if index < at]
        parent = preceding[-1]["code"] if preceding else None
        if parent and parent != row["provinceCode"]:
            continue
        candidates = {r["provinceCode"] for r in districts if _flat(r["name"]) == name}
        if not parent and len(candidates) > 1:
            continue
        province = next((r["name"] for r in province_rows if r["code"] == row["provinceCode"]), None)
        if not province:
            continue
        found.append({"region_code": row["code"], "region_name": province + " " + row["name"]})
    # A listed full province already includes a city in the same OR clause.
    codes = {r["region_code"] for r in found if len(r["region_code"]) == 2}
    found = [r for r in found if len(r["region_code"]) == 2 or r["region_code"][:2] not in codes]
    return list({r["region_code"]: r for r in found}.values())


def _historical_maps(pages, cutoff):
    """Boundary mappings are accepted only where this source states them."""
    maps = {}
    catalog = region_catalog()
    for page in pages:
        text = normalize_region_text(page["text"])
        for province in catalog["provinces"]:
            if province.get("validFrom", "") > cutoff:
                continue
            for match in re.finditer(re.escape(province["name"]) + r"([^*■▌]{0,260}?)기존\s*([가-힣]+(?:광역시|특별시|도))", text):
                names = match[1]
                districts = [{"region_code": row["code"], "region_name": province["name"] + " " + row["name"]}
                    for row in catalog["districts"] if row["provinceCode"] == province["code"]
                    and re.search(r"(?<![가-힣])" + re.escape(row["name"]) + r"(?![가-힣])", names)]
                if not districts and not re.search(r"그\s*외\s*지역", names):
                    continue
                maps.setdefault(match[2], {"province": {"region_code": province["code"], "region_name": province["name"]},
                    "regions": districts, "complement": bool(re.search(r"그\s*외\s*지역", names)),
                    "evidence_page": page["page"], "evidence_text": match.group(0)})
    # A document explicitly naming a merged province and both of its former
    # territories can express the full union without a district mapping table.
    for page in pages:
        body = normalize_region_text(page["text"])
        for province in catalog["provinces"]:
            installation = re.search(re.escape(province["name"]) + r"\s*설치(?:를\s*위한)?\s*(?:특별법|와)", body)
            if province.get("validFrom", "") > cutoff or not installation:
                continue
            # Bind former names to the explicit installation note and nearby
            # region mapping/table, wherever that note moved in the document.
            # Later deposit tables cannot establish a boundary union.
            declaration = re.split(r"(?:\d+|[ⅠⅡⅢⅣⅤ]+)\s*공통\s*유의사항|[■▌]", body[installation.start():], maxsplit=1)[0][:1600]
            old_names = {match[1] for match in re.finditer(r"기존\s*([가-힣]+(?:광역시|특별시|도))", declaration)}
            if len(old_names) < 2:
                continue
            for old_name in old_names:
                maps.setdefault(old_name, {"province": {"region_code": province["code"], "region_name": province["name"]},
                    "regions": [], "complement": False})
            for old_name in old_names:
                if maps[old_name]["province"]["region_code"] == province["code"]:
                    maps[old_name]["explicit_union"] = True
    return maps


def _map_former_scope(regions, mapping, quote):
    old_names = {r["region_name"] for r in regions if r["region_name"] in mapping}
    groups = {}
    for name in old_names:
        groups.setdefault(mapping[name]["province"]["region_code"], []).append(name)
    mapped = []
    replaced = set()
    for names in groups.values():
        if len(names) >= 2 and (all(mapping[n].get("explicit_union") for n in names) or (any(mapping[n]["complement"] for n in names) and any(mapping[n]["regions"] for n in names))):
            mapped.append(mapping[names[0]]["province"])
            replaced.update(names)
    return [r for r in regions if r["region_name"] not in replaced] + mapped


def _military_exceptions(pages, make):
    result = []
    for page in pages:
        text = normalize_region_text(page["text"])
        clauses = [(int(match[1]), match[0], match[0]) for match in re.finditer(
            r"(\d+)(?:\s*\([^)]{0,45}\)\s*[^■▌•]{0,8})?\s*년\s*이상[^■▌•]{0,700}", text)]
        # Some PDFs place the number in a separate column later in the same
        # military sentence. Bind it to the leading years unit and its local
        # rank parenthesis; never borrow a number from another paragraph.
        for match in re.finditer(r"(?:^|[.)■])\s*(년\s*이상[^■]{0,700}?(\d+)\s*\([^■]{0,80}\)[^■]{0,150}■?[^■]{0,250}?거주자격[^■]{0,120}?청약[^■]{0,150})", text):
            quote = match[1]
            ordered = re.sub(re.escape(match[2]) + r"\s*\([^)]{0,80}\)\s*[, ]*\s*■?", "", quote, count=1)
            clauses.append((int(match[2]), quote, ordered))
        for years, quote, ordered in clauses:
            flat = _flat(ordered)
            if not all(word in flat for word in ("장기복무", "군인", "거주자격", "청약")):
                continue
            area = "other" if re.search(r"기타지역(?:\([^)]*\))?(?:의)?거주자격", flat) else "local" if re.search(r"(?:해당지역|해당주택건설지역)거주자격", flat) else None
            if years > 100 or area is None:
                continue
            fields = {"min_years": years, "currently_serving": True, "residence_area": area, "require_as_of_date": True}
            if "추천" in flat and "국방부" in flat:
                fields.update(recommendation_required=True, recommendation_authority="국방부(국군복지단)" if "국군복지단" in flat else "국방부")
            result.append(make("military_service_years", effect="metadata", quote=quote, page=page["page"], **fields))
    return list({(r["min_years"], r["residence_area"], r.get("recommendation_required")): r for r in result}.values())


def _priority(quote, cutoff, provinces):
    # Read the region in the actual competitive priority clause. Never derive
    # the local territory from 공급위치 or from the first applicant region.
    match = re.search(r"(?:다만|단,|경쟁|우선공급)[^■▌•]{0,500}?우선(?:합니다|하여|공급|적용)", quote)
    if not match:
        match = re.search(r"(?:해당\s*주택건설지역인\s*)?[^■▌•]{0,230}?거주자[^■▌•]{0,180}?우선(?:합니다|하여|공급)", quote)
    if not match:
        return None
    text = match.group(0)
    region_text = re.split(r"거주", text)[0]
    regions = _region_names(region_text, cutoff, provinces)
    if len(regions) != 1:
        return None
    minimum = re.search(r"(\d+)\s*\(?\s*(년|개월)\s*이상", text)
    months = int(minimum[1]) * (12 if minimum[2] == "년" else 1) if minimum else 0
    return {**regions[0], "min_months": months, "criterion_date": cutoff}


def explicit_applicant_regions(pages, *, cutoff, make, provinces, method=None):
    from .official_rules import _sections
    scoped_pages = {}
    for section in _sections(pages, shinhee=False):
        lines_by_page = {}
        for line in section["lines"]:
            lines_by_page.setdefault(line["page"], []).append(line["text"])
        for page, lines in lines_by_page.items():
            scoped_pages.setdefault(page, []).append((section["supply_type"], normalize_region_text(" ".join(lines))))
    candidates = []
    military = _military_exceptions(pages, make)
    historical_maps = _historical_maps(pages, cutoff)
    for page in pages:
        text = normalize_region_text(page["text"])
        date_label = r"(?:분양|모집)광고일" if method == "officetel" else r"(?:최초\s*)?(?:입주자\s*모집공고일|분양광고일|매각공고일)"
        for match in re.finditer(date_label + r"(?:\s*\([^)]{0,35}\))?\s*현재[^■▌Ÿ•]{0,1100}", text):
            quote = match.group(0)
            flat = _flat(quote)
            if not re.search(r"청약이?가능|신청가능|신청할수|신청자격|무주택세대(?:구성원|주)|대상으로공급", flat):
                continue
            if re.search(r"과거|이전공고|했던|당시|최초공고의", flat):
                continue
            dated = re.search(r"\(\s*(20\d{2})[.년/-]\s*(\d{1,2})[.월/-]\s*(\d{1,2})", quote.split("현재")[0])
            if dated and "-".join((dated[1], dated[2].zfill(2), dated[3].zfill(2))) != cutoff:
                continue
            geography = re.split(r"(?:만\s*(?:\d+\s*)?세|성년|무주택세대|청약(?:이|신청)?\s*가능)", quote)[0]
            # A domestic residence sentence by itself does not waive a more
            # specific province/city scope in the same applicant clause.
            regions = _region_names(geography, cutoff, provinces)
            if regions and not re.search(r"에\s*거주|거주(?:하는|하고|자|중)", geography):
                # Deposit tables also name provinces, but they describe bank
                # amounts rather than the applicant's place of residence.
                continue
            source_regions = regions
            regions = _map_former_scope(regions, historical_maps, quote)
            fields = {"scope_complete": True}
            if regions:
                fields["regions"] = regions
            elif not any(name in geography for name in provinces) and re.search(r"(?:대한민국|국내|전국)(?:\([^)]*\))?에?\s*거주|(?:거주지역|거주지)[^■]{0,100}(?:불문|무관|관계없이|제한없)", geography):
                fields.update(unrestricted=True, domestic_only=True)
            else:
                continue
            priority = _priority(quote, cutoff, provinces)
            if priority and priority["region_name"] in historical_maps and historical_maps[priority["region_name"]]["regions"]:
                mapped = historical_maps[priority["region_name"]]
                priority["regions"] = mapped["regions"]
                mapping_rule = make("regional_mapping", quote=mapped["evidence_text"], page=mapped["evidence_page"])
                priority["mapping_evidence"] = {k: mapping_rule[k] for k in ("evidence_page", "evidence_text", "evidence_url", "document_hash") if k in mapping_rule}
            if priority is None or len(priority["region_code"]) == 2 and any(re.search(re.escape(r["name"])+r"\s*거주", quote) for r in region_catalog()["districts"]):
                # A mapped former province can qualify a unique current county.
                priority_quote = re.search(r"(?:다만|경쟁)[^■▌•]{0,500}?우선(?:합니다|하여|공급)", quote)
                if priority_quote:
                    changed = priority_quote[0]
                    for old, mapping in historical_maps.items():
                        if mapping["complement"] or mapping.get("explicit_union"):
                            changed = changed.replace(old, mapping["province"]["region_name"])
                    priority = _priority(changed, cutoff, provinces)
            if regions != source_regions:
                fields.update(source_regions=source_regions, region_mapping_basis="explicit_union_of_former_provinces")
            if priority:
                fields.update(priority_applicable=True, local_priority=priority)
            elif fields.get("unrestricted") or re.search(r"지역\s*우선[^■]{0,70}(?:없|미적용|적용하지)", quote):
                fields["priority_applicable"] = False
            # No explicit priority remains unspecified rather than invented.
            if military:
                fields["exceptions"] = military
            supplies = [supply for supply, body in scoped_pages.get(page["page"], []) if quote.strip() in body]
            for supply in list(dict.fromkeys(supplies)) or [None]:
                candidates.append(make("applicant_regions", effect="metadata", quote=quote, page=page["page"],
                                       **({"supply_type": supply} if supply else {}), **fields))
    unique = {}
    for rule in candidates:
        key = (rule.get("supply_type"), str(rule.get("regions")), rule.get("unrestricted"), str(rule.get("local_priority")))
        unique.setdefault(key, rule)
    # A complete common applicant paragraph beats an abbreviated table which
    # enumerates only the last province. Conflicting full scopes remain visible.
    rules = list(unique.values())
    common = [r for r in rules if not r.get("supply_type")]
    with_priority = [r for r in common if r.get("local_priority")]
    if with_priority and all(any({p["region_code"] for p in rule.get("regions", [])} <=
                                 {p["region_code"] for p in full.get("regions", [])} for full in with_priority)
                             for rule in common):
        common = with_priority
    scoped = [rule for rule in rules if rule.get("supply_type") and not any(
        rule.get("regions") == base.get("regions") and rule.get("unrestricted") == base.get("unrestricted")
        and (not rule.get("local_priority") or rule.get("local_priority") == base.get("local_priority"))
        for base in common)]
    return common + scoped


def reviewed_applicant_regions(pages, *, url, digest, cutoff, make):
    """Compatibility entry point; every result is parsed from current text."""
    provinces = {r["name"]: r["code"] for r in region_catalog()["provinces"]}
    provinces.update({"광주광역시": "29", "전라남도": "46"})
    return explicit_applicant_regions(pages, cutoff=cutoff, make=make, provinces=provinces)
