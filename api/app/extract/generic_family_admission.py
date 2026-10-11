"""Read public family routes from operative headings and this document's tables.

The parser does not select notices by identity, hash, page number or annual
financial values.  Unmodelled household and assessment branches remain explicit
source gaps; extracting a financial row never certifies an entire family route.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

REVIEW_VERSION = "generic-admission-family-2026-10-10-v1"
FAMILIES = ("신혼부부", "예비신혼부부", "한부모가족")


def _normal(text):
    return re.sub(r"\s+", " ", text).strip()


def _sections(pages):
    sections, current = [], None
    for page in pages:
        for line in page["text"].splitlines():
            clean = _normal(line)
            heading = re.match(r"^\d+(?:[.-]\d+)*[.)]?\s*(신혼부부|예비신혼부부|한부모가족)\s*신청자격\s*$", clean)
            if heading:
                current = {"family": heading[1], "lines": []}
                sections.append(current)
            elif re.match(r"^\d+(?:[.-]\d+)*[.)]?\s+[가-힣]", clean):
                current = None
            if current is not None:
                current["lines"].append({"page": page["page"], "text": line})
    # An index heading cannot establish an offered route without an applicant
    # body. Duplicate operative sections remain a conflict rather than winning
    # by their position in the file.
    return [section for section in sections if re.search(r"입주자모집공고일\s*현재|아래\s*조건|무주택", _normal(" ".join(line["text"] for line in section["lines"])))]


def _find(lines, pattern):
    """An exact matched quote plus the page where that match starts."""
    body, offsets = "", []
    for line in lines:
        offsets.append((len(body), line["page"]))
        body += _normal(line["text"]) + " "
    match = re.search(pattern, body)
    if not match:
        return None
    page = next(page for offset, page in reversed(offsets) if offset <= match.start())
    return {"page": page, "quote": match[0].strip()}


def _table_sections(pages, title):
    """Printed table headings, not prose references to those tables."""
    tables, current = [], None
    for page in pages:
        for line in page["text"].splitlines():
            clean = _normal(line)
            heading = re.match(r"^[<〈]\s*표\s*\d+\s*[>〉]\s*(.+)$", clean)
            if heading:
                current = {"lines": []} if re.search(title, heading[1]) else None
                if current is not None:
                    tables.append(current)
            elif re.match(r"^\d+\.\s+[가-힣]|^■\s+", clean):
                current = None
            if current is not None:
                current["lines"].append({"page": page["page"], "text": line})
    return tables


def _income_tables(pages):
    tables, evidence, conflict = {}, None, False
    min_size = None
    for section in _table_sections(pages, r"(?:전년도\s*도시근로자\s*가구당\s*월평균소득\s*기준|출산가구\s*소득기준\s*완화)"):
        body = _normal(" ".join(line["text"] for line in section["lines"]))
        header = re.search(r"구분\s*((?:\d+\s*인\s*(?:이하)?\s*){2,})", body)
        if not header:
            continue
        sizes = [int(n) for n in re.findall(r"(\d+)\s*인", header[1])]
        if sizes != sorted(set(sizes)):
            conflict = True
            continue
        if min_size is not None and min_size != sizes[0]:
            conflict = True
        min_size = sizes[0]
        anchors = list(re.finditer(r"전년도\s*도시근로자\s*가구당\s*월평균소득의\s*(\d+)\s*%", body))
        for index, anchor in enumerate(anchors):
            tail = body[anchor.end():anchors[index + 1].start() if index + 1 < len(anchors) else len(body)]
            tail = re.split(r"※|•|<", tail, maxsplit=1)[0]
            # Comma grouped values distinguish money from percentage/age/date
            # annotations. Require exactly a full printed household row.
            amounts = re.findall(r"(?<![\d,])\d{1,3}(?:,\d{3})+(?![\d,])", tail)
            if len(amounts) != len(sizes):
                conflict = True
                continue
            row = [{"household_size": size, "max_krw": int(amount.replace(",", ""))} for size, amount in zip(sizes, amounts)]
            if any(entry["max_krw"] <= 0 for entry in row) or any(a["max_krw"] > b["max_krw"] for a, b in zip(row, row[1:])):
                conflict = True
                continue
            key = anchor[1]
            if key in tables and tables[key] != row:
                conflict = True
            else:
                tables[key] = row
            if evidence is None:
                evidence = _find(section["lines"], re.escape(anchor[0]) + r".{0,450}")
    return ({}, None, None) if conflict else (tables, min_size, evidence)


def _date_from_quote(quote):
    dates = set()
    for match in re.finditer(r"(?<!\d)(\d{2}|\d{4})\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})\s*[.일]?\s*이후\s*출생", quote):
        year, month, day = map(int, match.groups())
        if year < 100:
            year += 2000
        try:
            dates.add(date(year, month, day).isoformat())
        except ValueError:
            return None
    return next(iter(dates)) if len(dates) == 1 else None


def _money(matches):
    multiplier = {"원": 1, "천원": 1000, "만원": 10000, "억원": 100000000}
    return [int(Decimal(amount.replace(",", "")) * multiplier[unit]) for amount, unit in matches]


def _relaxation_policy(anchor):
    if not anchor:
        return {"child_relaxation_policy_supported": False}
    one = re.search(r"(\d+)\s*명(?:만)?\s*(?:있는|인)\s*경우\s*(\d+)\s*%p", anchor["quote"])
    two = re.search(r"(\d+)\s*명\s*이상.{0,300}?인\s*경우\s*(\d+)\s*%p", anchor["quote"])
    if not one or not two:
        return {"child_relaxation_policy_supported": False}
    older = bool(re.search(r"(?:전|이전)\s*출생한\s*자녀가.{0,40}?있는\s*경우\s*포함", anchor["quote"]))
    values = {"one_child_bonus_percent": int(one[2]), "two_children_bonus_percent": int(two[2]),
              "one_child_count": int(one[1]), "two_children_count_min": int(two[1]),
              "include_older_children_when_recent_child_exists": older}
    # The current browser implements this particular one/two-child branch.
    # Other printed policies are retained as metadata and explicitly require
    # review instead of inheriting the browser's old 10/20-percent fallback.
    values["child_relaxation_policy_supported"] = bool(values["one_child_count"] == 1
        and values["two_children_count_min"] == 2 and older
        and values["one_child_bonus_percent"] == 10 and values["two_children_bonus_percent"] == 20)
    return values


def _asset_tables(pages):
    base, base_anchor, child, child_anchor = set(), None, None, None
    for table in _table_sections(pages, r"총자산보유기준|출산가구\s*자산보유기준\s*완화"):
        body = _normal(" ".join(line["text"] for line in table["lines"]))
        amounts = _money(re.findall(r"([\d,]+(?:\.\d+)?)\s*(천원|만원|억원|원)\s*이하", body))
        if "출산가구" not in table["lines"][0]["text"]:
            # PDF text can interleave the other table column between the
            # monetary cell and its following "이하" line.
            if not amounts and re.search(r"합계액에서.{0,60}?차감한.{0,80}?금액이", body):
                amounts = _money(re.findall(r"([\d,]+(?:\.\d+)?)\s*(천원|만원|억원|원)(?=.{0,160}?이하)", body))
            if len(amounts) == 1:
                base.add(amounts[0])
                base_anchor = _find(table["lines"], r"[\d,]+(?:\.\d+)?\s*(?:천원|만원|억원|원).{0,160}?이하")
        else:
            headers = re.findall(r"([12])\s*명\s*(?:이상)?인\s*경우", body)
            if len(headers) == 2 and set(headers) == {"1", "2"} and len(amounts) == 2:
                mapped = dict(zip(headers, amounts))
                if child is not None and child != mapped:
                    return None
                child = mapped
                child_anchor = {"page": table["lines"][0]["page"], "quote": body[:900]}
    if len(base) != 1 or not base_anchor:
        return None
    return {"base_max_krw": next(iter(base)), "one_child_max_krw": child.get("1") if child else None,
            "two_children_max_krw": child.get("2") if child else None, "base_anchor": base_anchor, "child_anchor": child_anchor}


def generic_family_admission(pages, *, digest, make):
    sections = _sections(pages)
    if not sections:
        return None
    lines = [{"page": page["page"], "text": line} for page in pages for line in page["text"].splitlines()]
    tables, min_size, table_evidence = _income_tables(pages)
    assets = _asset_tables(pages)
    financial_relaxation = {}
    for topic in ("소득", "자산"):
        relaxation = _find(lines, r"출산가구\s*" + topic + r"기준\s*완화.{0,650}?기준\s*완화")
        policy = _relaxation_policy(relaxation)
        relaxation_date = _date_from_quote(relaxation["quote"]) if relaxation and policy["child_relaxation_policy_supported"] else None
        financial_relaxation[topic] = {"policy": policy, "date": relaxation_date}
    income_scope = _find(lines, r"<가구원수\s*적용\s*기준>.{0,900}?소득산정\s*대상에서\s*제외")
    member_age = re.search(r"만\s*(\d+)\s*세\s*이상", income_scope["quote"]) if income_scope else None
    output, inventory, offered = [], [], []
    missing, conditional = {}, {}
    family_counts = {family: sum(s["family"] == family for s in sections) for family in FAMILIES}
    for section in sections:
        family = section["family"]
        supply = family + "(신혼희망타운)"
        if supply in offered:
            continue
        offered.append(supply)
        missing[supply], conditional[supply] = [], []
        target = section["lines"]
        body = _normal(" ".join(line["text"] for line in target))
        anchor = {"page": target[0]["page"], "quote": body[:900]}
        inventory.append({"supply_type": supply, "unit_type": None, "supply_count": None,
                          **{k: v for k, v in make("offered_supplies", **anchor).items() if k in {"verification", "document_hash", "criterion_date", "evidence_url", "evidence_text", "evidence_page"}}})
        if family_counts[family] > 1:
            missing[supply].append("신청자격 문단이 중복되어 현재 적용 분기를 대조해야 합니다.")
            continue
        bank = _find(target, r"입주자저축에\s*가입하여\s*\d+\s*개월.{0,220}?\d+\s*회\s*이상\s*납입한\s*분")
        if bank:
            months = re.search(r"(\d+)\s*개월", bank["quote"])
            payments = re.search(r"(\d+)\s*회\s*이상", bank["quote"])
            output.extend([make("subscription_months", int(months[1]), supply=supply, operator=">=", housing_kind="national",
                                supersedes_rule_kinds=["national_rank_months"], **bank),
                           make("recognized_payments_min", int(payments[1]), supply=supply, operator=">=", require_as_of_date=True, value_basis="announcement_balance", **bank)])
        elif re.search(r"입주자저축|청약통장", body):
            missing[supply].append("이 신청자격의 통장 가입기간·납입인정 횟수")
        homeless = _find(target, r"무주택세대구성원|혼인으로\s*구성할\s*세대원\s*전원이\s*무주택")
        if family == "예비신혼부부":
            planned = _find(target, r"혼인을\s*준비\s*중인.{0,250}?입주\s*전까지\s*혼인사실을\s*증명할\s*수")
            if planned:
                output.append(make("planned_marriage", True, supply=supply, must_prove_before="occupancy", **planned))
            else:
                missing[supply].append("예정 혼인 관계·혼인사실 확인 시점")
            if homeless:
                output.append(make("unparsed", supply=supply, label="혼인으로 구성할 세대의 주택 소유",
                                   text="예정 배우자와 혼인으로 구성할 세대의 보유 사실을 현재 등본 가족과 구분하여 대조해야 합니다.", **homeless))
            if re.search(r"전배우자와\s*재혼", body):
                missing[supply].append("예정 배우자와의 과거 혼인·재혼 제한")
        elif homeless:
            output.append(make("homeless", True, supply=supply, **homeless))
        else:
            missing[supply].append("신청 세대의 무주택 요건")

        child_anchor = _find(target, r"(?:만\s*\d+\s*세\s*미만|\d+\s*세\s*이하).{0,120}?자녀.{0,150}?(?:무주택세대구성원|를\s*둔\s*한부모가족)")
        child = None
        if child_anchor:
            exclusive = re.search(r"만\s*(\d+)\s*세\s*미만", child_anchor["quote"])
            inclusive = re.search(r"(\d+)\s*세\s*이하", child_anchor["quote"])
            age = int(exclusive[1]) if exclusive else int(inclusive[1])
            child = make("children_min", 1, child_age_max=age, child_age_inclusive=not bool(exclusive),
                         include_pregnancy=bool(re.search(r"태아", child_anchor["quote"])),
                         include_adoption=bool(re.search(r"입양", child_anchor["quote"])), operator=">=", **child_anchor)
        if family == "신혼부부":
            marriage = _find(target, r"혼인\s*중인.{0,180}?혼인기간이\s*\d+\s*(?:년|개월)\s*이내")
            if marriage:
                duration = re.search(r"혼인기간이\s*(\d+)\s*(년|개월)", marriage["quote"])
                months = int(duration[1]) * (12 if duration[2] == "년" else 1)
                period = make("marriage_months_max", months, operator="<=", anniversary_limit=True, **marriage)
                alternatives = [period, child] if child and re.search(r"또는", body) else [period]
                output.append(make("all", supply=supply, label="혼인·자녀 요건", conditions=[make("marital_status", allowed_values=["married"], **marriage), make("any", conditions=alternatives, **marriage)], **marriage))
                if re.search(r"동일\s*배우자.{0,100}?혼인기간.{0,100}?합산", body):
                    conditional[supply].append({"topic": "동일 배우자와 재혼한 경우 전체 혼인기간 합산", "status": "partial", "required": False, "phase": "conditional_admission", "rule_ids": []})
            else:
                missing[supply].append("혼인기간·자녀의 대체 신청자격")
        elif family == "한부모가족":
            parent = _find(target, r"한부모가족.{0,180}?부\s*또는\s*모")
            if parent and child:
                output.append(make("all", supply=supply, label="한부모가족·자녀 요건", conditions=[make("single_parent_family", True, **parent), child], **parent))
            else:
                missing[supply].append("한부모가족 관계·자녀 연령")

        income = _find(target, r"월평균소득이.{0,340}?\d+\s*%.{0,180}?이하인\s*분")
        normal_percent = re.search(r"(\d+)\s*%", income["quote"]) if income else None
        dual = re.search(r"본인\s*및\s*배우자가\s*모두\s*소득이\s*있는\s*경우.{0,35}?(\d+)\s*%", income["quote"]) if income else None
        required_percents = {normal_percent[1]} if normal_percent else set()
        if dual:
            required_percents.add(dual[1])
        if income and min_size and required_percents and required_percents <= tables.keys():
            output.append(make("shinhee_income", supply=supply, value_basis="household_monthly_income",
                               household_size_basis="official_income_household", min_household_size=min_size,
                               percentage_tables=tables, normal_percent=int(normal_percent[1]),
                               dual_income_percent=int(dual[1]) if dual else None, child_relaxation_since=financial_relaxation["소득"]["date"],
                               **financial_relaxation["소득"]["policy"],
                               table_evidence_page=table_evidence["page"], table_evidence_text=table_evidence["quote"], **income))
            if income_scope and member_age:
                output.append(make("income_household_scope", supply=supply, effect="metadata", member_basis="planned_household" if family == "예비신혼부부" else "homeless_household",
                                   include_fetuses="태아" in income_scope["quote"], income_member_min_age=int(member_age[1]),
                                   registered_ascendants_only=True, **income_scope))
            else:
                missing[supply].append("소득 산정 가구원·소득 합산 대상의 범위")
        elif re.search(r"월평균소득|소득기준", body):
            missing[supply].append("해당 신청자격의 소득 비율·가구원수별 공식 금액표")
        else:
            missing[supply].append("해당 신청자격의 소득 적용·면제 조항")
        asset_requirement = _find(target, r"해당\s*세대의\s*총자산\s*합계액이.{0,130}?이하인\s*분")
        if asset_requirement and assets:
            output.append(make("shinhee_assets", supply=supply, asset_basis="official_net_household", child_relaxation_since=financial_relaxation["자산"]["date"],
                               **financial_relaxation["자산"]["policy"],
                               **{k: assets[k] for k in ("base_max_krw", "one_child_max_krw", "two_children_max_krw")},
                               table_evidence_page=assets["base_anchor"]["page"], table_evidence_text=assets["base_anchor"]["quote"],
                               **(assets["child_anchor"] or asset_requirement)))
        elif re.search(r"총자산", body):
            missing[supply].append("공식 순자산 산정 범위·상한 금액")
        else:
            missing[supply].append("해당 신청자격의 자산 적용·면제 조항")
        # Exact assessment timing differs by financial item and can include
        # changes discovered after announcement. A current single amount does
        # not model those mandatory original-document rules.
        if assets:
            missing[supply].append("자산 항목별 평가시점·조사기준일 및 공고 후 조회 변동액의 적용")
        if not all(part["date"] for part in financial_relaxation.values()):
            conditional[supply].append({"topic": "출산가구 소득·자산 완화의 날짜·자녀수별 가산 정책", "status": "partial", "required": False,
                                       "phase": "conditional_admission", "rule_ids": []})
        if re.search(r"입주\s*시까지\s*무주택", _normal(" ".join(line["text"] for line in lines))):
            conditional[supply].append({"topic": "입주 시까지 신청 세대의 무주택 유지", "status": "partial", "required": False, "phase": "post_selection", "rule_ids": []})
        # An extra numbered requirement is never covered by neighbouring facts.
        numbered = re.split(r"(?m)^\s*[①②③④⑤⑥⑦⑧⑨⑩]", "\n".join(line["text"] for line in target))[1:]
        for clause in numbered:
            if not re.search(r"혼인|한부모|입주자저축|월평균소득|총자산", clause):
                missing[supply].append("추가 신청자격 조항: " + clause[:180])
        if re.search(r"자동차.{0,40}?(?:이하|초과)|근로.{0,30}?\d+\s*년|세대주이어야", body):
            missing[supply].append("추가 신청자격의 차량·근로·세대주 분기")

        whole = _normal(" ".join(line["text"] for line in lines))
        common = [(r"재당첨.{0,160}?제한", "재당첨 제한의 확인 대상·혼인 전 당첨 등 예외"),
                  (r"부적격.{0,160}?(?:제한|선정될\s*수\s*없는)", "부적격 당첨 제한의 확인 대상·적용 기간"),
                  (r"특별공급.{0,130}?(?:받은|당첨|횟수|제한)", "특별공급 당첨 이력·횟수 제한과 공식 예외"),
                  (r"해외|국외", "해외 연속체류·국내 거주 인정 예외")]
        for pattern, topic in common:
            if re.search(pattern, whole):
                missing[supply].append(topic)
        if not all(re.search(pattern, whole) for pattern, _ in common):
            missing[supply].append("미확보 공통 신청 제한·해외체류 적용·면제 조항")

    citizenship = _find(lines, r"외국인의\s*경우\s*본\s*아파트\s*청약신청이\s*불가합니다")
    if citizenship:
        output.append(make("citizenship", allowed_values=["korean"], **citizenship))
    if inventory:
        output.append(make("offered_supplies", effect="metadata", supplies=inventory, inventory_status="partial",
                           inventory_basis="operative_family_qualification_headings", inventory_scope_complete=True,
                           **{"page": inventory[0]["evidence_page"], "quote": inventory[0]["evidence_text"]}))
    return {"rules": output, "offered": offered, "offered_supply_types": offered, "supplies": inventory,
            "missing_topics": missing, "conditional_topics": conditional, "exempt_topics": {s: [] for s in offered},
            "review_version": REVIEW_VERSION, "reviewed_pages": [p["page"] for p in pages],
            "completion_basis": "document_structure_reviewed_standard_branch"}
