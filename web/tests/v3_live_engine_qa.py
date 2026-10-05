"""Read-only v3 integration QA against public notices and the current TS engine.

Run from any directory with Python 3.10+ after installing the web dependencies:
    python web/tests/v3_live_engine_qa.py

Only GET /api/notices/{id} is used. Fictional profiles live in a temporary Node
process; this script never reads browser profiles, credentials, or .env files.
The report contains decision labels and public source validity, never personal
inputs, rendered reason details, or a serialized fictional profile. Existing
production notices and the qualification engine are not modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
NOTICE_IDS = {
    "dongin": "46bcf351-feda-4a60-ab2d-2c29cbd2bc16",
    "gwangmyeong": "342f3968-02fd-4d2a-aa79-71baecedf9c4",
    "jamsil": "0458dfae-6269-4b94-b1fa-9e7034e805ee",
    "a6": "dabc205e-71fb-4ce9-b0c9-ac75e58f9872",
}
DEFAULT_NODE = Path("/home/seokj/.cache/ms-playwright-go/1.57.0/node")
ENGINE_FILES = ("types.ts", "qualification.ts", "eligibility.ts", "competition.ts", "ownership.ts", "regions.ts")


ENGINE_QA = r"""
import { readFileSync } from 'node:fs'
import { EMPTY_PROFILE } from '__SOURCE__/types.ts'
import { deriveRank, unitRankResults, applicantRegionEligibility, evaluateRule,
  exclusiveArea, criterionDate } from '__SOURCE__/qualification.ts'
import { evaluateEligibility, eligibilityCombinations } from '__SOURCE__/eligibility.ts'
import { residenceArea, resultCompetitionDecision, resultCompetitionRows,
  historicalCompetitionValid, competitionClosureProof } from '__SOURCE__/competition.ts'

const { notices, asOf } = JSON.parse(readFileSync(0, 'utf8'))
const now = Date.parse(asOf)
const checks = []
const snapshots = {}
function check(label, condition) {
  checks.push({ label, passed: !!condition })
}
function reasonSummary(reason) {
  return {
    status: reason.status, label: reason.label, category: reason.category || null,
    profileField: reason.profileField || null, criterionDate: reason.criterionDate || null,
    evidenceUrl: reason.evidenceUrl || null, evidenceTextPresent: !!reason.evidenceText,
  }
}
function rankSummary(result) {
  return { rank: result.rank, status: result.status, label: result.label,
    reasons: result.reasons.map(reasonSummary) }
}
function assessmentSummary(result) {
  return { status: result.status, reasons: result.reasons.map(reasonSummary) }
}
function unitSummary(notice, profile) {
  return unitRankResults(notice, profile).map(({ unitType, result }) => ({
    unitType, ...rankSummary(result),
  }))
}
function rankRules(notice) {
  return notice.rules.filter(rule => rule.purpose === 'first_rank' && rule.effect !== 'metadata')
}
function metadata(notice, kind) {
  return notice.rules.find(rule => rule.kind === kind && rule.effect === 'metadata' && rule.verification === 'official')
}
function rankCutoff(notice) {
  const rule = metadata(notice, 'rank_requirements') || rankRules(notice)[0]
  return criterionDate(rule, notice)
}
function profile(notice, overrides = {}) {
  return {
    ...EMPTY_PROFILE, children: [], ownershipFacts: [],
    region: '경기도', district: '화성시', regionCode: '41', districtCode: '41590',
    regionNeedsReview: false, movedInDate: '2010-01-01', districtMovedInDate: '2010-01-01',
    cityMovedInDate: '2010-01-01', dateOfBirth: '1990-01-01', householdSize: '1',
    isHouseholdHead: true, hasSpouse: false, familyOnRegister: false, householdScopeKnown: true,
    applicantOwnsHome: false, spouseOwnsHome: false, familyOwnsHome: false,
    ownershipFactsKnown: true, applicantPreviouslyOwnedHome: false,
    spousePreviouslyOwnedHome: false, familyPreviouslyOwnedHome: false,
    accountType: 'comprehensive', privateRankBaseDate: '2010-01-01',
    nationalRankBaseDate: '2010-01-01', accountConversionUnclear: false,
    privateDepositKrw: '6000000', privateDepositAsOfDate: rankCutoff(notice),
    privateDepositMaintained: true, nationalRecognizedPayments: '12',
    nationalPaymentsAsOfDate: rankCutoff(notice), previousWinning: false,
    restrictedFromApplying: false, specialWinning: false, militaryCurrentlyServing: false,
    ...overrides,
  }
}
function run(label, callback) {
  try { callback() } catch (error) {
    checks.push({ label: `${label}: engine execution`, passed: false,
      errorType: error?.name || 'Error' })
  }
}

