"""Applicant review of Sangok's exact 2026-10-08, 70-page notice.

This review supplies independently checked page anchors to the common private
condition model. Allocation evidence, paperwork and an address do not certify
applicant conditions. Conditional exemption/conversion routes remain explicit.
"""
from __future__ import annotations

import re

from .current_private_admission import current_private_admission
from .hangang_admission import GENERAL, SPECIALS

SANGOK_HASH = "10597652e7b524abfc4b6609e00f430793f820b0732c130f94c788585285e67b"
REVIEW_VERSION = "sangok-admission-2026-10-10-v1"
LAYOUT = {
    "title": "산곡역자이힐스테이트앤하늘채", "count": 70,
    "summary": 1, "active": 2, "overseas": 3, "restriction": 4,
    "ineligible": 4, "used": 5, "once": 11, "foreign": 12,
    "bank": 12, "nomination": 13, "general": 26, "domestic": 5,
    "first": 21, "first_income": 22, "first_asset": 23,
    "newborn": 24, "newborn_income": 24, "newborn_asset": 25,
    "newborn_scope": 25, "elder": 19, "ownership": 40, "benefits": 38,
    "newlywed_income": 17, "newlywed_asset": 18,
    "newlywed_policy": 16, "newlywed_scope": 17,
    "reasons": ["장애인", "국가유공자·보훈", "중소기업 장기근속", "장기복무 군인"],
    "unsupported_reasons": ["기타"],
}


