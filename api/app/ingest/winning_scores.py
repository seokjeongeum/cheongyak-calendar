"""Official winning-score API and result table. Stored independently of closure proof."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re

import httpx
from sqlalchemy import select

from app.models import Notice
from app.repository import lock_notice
from .common import FeedError, get_json, integer
from .competition import API_BASE, AREA_BY_CODE, AREA_BY_LABEL, CompetitionTableParser, unit_key


def score(raw) -> float | None:
    text = str(raw).strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        return None
    value = float(text)
    return value if 0 <= value <= 84 else None


def parse_score_popup(html: str, *, url: str, house_no: str, notice_no: str, observed_at: str) -> list[dict]:
    parser = CompetitionTableParser()
    parser.feed(html)
    if not parser.found_table or not parser.closed_table:
        raise FeedError("공식 당첨가점 결과 표를 확인하지 못했습니다.")
    digest = hashlib.sha256(html.encode()).hexdigest()
    rows = []
    for row in parser.rows:
        attrs, cells = row["attrs"], row["cells"]
        if (not attrs.get("data-ty") or len(cells) != 11
                or "cpHouseTy" not in cells[0]["class"].split()
                or "cpRank1" not in cells[2]["class"].split()
                or re.sub(r"\s+", "", cells[2]["text"]) != "1순위"
                or "cpSubscrptRt" not in cells[6]["class"].split()):
            continue
        area = AREA_BY_LABEL.get(re.sub(r"\s+", "", cells[3]["text"]), "unknown")
        # Header positions are verified against the actual first-rank table;
        # placeholder colspan cells have fewer columns and cannot become 0.
        if (unit_key(cells[0]["text"]) != unit_key(attrs["data-ty"]) or area == "unknown"
                or re.sub(r"\s+", "", attrs.get("data-sem") or "") != re.sub(r"\s+", "", cells[3]["text"])
                or "cpResideSenm" not in cells[7]["class"].split()
                or re.sub(r"\s+", "", cells[7]["text"]) != re.sub(r"\s+", "", cells[3]["text"])):
            continue
        minimum, maximum, average = [score(cell["text"]) for cell in cells[8:11]]
        if minimum is None or maximum is None or average is None or not minimum <= average <= maximum:
            continue
        rows.append(dict(unit_type=cells[0]["text"], residence_area=area, min_score=minimum, max_score=maximum, average_score=average, house_manage_no=house_no, notice_no=notice_no, supply_type="일반공급", rank=1, selection_path="points", verification="official", source="cheongyak_competition", evidence_url=url, evidence_text=" / ".join(c["text"] for c in cells), evidence_location="#compitTbl · 1순위 당첨가점", document_hash=digest, observed_at=observed_at))
    return rows


async def collect_winning_scores(client: httpx.AsyncClient, key: str, house_no: str, notice_no: str) -> tuple[list[dict], str]:
    observed = datetime.now(timezone.utc).isoformat()
    url = f"https://www.applyhome.co.kr/ai/aia/selectAPTCompetitionPopup.do?houseManageNo={house_no}&pblancNo={notice_no}"
    api_error = False
    if key:
        try:
            rows = []
            for page in range(1, 21):
                body = await get_json(client, f"{API_BASE}/getAptLttotPblancScore", {"serviceKey": key, "cond[HOUSE_MANAGE_NO::EQ]": house_no, "cond[PBLANC_NO::EQ]": notice_no, "page": page, "perPage": 100, "returnType": "JSON"})
                if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                    raise FeedError("공식 당첨가점 API 응답 형식 오류")
                for raw in body["data"]:
                    if not isinstance(raw, dict):
                        raise FeedError("공식 당첨가점 API 응답 형식 오류")
                    if str(raw.get("HOUSE_MANAGE_NO")) != house_no or str(raw.get("PBLANC_NO")) != notice_no:
                        raise FeedError("공식 당첨가점 API 공고 식별이 일치하지 않습니다.")
                    area = AREA_BY_CODE.get(str(raw.get("RESIDE_SECD", "")).zfill(2), "unknown")
                    low, high, avg = (score(raw.get(k)) for k in ("LWET_SCORE", "TOP_SCORE", "AVRG_SCORE"))
                    if not raw.get("HOUSE_TY") or area == "unknown" or low is None or high is None or avg is None or not low <= avg <= high:
                        continue
                    evidence = {k: raw.get(k) for k in ("HOUSE_MANAGE_NO", "PBLANC_NO", "HOUSE_TY", "RESIDE_SECD", "LWET_SCORE", "TOP_SCORE", "AVRG_SCORE")}
                    document = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
                    rows.append(dict(unit_type=raw["HOUSE_TY"], residence_area=area, min_score=low, max_score=high, average_score=avg, house_manage_no=house_no, notice_no=notice_no, supply_type="일반공급", rank=1, selection_path="points", verification="official", source="cheongyak_competition", evidence_url=url, evidence_text=document, document_hash=hashlib.sha256(document.encode()).hexdigest(), evidence_location="getAptLttotPblancScore · HOUSE_TY / RESIDE_SECD", observed_at=observed))
                matched = integer(body.get("matchCount"))
                if len(body["data"]) < 100 or (matched is not None and page * 100 >= matched):
                    return rows, "success" if rows else "unpublished"
            raise FeedError("당첨가점 API 페이지 수가 한도를 초과했습니다.")
        except FeedError:
            api_error = True
    response = await client.get(url, timeout=30)
    response.raise_for_status()
    rows = parse_score_popup(response.text, url=url, house_no=house_no, notice_no=notice_no, observed_at=observed)
    return rows, "fallback" if rows and api_error else "success" if rows else "unpublished"


def record_winning_scores(session, notice_id: str, rows: list[dict], status: str, *, expected_version: int, criterion_date: str | None):
    current = session.get(Notice, notice_id)
    notice = lock_notice(session, current.source, current.external_id) if current else None
    if notice is None or notice.version != expected_version:
        return
    previous = [r for r in notice.rules if r.get("kind") == "winning_scores"]
    retained = [r for r in notice.rules if r.get("kind") != "winning_scores"]
    if status == "error":
        rows = [{**row, "collection_status": "error"} for r in previous for row in r.get("rows", [])]
    rows = [{**row, "criterion_date": criterion_date, "collection_status": status} for row in rows]
    notice.rules = [*retained, {"kind": "winning_scores", "effect": "metadata", "source": "cheongyak_competition", "verification": "official", "status": status, "observed_at": datetime.now(timezone.utc).isoformat(), "rows": rows}]
    session.flush()