run('Public official metadata', () => {
  for (const [key, notice] of Object.entries(notices)) {
    check(`${key}: the expected retained public notice is returned`, notice.id === __IDS__[key])
    check(`${key}: housing classification is supported by official evidence`,
      notice.housing_kind_evidence?.verification === 'official' &&
      !!notice.housing_kind_evidence?.evidence_url && !!notice.housing_kind_evidence?.evidence_text)
    if (key === 'jamsil') continue
    const coverage = metadata(notice, 'rank_requirements')
    const rules = rankRules(notice)
    check(`${key}: complete official rank coverage matches the current document`,
      coverage?.complete === true && !!notice.document_hash &&
      coverage.document_hash === notice.document_hash &&
      Array.isArray(coverage.required_kinds) &&
      coverage.required_kinds.every(kind => rules.some(rule => rule.kind === kind &&
        rule.verification === 'official' && rule.document_hash === notice.document_hash &&
        !!rule.evidence_url && !!rule.evidence_text)))
  }
})

run('Dongin rank and region', () => {
  const notice = notices.dongin, person = profile(notice)
  const units = unitSummary(notice, person)
  const scope = applicantRegionEligibility(notice, person)
  const combinations = eligibilityCombinations(notice, person)
  snapshots.dongin = { rank: rankSummary(deriveRank(notice, person)), units,
    applicantScope: scope ? reasonSummary(scope) : null, residenceArea: residenceArea(notice, person),
    supplies: combinations.map(combo => ({ unitType: combo.unitType, supplyType: combo.supplyType,
      ...assessmentSummary(combo.result) })) }
  check('Dongin: all four real unit types meet official private first rank requirements',
    units.length === 4 && units.every(unit => unit.rank === 'first' && unit.status === 'possible'))
  check('Dongin: rank remains separate from the failing application region',
    deriveRank(notice, person).rank === 'first' && scope?.status === 'fail')
  check('Dongin: the outside-region profile is not labelled as an ordinary other-region candidate',
    residenceArea(notice, person) === 'unknown')
  check('Dongin: every offered supply assessment carries the official region mismatch',
    combinations.length > 0 && combinations.every(combo => combo.result.status === 'mismatch' &&
      combo.result.reasons.some(reason => reason.label === scope.label && reason.status === 'fail')))
})

run('Gwangmyeong rank and region', () => {
  const notice = notices.gwangmyeong, person = profile(notice)
  const units = unitSummary(notice, person)
  const scope = applicantRegionEligibility(notice, person)
  snapshots.gwangmyeong = { rank: rankSummary(deriveRank(notice, person)), units,
    applicantScope: scope ? reasonSummary(scope) : null, residenceArea: residenceArea(notice, person) }
  check('Gwangmyeong: all seven real unit types meet official private first rank requirements',
    units.length === 7 && units.every(unit => unit.rank === 'first' && unit.status === 'possible'))
  check('Gwangmyeong: the permitted capital-region profile passes the official applicant scope',
    scope?.status === 'pass' && residenceArea(notice, person) === 'other')
  const required = metadata(notice, 'rank_requirements')?.required_kinds || []
  check('Gwangmyeong: additional household and winning-history rank conditions are covered',
    ['household_head', 'ownership_count_max', 'previous_winning'].every(kind => required.includes(kind)))
})