def sangok_admission(pages, *, digest, reviewed, rules, offered, make):
    if (digest != SANGOK_HASH or not reviewed or reviewed.get("title") != LAYOUT["title"]
            or reviewed.get("announcement_date") != "2026-10-08"):
        return None
    source = {p["page"]: re.sub(r"\s+", " ", p["text"]).strip() for p in pages}
    if not set(range(1, 71)) <= source.keys() or set(offered) != {GENERAL, *SPECIALS}:
        return None

    def e(page, pattern):
        match = re.search(pattern, source[page])
        return {"page": page, "quote": match.group(0)} if match else None

    # Independently checked mandatory paragraphs. Missing or changed clauses
    # cannot inherit a previous review merely because the hash field survived.
    adult = e(5, r"만\s*19세\s*이상인\s*분\s*또는\s*세대주인\s*미성년자\s*\(자녀양육,\s*형제자매부양\)")
    head_waiver = e(1, r"세대주\s*요건\s*-\s*-\s*-\s*필요\s*-\s*-\s*-\s*-")
    special_once = e(11, r"특별공급은\s*무주택세대구성원에게\s*한\s*차례에\s*한정하여\s*1세대\s*1주택\s*기준으로\s*공급합니다")
    rewinning = e(5, r"재당첨\s*제한을\s*적용받지\s*않으며.{0,160}?본\s*아파트\s*청약이\s*가능합니다")
    ownership = e(5, r"1주택\s*이상\s*소유하신\s*분도\s*청약\s*1순위\s*자격이\s*부여됩니다")
    multi = e(14, r"만\s*19세\s*미만의\s*자녀\s*2명\s*이상\(태아,\s*입양자녀\s*포함\)")
    elder = e(19, r"만\s*65세\s*이상의\s*직계존속.{0,200}?3년\s*이상\s*계속하여\s*부양.{0,120}?등재되어\s*있는\s*경우에\s*한함\)")
    newborn = e(24, r"2세\s*미만\(2세가\s*되는\s*날을\s*포함한다\)의\s*자녀\(임신중이거나\s*입양한\s*경우\s*포함\)")
    household = e(12, r"기관추천\s*/\s*다자녀가구\s*/\s*신혼부부\s*/\s*생애최초\s*/\s*신생아\s*특별공급\s*:\s*무주택세대구성원\s*요건.{0,100}?노부모부양\s*특별공급\s*:\s*무주택세대주\s*요건")
    nomination = e(13, r"장기복무\s*제대군인.{0,350}?10년\s*이상\s*장기복무군인.{0,600}?중소기업\s*근로자.{0,500}?장애인")
    deposits = e(12, r"전용면적\s*85㎡\s*이하\s*250만원\s*300만원\s*200만원.{0,400}?모든면적\s*1,000만원\s*1,500만원\s*500만원")
    if not all((adult, head_waiver, special_once, rewinning, ownership, multi, elder, newborn, household, nomination, deposits)):
        return None
    result = current_private_admission(
        pages, digest=digest, reviewed=reviewed, rules=rules, offered=offered, make=make,
        _reviewed_layout=LAYOUT, _review_version=REVIEW_VERSION,
    )
    if not result:
        return None

    # Sangok explicitly lists both serving and retired long-service military
    # recommendations. Its dual-income paragraph requires ONE spouse below
    # 140%, not both; preserve the exact conditional limit while its separate
    # spouse incomes remain outside the current input model.
    for rule in result["rules"]:
        if rule["kind"] == "recommendation" and rule.get("supply_type") == SPECIALS[0]:
            rule["unsupported_reason_label"] = "철거주택 소유자·도시재생 부지제공자의 별도 추천 분기"
            rule["unsupported_reason_evidence_page"] = 13
            rule["unsupported_reason_evidence_text"] = nomination["quote"]
        pending = [rule]
        while pending:
            item = pending.pop()
            pending.extend(item.get("conditions", []))
            if item["kind"] == "unparsed" and item.get("supply_type") == SPECIALS[2] and "각각" in item.get("label", ""):
                item["label"] = "부부 중 1인의 140% 소득 상한"
                item["text"] = "맞벌이 합산 160% 이하 경로는 부부 중 1인의 소득이 140% 이하여야 합니다."
    for topic in result["conditional_topics"][SPECIALS[0]]:
        if "장기복무 제대군인" in topic["topic"]:
            topic["topic"] = topic["reason"] = "철거주택 소유자·도시재생 부지제공자의 추천·통장 면제 분기"
    for topic in result["conditional_topics"][SPECIALS[2]]:
        if "각각" in topic["topic"]:
            topic["topic"] = topic["reason"] = "부부 중 1인의 140% 소득 상한"

    # The ordinary parser omitted the general adult/domestic paragraph. The
    # minor-head exception is real and remains a conditional source review.
    result["rules"].append(make("any", label="성년 또는 공고의 미성년 세대주", conditions=[
        make("age_min", 19, operator=">=", unit="years", **adult),
        make("all", label="자녀양육·형제자매부양 미성년 세대주", conditions=[
            make("household_head", True, **adult),
            make("unparsed", label="미성년 세대주의 자녀양육·형제자매부양 요건",
                 text="19세 미만 세대주의 실제 자녀양육 또는 형제자매부양 사유와 등본을 대조해야 합니다.", **adult),
        ], **adult),
    ], **adult))

    # Same source explicitly waives these applicant constraints. A future
    # consequence of winning this notice is not a present admission failure.
    for supply in offered:
        result["exempt_topics"].setdefault(supply, []).append({
            "topic": "재당첨 제한", "status": "not_applicable", "required": False,
            "rule_ids": [], "evidence_page": 5, "evidence_text": rewinning["quote"],
        })
    result["exempt_topics"][GENERAL].extend({
        "topic": topic, "status": "not_applicable", "required": False, "rule_ids": [],
        "evidence_page": evidence["page"], "evidence_text": evidence["quote"],
    } for topic, evidence in (("무주택 세대구성원", ownership), ("세대주", head_waiver), ("특별공급 횟수 제한", special_once)))
    for supply in offered:
        result["conditional_topics"][supply].append({
            "topic": "미성년 세대주의 실제 자녀양육·형제자매부양", "status": "partial",
            "required": False, "phase": "conditional_admission", "rule_ids": [],
            "reason": "성년인 분에게는 적용하지 않습니다.",
        })

    instructions = [
        {"label": "동일 발표일 중복 신청·부부 예외", "phase": "application",
         "detail": "본인은 동일 주택에 특별공급과 일반공급 각 1건씩 신청할 수 있습니다. 같은 유형의 중복 신청은 무효이며, 부부의 동일 발표일 중복 당첨은 먼저 접수한 건만 유효합니다.",
         "evidence_page": 12, "evidence_text": source[12][:850]},
        {"label": "서류·출산 및 입양 확인·계약금 납부", "phase": "post_selection",
         "detail": "증빙서류 제출, 임신·입양의 입주 시 확인과 계약금·중도금·잔금은 당첨 후 이행 절차입니다.",
         "evidence_page": 32, "evidence_text": source[32][:850]},
    ]
    provenance = make("application_instructions")
    for item in instructions:
        item.update({"evidence_url": provenance["evidence_url"], "document_hash": digest})
    result["rules"].append(make("application_instructions", effect="metadata", instructions=instructions,
                                page=12, quote=source[12][:850]))
    # The entire source was reviewed; these page-bound checks are mandatory
    # admission sections, not a count-based certificate.
    result["reviewed_pages"] = list(range(1, 71))
    return result