run('A6 national rank', () => {
  const notice = notices.a6, person = profile(notice)
  const sufficient = deriveRank(notice, person), units = unitSummary(notice, person)
  const insufficient = deriveRank(notice, { ...person, nationalRecognizedPayments: '9' })
  const missingDate = deriveRank(notice, { ...person, nationalPaymentsAsOfDate: '' })
  const futureDate = deriveRank(notice, { ...person, nationalPaymentsAsOfDate: '2099-01-01' })
  snapshots.a6 = { sufficient: rankSummary(sufficient), units,
    insufficient: rankSummary(insufficient), missingRecognitionDate: rankSummary(missingDate),
    recognitionDateAfterCutoff: rankSummary(futureDate) }
  check('A6: verified national requirements produce first rank for sufficient recognized payments',
    notice.housing_kind === 'national' && sufficient.rank === 'first' && sufficient.status === 'possible')
  check('A6: every actual priced unit gets the same national rank outcome',
    units.length === notice.prices.length && units.length > 0 && units.every(unit => unit.rank === 'first'))
  check('A6: insufficient recognized payments produce a distinct mismatch',
    insufficient.rank === 'unknown' && insufficient.status === 'mismatch' &&
    insufficient.reasons.some(reason => reason.status === 'fail' && reason.label === '국민주택 납입인정횟수'))
  check('A6: a missing recognition date remains a review',
    missingDate.rank === 'unknown' && missingDate.reasons.some(reason => reason.profileField === 'nationalPaymentsAsOfDate'))
  check('A6: a recognition date after the official cutoff cannot establish historical payments',
    futureDate.rank === 'unknown' && futureDate.reasons.some(reason => reason.profileField === 'nationalPaymentsAsOfDate'))
})

run('Jamsil non-rank applicability', () => {
  const notice = notices.jamsil
  const untouched = { ...EMPTY_PROFILE, children: [], ownershipFacts: [] }
  const before = JSON.stringify(untouched), rank = deriveRank(notice, untouched)
  const qualification = evaluateEligibility(notice, untouched)
  snapshots.jamsil = { rank: rankSummary(rank), qualification: assessmentSummary(qualification),
    accountRequired: notice.rank_applicability?.account_required,
    rankEvidenceOfficial: notice.rank_applicability?.verification === 'official',
    noInputMutation: JSON.stringify(untouched) === before }
  check('Jamsil: official officetel applicability produces no apartment rank',
    notice.category === 'officetel' && rank.rank === 'not_applicable' && rank.status === 'possible')
  check('Jamsil: no subscription account is required by the official applicability',
    notice.rank_applicability?.account_required === false &&
    rank.reasons.some(reason => reason.requirement === '청약통장 불필요'))
  check('Jamsil: empty local inputs do not request invented rank base or balance dates',
    !rank.reasons.some(reason => ['privateRankBaseDate', 'nationalRankBaseDate',
      'privateDepositAsOfDate', 'nationalPaymentsAsOfDate', 'accountType'].includes(reason.profileField)))
  check('Jamsil: local engine evaluation leaves the empty fictional profile untouched',
    JSON.stringify(untouched) === before && !untouched.privateRankBaseDate && !untouched.nationalRankBaseDate)
})

run('Official exclusive area thresholds', () => {
  const evidence = []
  for (const key of ['dongin', 'gwangmyeong']) {
    const notice = notices[key], person = profile(notice, { privateDepositKrw: '2000000' })
    const deposit = rankRules(notice).find(rule => rule.kind === 'deposit_min_krw')
    const account = rankRules(notice).find(rule => rule.kind === 'account_type')
    check(`${key}: real official supply areas cross the exclusive-area threshold`,
      notice.prices.some(price => price.area_sqm > 85 && exclusiveArea(price) <= 85))
    for (const price of notice.prices) {
      const area = exclusiveArea(price)
      const amount = evaluateRule(deposit, person, notice, price.unit_type)
      const installment = evaluateRule(account, { ...person, accountType: 'installment' }, notice, price.unit_type)
      check(`${key} ${price.unit_type}: deposit tier uses the official exclusive area`,
        area === price.exclusive_area_sqm && area > 0 && area <= 85 && amount.status === 'pass' &&
        amount.requirement?.includes(`전용면적 ${area}㎡`) && amount.requirement?.endsWith('2,000,000원'))
      check(`${key} ${price.unit_type}: installment area limit uses the official exclusive area`,
        installment.status === 'pass')
      evidence.push({ notice: key, unitType: price.unit_type, exclusiveAreaVerified: area === price.exclusive_area_sqm,
        supplyAreaDiffers: price.area_sqm !== area, deposit: reasonSummary(amount), installment: reasonSummary(installment) })
    }
  }
  const unknown = notices.a6.prices.filter(price => price.exclusive_area_sqm == null && price.area_basis !== 'exclusive')
  check('A6: missing official exclusive areas never fall back to supply area',
    unknown.every(price => exclusiveArea(price) === null))
  snapshots.areaThresholds = { units: evidence, unverifiedExclusiveAreaUnitTypes: unknown.map(price => price.unit_type) }
})

run('Gwangmyeong historical result filtering', () => {
  const notice = notices.gwangmyeong, person = profile(notice)
  const before = JSON.stringify(notice)
  const decision = resultCompetitionDecision(notice, person, undefined, now)
  const visible = resultCompetitionRows(notice, decision, true)
  const restored = resultCompetitionRows(notice, decision, false)
  const proof = competitionClosureProof(notice, '059.9742A', 'results', now)
  const valid = historicalCompetitionValid(notice)
  const beforeUnits = new Set(notice.prices.map(price => price.unit_type))
  snapshots.gwangmyeongResults = {
    proofValid: valid, sourceProofInvalidated: notice.competition?.proof_invalidated === true,
    area: decision.area, hidden: decision.hidden, closedUnitTypes: decision.closedUnits,
    visibleUnitTypes: [...new Set(visible.map(row => row.unit_type))],
    visibleRows: visible.length, restoredRows: restored.length, priceRows: notice.prices.length,
    closureProofs: (decision.closureProofs || []).map(item => ({ unitType: item.unitType,
      kind: item.kind, competitionEvidenceUrl: item.competitionEvidenceUrl,
      competitionEvidenceTextPresent: !!item.competitionEvidenceText,
      allocationEvidenceUrl: item.allocationEvidenceUrl || null,
      allocationEvidenceTextPresent: !!item.allocationEvidenceText })),
    retainedTargetRate: visible.filter(row => row.unit_type === '059.7421B' && row.competition_rate === '1.10')
      .map(row => ({ unitType: row.unit_type, rank: row.rank, rate: row.competition_rate,
        resultStatus: row.result_status, verification: row.verification, evidenceUrl: row.evidence_url })),
  }
  check('Gwangmyeong results: 59A hiding follows current historical proof validity',
    valid ? !!proof && !visible.some(row => row.unit_type === '059.9742A')
      : !proof && visible.some(row => row.unit_type === '059.9742A'))
  check('Gwangmyeong results: the actual 59B first-rank 1.10 result remains visible',
    visible.some(row => row.unit_type === '059.7421B' && row.rank === 1 &&
      row.competition_rate === '1.10' && row.verification === 'official'))
  check('Gwangmyeong results: a remaining unit keeps the whole notice visible', !decision.hidden)
  check('Gwangmyeong results: restoring rows recovers every collected official result',
    restored.length === notice.competitions.filter(row => row.verification === 'official').length)
  check('Gwangmyeong results: all seven public prices survive the competition filter',
    notice.prices.length === 7 && new Set(notice.prices.map(price => price.unit_type)).size === 7 &&
    notice.prices.every(price => beforeUnits.has(price.unit_type)) && JSON.stringify(notice) === before)
})

console.log(JSON.stringify({ checks, snapshots }))
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_snapshot(row: dict) -> dict:
    """Store public provenance, omitting full document quotes and revisions."""
    selected = [rule for rule in row.get("rules", []) if rule.get("purpose") == "first_rank"
                or rule.get("kind") in {"applicant_regions", "rank_requirements", "regional_allocation", "rank_applicability"}]
    return {
        "id": row["id"], "title": row["title"], "version": row["version"],
        "housingKind": row.get("housing_kind"), "documentHash": row.get("document_hash"),
        "officialUrl": row.get("official_url"), "priceRows": len(row.get("prices", [])),
        "rankApplicability": row.get("rank_applicability"),
        "rules": [{
            "kind": rule["kind"], "verification": rule.get("verification"),
            "source": rule.get("source"), "parserVersion": rule.get("parser_version"),
            "criterionDate": rule.get("criterion_date"), "scope": rule.get("scope"),
            "evidenceUrl": rule.get("evidence_url"), "evidenceTextPresent": bool(rule.get("evidence_text")),
            "documentHash": rule.get("document_hash"),
            "matchesCurrentDocument": rule.get("document_hash") == row.get("document_hash") if rule.get("document_hash") else None,
            **({"complete": rule["complete"], "requiredKinds": rule.get("required_kinds")} if "complete" in rule else {}),
        } for rule in selected],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default=os.environ.get("CHEONGYAK_QA_BASE", "http://localhost:8080"))
    parser.add_argument("--node", default=os.environ.get("CHEONGYAK_QA_NODE") or shutil.which("node") or str(DEFAULT_NODE))
    parser.add_argument("--as-of", help="ISO timestamp for historical evidence validity; defaults to current UTC")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/qa/v3-live-engine-2026-10-04.json")
    args = parser.parse_args()
    parsed_base = urlsplit(args.base)
    if parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc or parsed_base.username or parsed_base.password:
        parser.error("--base must be an HTTP(S) origin without credentials")
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        parser.error("--as-of must include a timezone")
    report = {
        "base": args.base.rstrip("/"), "asOf": as_of.astimezone(timezone.utc).isoformat(),
        "readOnly": {"publicGetOnly": True, "browserProfileRead": False,
                     "fictionalProfilesLocalOnly": True, "profileValuesInReport": False},
        "engine": {"sourceHashes": {name: sha256(ROOT / "web/src" / name) for name in ENGINE_FILES}},
        "requests": [], "publicNotices": {}, "checks": [], "snapshots": {},
    }
    try:
        notices = {}
        for key, identifier in NOTICE_IDS.items():
            path = f"/api/notices/{identifier}"
            request = Request(report["base"] + path, headers={"Accept": "application/json"}, method="GET")
            with urlopen(request, timeout=30) as response:
                row = json.load(response)
                report["requests"].append({"method": "GET", "path": path, "status": response.status})
            notices[key] = row
            report["publicNotices"][key] = source_snapshot(row)
        source = ENGINE_QA.replace("__SOURCE__", str(ROOT / "web/src")).replace("__IDS__", json.dumps(NOTICE_IDS))
        with tempfile.TemporaryDirectory(prefix="cheongyak-live-engine-qa-") as folder:
            entry, bundle = Path(folder) / "qa.ts", Path(folder) / "qa.mjs"
            entry.write_text(source, encoding="utf-8")
            build = subprocess.run([str(ROOT / "web/node_modules/esbuild/bin/esbuild"), str(entry),
                                    "--bundle", "--platform=node", "--format=esm", f"--outfile={bundle}", "--log-level=error"],
                                   capture_output=True, text=True, timeout=60)
            if build.returncode:
                raise RuntimeError("Current TypeScript engine could not be bundled with esbuild")
            report["engine"]["bundleHash"] = sha256(bundle)
            result = subprocess.run([args.node, str(bundle)],
                                    input=json.dumps({"notices": notices, "asOf": report["asOf"]}),
                                    capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise RuntimeError("Bundled TypeScript engine QA did not finish successfully")
            tested = json.loads(result.stdout)
            report["checks"].extend(tested["checks"])
            report["snapshots"] = tested["snapshots"]
        report["checks"].append({"label": "All public requests are GETs without profiles or request bodies",
                                  "passed": len(report["requests"]) == len(NOTICE_IDS) and
                                  all(request["method"] == "GET" for request in report["requests"])})
        # Source edits during a run make the captured source hash ambiguous.
        report["checks"].append({"label": "Engine source hashes remain stable during the integration run",
                                  "passed": all(sha256(ROOT / "web/src" / name) == digest
                                                for name, digest in report["engine"]["sourceHashes"].items())})
    except Exception as error:
        # Do not dump subprocess stderr, response payloads or local inputs.
        report["checks"].append({"label": "Read-only live engine QA completed", "passed": False,
                                  "errorType": type(error).__name__})
    report["passed"] = sum(check["passed"] for check in report["checks"])
    report["failed"] = sum(not check["passed"] for check in report["checks"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "failed": report["failed"],
                      "output": str(args.output.resolve()),
                      "failedChecks": [check["label"] for check in report["checks"] if not check["passed"]]}, ensure_ascii=False))
    return int(report["failed"] > 0)


if __name__ == "__main__":
    sys.exit(main())
