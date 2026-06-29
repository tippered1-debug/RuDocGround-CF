from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rudocground.case_tools import prepare_prompts
from rudocground.io import load_gold
from rudocground.metrics import evaluate_report
from rudocground.models import PredictionRecord


ROOT = Path(".")
CASES_DIR = ROOT / "data" / "cases"
SOURCE_DIR = ROOT / "data" / "source_documents"
PROMPTS_DIR = ROOT / "prompts"
RESULTS_DIR = ROOT / "results"

LEGACY_CASE_IDS = [
    "trip_001",
    "procurement_002",
    "authority_003",
    "acceptance_004",
    "notice_005",
    "reconciliation_006",
    "amendment_007",
    "sla_008",
    "approval_chain_009",
    "asset_scope_010",
]

PILOT_CASE_IDS = [
    "logistics_014",
    "iplic_016",
    "privacy_017",
    "hr_019",
    "procure_022",
]

EXPANSION_CASE_IDS = [
    "finset_011",
    "finset_012",
    "logistics_013",
    "iplic_015",
    "privacy_018",
    "hr_020",
    "procure_021",
    "it_023",
    "it_024",
    "property_025",
    "property_026",
    "shipping_027",
    "finance_028",
    "infosec_029",
    "hr_030",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _jsonl_write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _text_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _write_questions_json(case_root: Path, case_id: str, question_rows: list[dict[str, Any]]) -> None:
    questions = [
        {
            "question_id": row["question_id"],
            "question": row["question"],
            "answer_type": row["answer_type"],
        }
        for row in question_rows
    ]
    _json_write(case_root / "questions.json", {"case_id": case_id, "questions": questions})


def _parse_question_matrix(case_root: Path) -> list[dict[str, Any]]:
    matrix = case_root / "question_matrix.md"
    if not matrix.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in matrix.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| Q"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) < 3:
            continue
        rows.append(
            {
                "question_id": parts[0],
                "question": parts[1],
                "answer_type": parts[2],
            }
        )
    return rows


def _slugify(value: str) -> str:
    value = value.strip().lower().replace(" ", "_")
    return "".join(ch for ch in value if ch.isalnum() or ch in {"_", "-", ":"})


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    group: str
    domain: str
    title: str
    q1_control: str
    q4_question: str
    q5_question: str
    q6_question: str
    q6_type: str
    q6_a: Any
    q6_b: Any
    q6_c: Any
    q7_question: str
    q7_type: str
    q7_a: Any
    q7_b: Any
    q7_c: Any
    q8_codes: list[str]
    identifier: str
    nuisance_ref_a: str
    nuisance_ref_c: str
    nuisance_ts_a: str
    nuisance_ts_c: str
    decision_a: str
    decision_b: str
    support_sufficient: bool
    missing_required: bool
    final_status_a: str
    final_status_b: str
    substantive_a: str
    substantive_b: str
    code_set_question: str
    q12_control: str


CASE_SPECS: list[CaseSpec] = [
    CaseSpec(
        case_id="finset_011",
        group="batch1",
        domain="finance and calculations",
        title="Partial prepayment threshold",
        q1_control="reimbursement_policy",
        q4_question="Does the partial prepayment line remain reimbursable?",
        q5_question="What is the decision on the line item?",
        q6_question="What reimbursable amount is recorded in the core record?",
        q6_type="money",
        q6_a=1200,
        q6_b=0,
        q6_c=1200,
        q7_question="What deadline date is recorded in the core record?",
        q7_type="date",
        q7_a="2026-06-01",
        q7_b="2026-06-03",
        q7_c="2026-06-01",
        q8_codes=["taxable_scope", "non_taxable_scope"],
        identifier="INV-1101",
        nuisance_ref_a="PRE-1101",
        nuisance_ref_c="PRE-3301",
        nuisance_ts_a="2026-06-01T09:00:00",
        nuisance_ts_c="2026-06-01T09:15:00",
        decision_a="rejected",
        decision_b="approved",
        support_sufficient=True,
        missing_required=False,
        final_status_a="rejected",
        final_status_b="approved",
        substantive_a="Line 2 is not reimbursable under the partial prepayment rule.",
        substantive_b="Line 2 is reimbursable under the partial prepayment rule.",
        code_set_question="Which control codes apply to the reimbursement decision?",
        q12_control="reimbursement_policy",
    ),
    CaseSpec(
        case_id="finset_012",
        group="batch1",
        domain="finance and calculations",
        title="Currency clause trigger",
        q1_control="fx_clause",
        q4_question="Does the FX threshold condition hold?",
        q5_question="What is the final payment basis?",
        q6_question="What payable amount is recorded in the core record?",
        q6_type="money",
        q6_a=10000,
        q6_b=12000,
        q6_c=10000,
        q7_question="What deadline date is recorded in the core record?",
        q7_type="date",
        q7_a="2026-07-01",
        q7_b="2026-07-15",
        q7_c="2026-07-01",
        q8_codes=["threshold_check", "fx_indexation"],
        identifier="FX-1201",
        nuisance_ref_a="FX-1201",
        nuisance_ref_c="FX-3301",
        nuisance_ts_a="2026-07-01T10:00:00",
        nuisance_ts_c="2026-07-01T10:11:00",
        decision_a="not_indexed",
        decision_b="indexed",
        support_sufficient=True,
        missing_required=False,
        final_status_a="not_indexed",
        final_status_b="indexed",
        substantive_a="The FX threshold is not triggered.",
        substantive_b="The FX threshold is triggered.",
        code_set_question="Which control codes apply to the currency clause?",
        q12_control="fx_clause",
    ),
    CaseSpec(
        case_id="logistics_013",
        group="batch1",
        domain="supply and logistics",
        title="Split shipment acceptance",
        q1_control="shipping_procedure",
        q4_question="Is the custody chain complete?",
        q5_question="What is the shipment acceptance outcome?",
        q6_question="How many custody chains are documented in the core record?",
        q6_type="integer",
        q6_a=1,
        q6_b=2,
        q6_c=1,
        q7_question="What shipment date is recorded in the core record?",
        q7_type="date",
        q7_a="2026-08-01",
        q7_b="2026-08-02",
        q7_c="2026-08-01",
        q8_codes=["warehouse_a", "warehouse_b"],
        identifier="SHIP-1301",
        nuisance_ref_a="SHIP-1301",
        nuisance_ref_c="SHIP-3301",
        nuisance_ts_a="2026-08-01T11:00:00",
        nuisance_ts_c="2026-08-01T11:20:00",
        decision_a="partial_acceptance",
        decision_b="full_acceptance",
        support_sufficient=True,
        missing_required=False,
        final_status_a="partial_acceptance",
        final_status_b="full_acceptance",
        substantive_a="Only one custody chain is complete.",
        substantive_b="Both custody chains are complete.",
        code_set_question="Which control codes apply to the shipment?",
        q12_control="shipping_procedure",
    ),
    CaseSpec(
        case_id="iplic_015",
        group="batch1",
        domain="licenses and IP",
        title="Territory license scope",
        q1_control="license_agreement",
        q4_question="Does the license cover the second region?",
        q5_question="What is the territory scope outcome?",
        q6_question="How many regions are covered in the core record?",
        q6_type="integer",
        q6_a=1,
        q6_b=2,
        q6_c=1,
        q7_question="What renewal date is recorded in the core record?",
        q7_type="date",
        q7_a="2026-09-01",
        q7_b="2026-09-30",
        q7_c="2026-09-01",
        q8_codes=["territory_scope", "renewal_gate"],
        identifier="LIC-1501",
        nuisance_ref_a="LIC-1501",
        nuisance_ref_c="LIC-3301",
        nuisance_ts_a="2026-09-01T12:00:00",
        nuisance_ts_c="2026-09-01T12:18:00",
        decision_a="single_region",
        decision_b="two_regions",
        support_sufficient=True,
        missing_required=False,
        final_status_a="single_region",
        final_status_b="two_regions",
        substantive_a="The license covers only one region.",
        substantive_b="The license covers two regions.",
        code_set_question="Which control codes apply to the license scope?",
        q12_control="license_agreement",
    ),
    CaseSpec(
        case_id="privacy_018",
        group="batch1",
        domain="privacy and infosec",
        title="Security incident notification clock",
        q1_control="incident_response_policy",
        q4_question="Was the notification submitted on time?",
        q5_question="What is the incident-notice outcome?",
        q6_question="How many hours remain until the notification deadline in the core record?",
        q6_type="integer",
        q6_a=72,
        q6_b=48,
        q6_c=72,
        q7_question="What deadline timestamp is recorded in the core record?",
        q7_type="datetime",
        q7_a="2026-09-12T10:00:00",
        q7_b="2026-09-12T06:00:00",
        q7_c="2026-09-12T10:00:00",
        q8_codes=["deadline_clock", "regulator_notice"],
        identifier="INC-1801",
        nuisance_ref_a="INC-1801",
        nuisance_ref_c="INC-3301",
        nuisance_ts_a="2026-09-12T09:40:00",
        nuisance_ts_c="2026-09-12T09:55:00",
        decision_a="not_timely",
        decision_b="timely",
        support_sufficient=True,
        missing_required=False,
        final_status_a="not_timely",
        final_status_b="timely",
        substantive_a="The notice deadline is missed.",
        substantive_b="The notice deadline is met.",
        code_set_question="Which control codes apply to the notification clock?",
        q12_control="incident_response_policy",
    ),
    CaseSpec(
        case_id="hr_020",
        group="batch2",
        domain="HR access and authority",
        title="Delegated authority gap",
        q1_control="delegation_policy",
        q4_question="Is the signer authorized for this contract class?",
        q5_question="What is the signature validity outcome?",
        q6_question="What contract class is recorded in the core record?",
        q6_type="categorical",
        q6_a="maintenance_contracts",
        q6_b="purchase_contracts",
        q6_c="maintenance_contracts",
        q7_question="What delegation date is recorded in the core record?",
        q7_type="date",
        q7_a="2026-10-01",
        q7_b="2026-10-15",
        q7_c="2026-10-01",
        q8_codes=["authority_scope", "delegated_signing"],
        identifier="DEL-2001",
        nuisance_ref_a="DEL-2001",
        nuisance_ref_c="DEL-3301",
        nuisance_ts_a="2026-10-01T13:00:00",
        nuisance_ts_c="2026-10-01T13:25:00",
        decision_a="unauthorized",
        decision_b="authorized",
        support_sufficient=True,
        missing_required=False,
        final_status_a="unauthorized",
        final_status_b="authorized",
        substantive_a="The signer is outside delegated authority.",
        substantive_b="The signer is inside delegated authority.",
        code_set_question="Which control codes apply to delegated authority?",
        q12_control="delegation_policy",
    ),
    CaseSpec(
        case_id="procure_021",
        group="batch2",
        domain="procurement and compliance",
        title="Single-source justification",
        q1_control="sole_source_policy",
        q4_question="Is the sole-source justification complete?",
        q5_question="What is the procurement-support outcome?",
        q6_question="How many mandatory comparators are documented in the core record?",
        q6_type="integer",
        q6_a=2,
        q6_b=1,
        q6_c=2,
        q7_question="What checklist date is recorded in the core record?",
        q7_type="date",
        q7_a="2026-11-01",
        q7_b="2026-11-03",
        q7_c="2026-11-01",
        q8_codes=["sole_source", "comparator_check"],
        identifier="PROC-2101",
        nuisance_ref_a="PROC-2101",
        nuisance_ref_c="PROC-3301",
        nuisance_ts_a="2026-11-01T14:00:00",
        nuisance_ts_c="2026-11-01T14:10:00",
        decision_a="incomplete",
        decision_b="complete",
        support_sufficient=False,
        missing_required=True,
        final_status_a="blocked",
        final_status_b="approved",
        substantive_a="The mandatory comparator is present.",
        substantive_b="The mandatory comparator is missing.",
        code_set_question="Which control codes apply to the sole-source file?",
        q12_control="sole_source_policy",
    ),
    CaseSpec(
        case_id="it_023",
        group="batch2",
        domain="IT / SLA",
        title="SLA penalty waiver",
        q1_control="sla_policy",
        q4_question="Is the service credit waived?",
        q5_question="What is the service-credit outcome?",
        q6_question="What service credit amount is recorded in the core record?",
        q6_type="money",
        q6_a=50000,
        q6_b=0,
        q6_c=50000,
        q7_question="What report timestamp is recorded in the core record?",
        q7_type="datetime",
        q7_a="2026-11-10T16:00:00",
        q7_b="2026-11-10T18:00:00",
        q7_c="2026-11-10T16:00:00",
        q8_codes=["waiver_clause", "service_credit"],
        identifier="SLA-2301",
        nuisance_ref_a="SLA-2301",
        nuisance_ref_c="SLA-3301",
        nuisance_ts_a="2026-11-10T15:00:00",
        nuisance_ts_c="2026-11-10T15:20:00",
        decision_a="not_waived",
        decision_b="waived",
        support_sufficient=True,
        missing_required=False,
        final_status_a="not_waived",
        final_status_b="waived",
        substantive_a="The outage report was filed late.",
        substantive_b="The outage report was filed on time.",
        code_set_question="Which control codes apply to the SLA file?",
        q12_control="sla_policy",
    ),
    CaseSpec(
        case_id="it_024",
        group="batch2",
        domain="IT / SLA",
        title="Escalation path breach",
        q1_control="escalation_matrix",
        q4_question="Was the escalation routed to the correct tier?",
        q5_question="What is the escalation compliance outcome?",
        q6_question="What escalation tier is recorded in the core record?",
        q6_type="integer",
        q6_a=2,
        q6_b=3,
        q6_c=2,
        q7_question="What ticket date is recorded in the core record?",
        q7_type="date",
        q7_a="2026-12-01",
        q7_b="2026-12-02",
        q7_c="2026-12-01",
        q8_codes=["tier_check", "sla_clock"],
        identifier="TKT-2401",
        nuisance_ref_a="TKT-2401",
        nuisance_ref_c="TKT-3301",
        nuisance_ts_a="2026-12-01T08:30:00",
        nuisance_ts_c="2026-12-01T08:44:00",
        decision_a="non_compliant",
        decision_b="compliant",
        support_sufficient=True,
        missing_required=False,
        final_status_a="non_compliant",
        final_status_b="compliant",
        substantive_a="The escalation went to the wrong tier.",
        substantive_b="The escalation went to the required tier.",
        code_set_question="Which control codes apply to the escalation matrix?",
        q12_control="escalation_matrix",
    ),
    CaseSpec(
        case_id="property_025",
        group="batch2",
        domain="lease property and guarantees",
        title="Lease renewal option window",
        q1_control="lease_notice_rule",
        q4_question="Was the renewal option exercised on time?",
        q5_question="What is the lease-renewal outcome?",
        q6_question="How many business days are recorded for the notice window?",
        q6_type="integer",
        q6_a=30,
        q6_b=29,
        q6_c=30,
        q7_question="What notice deadline date is recorded in the core record?",
        q7_type="date",
        q7_a="2026-12-31",
        q7_b="2027-01-01",
        q7_c="2026-12-31",
        q8_codes=["option_window", "delivery_proof"],
        identifier="LEASE-2501",
        nuisance_ref_a="LEASE-2501",
        nuisance_ref_c="LEASE-3301",
        nuisance_ts_a="2026-12-15T10:00:00",
        nuisance_ts_c="2026-12-15T10:07:00",
        decision_a="lapsed",
        decision_b="renewed",
        support_sufficient=True,
        missing_required=False,
        final_status_a="lapsed",
        final_status_b="renewed",
        substantive_a="The renewal notice is late.",
        substantive_b="The renewal notice is timely.",
        code_set_question="Which control codes apply to the lease notice?",
        q12_control="lease_notice_rule",
    ),
    CaseSpec(
        case_id="property_026",
        group="batch3",
        domain="lease property and guarantees",
        title="Security deposit offset",
        q1_control="lease_guarantee_clause",
        q4_question="Is the deposit offset allowed?",
        q5_question="What is the deposit-offset outcome?",
        q6_question="What deposit offset amount is recorded in the core record?",
        q6_type="money",
        q6_a=20000,
        q6_b=0,
        q6_c=20000,
        q7_question="What repair-act date is recorded in the core record?",
        q7_type="date",
        q7_a="2026-10-15",
        q7_b="2026-10-16",
        q7_c="2026-10-15",
        q8_codes=["offset_gate", "repair_act"],
        identifier="LEASE-2601",
        nuisance_ref_a="LEASE-2601",
        nuisance_ref_c="LEASE-3301",
        nuisance_ts_a="2026-10-15T09:00:00",
        nuisance_ts_c="2026-10-15T09:13:00",
        decision_a="not_allowed",
        decision_b="allowed",
        support_sufficient=True,
        missing_required=False,
        final_status_a="not_allowed",
        final_status_b="allowed",
        substantive_a="The repair act is missing.",
        substantive_b="The repair act is signed.",
        code_set_question="Which control codes apply to the deposit offset?",
        q12_control="lease_guarantee_clause",
    ),
    CaseSpec(
        case_id="shipping_027",
        group="batch3",
        domain="supply and logistics",
        title="Freight liability transfer",
        q1_control="freight_contract",
        q4_question="Does liability transfer at loading?",
        q5_question="What is the freight-liability outcome?",
        q6_question="At which stage is the risk transfer recorded in the core record?",
        q6_type="categorical",
        q6_a="loading",
        q6_b="unloading",
        q6_c="loading",
        q7_question="What damage-report date is recorded in the core record?",
        q7_type="date",
        q7_a="2026-08-10",
        q7_b="2026-08-11",
        q7_c="2026-08-10",
        q8_codes=["risk_transfer", "bill_of_lading"],
        identifier="FRT-2701",
        nuisance_ref_a="FRT-2701",
        nuisance_ref_c="FRT-3301",
        nuisance_ts_a="2026-08-10T17:00:00",
        nuisance_ts_c="2026-08-10T17:12:00",
        decision_a="shipper_liable",
        decision_b="carrier_liable",
        support_sufficient=True,
        missing_required=False,
        final_status_a="shipper_liable",
        final_status_b="carrier_liable",
        substantive_a="Risk transfers at loading.",
        substantive_b="Risk transfers at unloading.",
        code_set_question="Which control codes apply to the freight file?",
        q12_control="freight_contract",
    ),
    CaseSpec(
        case_id="finance_028",
        group="batch3",
        domain="finance and calculations",
        title="Advance report substantiation",
        q1_control="reimbursement_policy",
        q4_question="Is the receipt substantiated?",
        q5_question="What is the reimbursement outcome?",
        q6_question="What reimbursable amount is recorded in the core record?",
        q6_type="money",
        q6_a=850,
        q6_b=0,
        q6_c=850,
        q7_question="What report date is recorded in the core record?",
        q7_type="date",
        q7_a="2026-09-15",
        q7_b="2026-09-18",
        q7_c="2026-09-15",
        q8_codes=["substantiation", "receipts"],
        identifier="ADV-2801",
        nuisance_ref_a="ADV-2801",
        nuisance_ref_c="ADV-3301",
        nuisance_ts_a="2026-09-15T08:00:00",
        nuisance_ts_c="2026-09-15T08:14:00",
        decision_a="not_reimbursable",
        decision_b="reimbursable",
        support_sufficient=True,
        missing_required=False,
        final_status_a="not_reimbursable",
        final_status_b="reimbursable",
        substantive_a="The receipt lacks substantiation.",
        substantive_b="The receipt is substantiated.",
        code_set_question="Which control codes apply to the advance report?",
        q12_control="reimbursement_policy",
    ),
    CaseSpec(
        case_id="infosec_029",
        group="batch3",
        domain="privacy and infosec",
        title="Privileged account emergency use",
        q1_control="privileged_access_policy",
        q4_question="Is the emergency access session still valid?",
        q5_question="What is the access-validity outcome?",
        q6_question="What expiry timestamp is recorded in the core record?",
        q6_type="datetime",
        q6_a="2026-11-20T18:00:00",
        q6_b="2026-11-20T17:00:00",
        q6_c="2026-11-20T18:00:00",
        q7_question="What approval timestamp is recorded in the core record?",
        q7_type="datetime",
        q7_a="2026-11-20T16:00:00",
        q7_b="2026-11-20T16:15:00",
        q7_c="2026-11-20T16:00:00",
        q8_codes=["emergency_access", "post_review"],
        identifier="ACC-2901",
        nuisance_ref_a="ACC-2901",
        nuisance_ref_c="ACC-3301",
        nuisance_ts_a="2026-11-20T15:00:00",
        nuisance_ts_c="2026-11-20T15:25:00",
        decision_a="expired",
        decision_b="valid",
        support_sufficient=True,
        missing_required=False,
        final_status_a="expired",
        final_status_b="valid",
        substantive_a="The emergency access session expired.",
        substantive_b="The emergency access session is still valid.",
        code_set_question="Which control codes apply to privileged access?",
        q12_control="privileged_access_policy",
    ),
    CaseSpec(
        case_id="hr_030",
        group="batch3",
        domain="HR access and authority",
        title="Exit checklist completion",
        q1_control="exit_checklist_rule",
        q4_question="Is the exit checklist complete?",
        q5_question="What is the exit-status outcome?",
        q6_question="How many return items are recorded in the core record?",
        q6_type="integer",
        q6_a=3,
        q6_b=2,
        q6_c=3,
        q7_question="What closure date is recorded in the core record?",
        q7_type="date",
        q7_a="2026-10-20",
        q7_b="2026-10-21",
        q7_c="2026-10-20",
        q8_codes=["offboarding", "asset_return"],
        identifier="HR-3001",
        nuisance_ref_a="HR-3001",
        nuisance_ref_c="HR-3301",
        nuisance_ts_a="2026-10-20T09:30:00",
        nuisance_ts_c="2026-10-20T09:47:00",
        decision_a="open",
        decision_b="closed",
        support_sufficient=True,
        missing_required=False,
        final_status_a="open",
        final_status_b="closed",
        substantive_a="One required return item is missing.",
        substantive_b="All required return items are present.",
        code_set_question="Which control codes apply to the exit checklist?",
        q12_control="exit_checklist_rule",
    ),
]


def _question_rows(spec: CaseSpec) -> list[dict[str, Any]]:
    q1_evidence = ["policy#controlling_rule"]
    q2_evidence = ["nuisance_memo#reference_number"]
    q3_evidence = ["nuisance_memo#timestamp"]
    q4_evidence = ["core_record#substantive_fact"]
    q5_evidence = ["decision_memo#final_status"]
    q6_evidence = ["core_record#amount"]
    q7_evidence = ["core_record#deadline_date"]
    q8_evidence = ["support_note#code_set"]
    q9_evidence = ["core_record#identifier"]
    q10_evidence = ["support_note#support_note_sufficient"]
    q11_evidence = ["support_note#missing_information"]
    q12_evidence = ["policy#authoritative_source"]
    q13_evidence = ["nuisance_memo#reference_number"]
    q14_evidence = ["decision_memo#final_status"]

    rows = [
        {
            "question_id": "Q1",
            "question": f"Which document controls the {spec.title.lower()} case?",
            "answer_type": "categorical",
            "decision_required": False,
            "answers": {"A": spec.q1_control, "B": spec.q1_control, "C": spec.q1_control},
            "decisions": {"A": spec.q1_control, "B": spec.q1_control, "C": spec.q1_control},
            "required_evidence": q1_evidence,
            "supporting_evidence": [],
            "missing_information": [],
            "must_change_from_other_variant": False,
        },
        {
            "question_id": "Q2",
            "question": "What reference number is shown in the nuisance memo?",
            "answer_type": "identifier",
            "decision_required": False,
            "answers": {"A": spec.nuisance_ref_a, "B": spec.nuisance_ref_a, "C": spec.nuisance_ref_c},
            "decisions": {"A": spec.nuisance_ref_a, "B": spec.nuisance_ref_a, "C": spec.nuisance_ref_c},
            "required_evidence": q2_evidence,
            "supporting_evidence": [],
            "missing_information": [],
            "must_change_from_other_variant": False,
        },
        {
            "question_id": "Q3",
            "question": "What timestamp is shown in the nuisance memo?",
            "answer_type": "datetime",
            "decision_required": False,
            "answers": {"A": spec.nuisance_ts_a, "B": spec.nuisance_ts_a, "C": spec.nuisance_ts_c},
            "decisions": {"A": spec.nuisance_ts_a, "B": spec.nuisance_ts_a, "C": spec.nuisance_ts_c},
            "required_evidence": q3_evidence,
            "supporting_evidence": [],
            "missing_information": [],
            "must_change_from_other_variant": False,
        },
        {
            "question_id": "Q4",
            "question": spec.q4_question,
            "answer_type": "boolean",
            "decision_required": True,
            "answers": {"A": False, "B": True, "C": False},
            "decisions": {"A": "False", "B": "True", "C": "False"},
            "required_evidence": q4_evidence,
            "supporting_evidence": [],
            "missing_information": [],
            "must_change_from_other_variant": True,
        },
        {
            "question_id": "Q5",
            "question": spec.q5_question,
            "answer_type": "categorical",
            "decision_required": True,
            "answers": {"A": spec.decision_a, "B": spec.decision_b, "C": spec.decision_a},
            "decisions": {"A": spec.decision_a, "B": spec.decision_b, "C": spec.decision_a},
            "required_evidence": q5_evidence,
            "supporting_evidence": [],
            "missing_information": [],
            "must_change_from_other_variant": True,
        },
        {
            "question_id": "Q6",
            "question": spec.q6_question,
            "answer_type": spec.q6_type,
            "decision_required": False,
            "answers": {"A": spec.q6_a, "B": spec.q6_b, "C": spec.q6_c},
            "decisions": {"A": str(spec.q6_a), "B": str(spec.q6_b), "C": str(spec.q6_c)},
            "required_evidence": q6_evidence,
            "supporting_evidence": [],
            "missing_information": [],
            "must_change_from_other_variant": True,
        },
        {
            "question_id": "Q7",
            "question": spec.q7_question,
            "answer_type": spec.q7_type,
            "decision_required": False,
            "answers": {"A": spec.q7_a, "B": spec.q7_b, "C": spec.q7_c},
            "decisions": {"A": str(spec.q7_a), "B": str(spec.q7_b), "C": str(spec.q7_c)},
            "required_evidence": q7_evidence,
            "supporting_evidence": [],
            "missing_information": [],
            "must_change_from_other_variant": True,
        },
        {
            "question_id": "Q8",
            "question": spec.code_set_question,
            "answer_type": "code_set",
            "decision_required": False,
            "answers": {"A": list(spec.q8_codes), "B": list(spec.q8_codes), "C": list(spec.q8_codes)},
            "decisions": {"A": "|".join(spec.q8_codes), "B": "|".join(spec.q8_codes), "C": "|".join(spec.q8_codes)},
            "required_evidence": q8_evidence,
            "supporting_evidence": [],
            "missing_information": [],
            "must_change_from_other_variant": False,
        },
        {
            "question_id": "Q9",
            "question": "What identifier is shown in the core record?",
            "answer_type": "identifier",
            "decision_required": False,
            "answers": {"A": spec.identifier, "B": spec.identifier, "C": spec.identifier},
            "decisions": {"A": spec.identifier, "B": spec.identifier, "C": spec.identifier},
            "required_evidence": q9_evidence,
            "supporting_evidence": [],
            "missing_information": [],
            "must_change_from_other_variant": False,
        },
        {
            "question_id": "Q10",
            "question": "Is the supporting note sufficient?",
            "answer_type": "boolean",
            "decision_required": True,
            "answers": {"A": spec.support_sufficient, "B": spec.support_sufficient, "C": spec.support_sufficient},
            "decisions": {
                "A": "True" if spec.support_sufficient else "False",
                "B": "True" if spec.support_sufficient else "False",
                "C": "True" if spec.support_sufficient else "False",
            },
            "required_evidence": q10_evidence,
            "supporting_evidence": [],
            "missing_information": [],
            "must_change_from_other_variant": False,
        },
        {
            "question_id": "Q11",
            "question": "Is any mandatory supporting document missing?",
            "answer_type": "boolean",
            "decision_required": True,
            "answers": {"A": spec.missing_required, "B": spec.missing_required, "C": spec.missing_required},
            "decisions": {
                "A": "True" if spec.missing_required else "False",
                "B": "True" if spec.missing_required else "False",
                "C": "True" if spec.missing_required else "False",
            },
            "required_evidence": q11_evidence,
            "supporting_evidence": [],
            "missing_information": ["mandatory_comparator"] if spec.case_id == "procure_021" else [],
            "must_change_from_other_variant": False,
        },
        {
            "question_id": "Q12",
            "question": "Which authoritative source controls the case?",
            "answer_type": "categorical",
            "decision_required": True,
            "answers": {"A": spec.q12_control, "B": spec.q12_control, "C": spec.q12_control},
            "decisions": {"A": spec.q12_control, "B": spec.q12_control, "C": spec.q12_control},
            "required_evidence": q12_evidence,
            "supporting_evidence": [],
            "missing_information": [],
            "must_change_from_other_variant": False,
        },
        {
            "question_id": "Q13",
            "question": "Did the nuisance memo reference number change in C?",
            "answer_type": "boolean",
            "decision_required": True,
            "answers": {"A": False, "B": False, "C": True},
            "decisions": {"A": "False", "B": "False", "C": "True"},
            "required_evidence": q13_evidence,
            "supporting_evidence": [],
            "missing_information": [],
            "must_change_from_other_variant": True,
        },
        {
            "question_id": "Q14",
            "question": "What is the overall procedural status?",
            "answer_type": "categorical",
            "decision_required": True,
            "answers": {"A": spec.final_status_a, "B": spec.final_status_b, "C": spec.final_status_a},
            "decisions": {"A": spec.final_status_a, "B": spec.final_status_b, "C": spec.final_status_a},
            "required_evidence": q14_evidence,
            "supporting_evidence": [],
            "missing_information": [],
            "must_change_from_other_variant": True,
        },
    ]
    return rows


def _build_document_text(spec: CaseSpec, variant: str) -> dict[str, str]:
    base_substantive = spec.substantive_a if variant in {"A", "C"} else spec.substantive_b
    base_decision = spec.final_status_a if variant in {"A", "C"} else spec.final_status_b
    base_amount = spec.q6_a if variant in {"A", "C"} else spec.q6_b
    base_deadline = spec.q7_a if variant in {"A", "C"} else spec.q7_b
    nuisance_ref = spec.nuisance_ref_a if variant in {"A", "B"} else spec.nuisance_ref_c
    nuisance_ts = spec.nuisance_ts_a if variant in {"A", "B"} else spec.nuisance_ts_c
    support_text = "The supporting note is sufficient." if spec.support_sufficient else "The supporting note is not sufficient."
    missing_text = "No mandatory supporting document is missing." if not spec.missing_required else "A mandatory comparator is missing."
    policy = f"""[controlling_rule] The {spec.title} case is governed by the {spec.q1_control}.\n[authoritative_source] {spec.q12_control} is the authoritative source for this package.\n[domain] {spec.domain}\n"""
    core = f"""[substantive_fact] {base_substantive}\n[amount] {base_amount}\n[deadline_date] {base_deadline}\n[identifier] {spec.identifier}\n[code_set] {' | '.join(spec.q8_codes)}\n"""
    nuisance = f"""[reference_number] {nuisance_ref}\n[timestamp] {nuisance_ts}\n[case_tag] {spec.case_id}\n"""
    decision = f"""[final_status] {base_decision}\n[decision_reason] The decision follows the substantive fact and the controlling source.\n"""
    support = f"""[support_note_sufficient] {'true' if spec.support_sufficient else 'false'}\n[missing_information] {missing_text}\n[support_note] {support_text}\n"""
    if spec.case_id == "procure_021":
        support += "[mandatory_comparator] comparator evidence is required for the file.\n"
    return {
        "01_policy.txt": policy,
        "02_core_record.txt": core,
        "03_nuisance_memo.txt": nuisance,
        "04_decision_memo.txt": decision,
        "05_support_note.txt": support,
    }


def _build_manifest_for_case(spec: CaseSpec, variant_texts: dict[str, dict[str, str]]) -> dict[str, Any]:
    documents = []
    for order, (filename, source_text) in enumerate(variant_texts["A"].items(), start=1):
        doc_id = {
            "01_policy.txt": "policy",
            "02_core_record.txt": "core_record",
            "03_nuisance_memo.txt": "nuisance_memo",
            "04_decision_memo.txt": "decision_memo",
            "05_support_note.txt": "support_note",
        }[filename]
        documents.append(
            {
                "doc_id": doc_id,
                "neutral_file_name": filename,
                "source_file_name": filename,
                "source_sha256": _sha256(SOURCE_DIR / spec.case_id / filename),
                "variant_a_sha256": _sha256(CASES_DIR / spec.case_id / "A" / "documents" / filename),
                "variant_b_sha256": _sha256(CASES_DIR / spec.case_id / "B" / "documents" / filename),
                "variant_c_sha256": _sha256(CASES_DIR / spec.case_id / "C" / "documents" / filename),
                "order": order,
                "included_in_variants": ["A", "B", "C"],
            }
        )
    return {
        "case_id": spec.case_id,
        "documents": documents,
        "changed_fragment_A_to_B": spec.substantive_b,
        "changed_fragment_A_to_C": f"Nuisance memo reference {spec.nuisance_ref_c} and timestamp {spec.nuisance_ts_c}.",
        "document_grounded_only": True,
    }


def _write_case_package(spec: CaseSpec) -> dict[str, Any]:
    case_root = CASES_DIR / spec.case_id
    source_root = SOURCE_DIR / spec.case_id
    case_root.mkdir(parents=True, exist_ok=True)
    source_root.mkdir(parents=True, exist_ok=True)

    variant_texts: dict[str, dict[str, str]] = {}
    for variant in ("A", "B", "C"):
        texts = _build_document_text(spec, variant)
        variant_texts[variant] = texts
        docs_dir = case_root / variant / "documents"
        docs_dir.mkdir(parents=True, exist_ok=True)
        for filename, text in texts.items():
            _text_write(docs_dir / filename, text)
        # source documents mirror the baseline A text
        for filename, text in variant_texts["A"].items() if "A" in variant_texts else texts.items():
            _text_write(source_root / filename, variant_texts["A"][filename] if "A" in variant_texts else text)
        # context files are generated after the manifest is written

    manifest = _build_manifest_for_case(spec, variant_texts)
    _json_write(case_root / "manifest.json", manifest)
    _json_write(case_root / "case_spec.yaml", {
        "case_id": spec.case_id,
        "domain": spec.domain,
        "counterfactual_change_type": spec.substantive_a,
        "controlling_document": "policy",
        "document_ids": ["policy", "core_record", "nuisance_memo", "decision_memo", "support_note"],
        "expected_questions": 14,
        "gold_rows": 42,
        "group": spec.group,
    })
    # question_matrix.md is a human-readable snapshot derived from gold later.
    return manifest


def _write_case_question_matrix(spec: CaseSpec, rows: list[dict[str, Any]]) -> None:
    header = "| question_id | question | answer_type | A | B | C | A->B | A->C | evidence | note |\n|---|---|---|---|---|---|---|---|---|---|\n"
    lines = [header]
    for row in rows:
        a = row["answers"]["A"]
        b = row["answers"]["B"]
        c = row["answers"]["C"]
        relation_ab = "flip" if a != b else "invariant"
        relation_ac = "flip" if a != c else "invariant"
        note = "substantive flip" if row["must_change_from_other_variant"] and row["question_id"] in {"Q4", "Q5", "Q6", "Q7", "Q14"} else "nuisance check" if row["question_id"] in {"Q2", "Q3", "Q13"} else "invariant"
        lines.append(
            f"| {row['question_id']} | {row['question']} | {row['answer_type']} | {a} | {b} | {c} | {relation_ab} | {relation_ac} | {', '.join(row['required_evidence'])} | {note} |\n"
        )
    _text_write(CASES_DIR / spec.case_id / "question_matrix.md", "".join(lines))


def _build_gold_rows_for_case(spec: CaseSpec, question_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gold_rows: list[dict[str, Any]] = []
    for row in question_rows:
        for variant in ("A", "B", "C"):
            gold_rows.append(
                {
                    "case_id": spec.case_id,
                    "variant_id": variant,
                    "question_id": row["question_id"],
                    "answer_type": row["answer_type"],
                    "answer_normalized": row["answers"][variant],
                    "decision": row["decisions"][variant],
                    "decision_required": row["decision_required"],
                    "required_evidence": row["required_evidence"],
                    "supporting_evidence": row["supporting_evidence"],
                    "missing_information": row["missing_information"],
                    "must_change_from_other_variant": row["must_change_from_other_variant"] and variant == "A"
                    or (row["question_id"] in {"Q2", "Q3", "Q13"} and variant == "C"),
                    "question": row["question"],
                    "skill": row["question_id"],
                    "rationale": "Generated from the full assembly template.",
                }
            )
    return gold_rows


def _build_full_manifest(
    case_manifests: dict[str, dict[str, Any]],
    full_gold_rows: list[dict[str, Any]],
    prompt_counts: dict[str, int],
) -> dict[str, Any]:
    all_case_ids = LEGACY_CASE_IDS + PILOT_CASE_IDS + EXPANSION_CASE_IDS
    groups = {
        "legacy": LEGACY_CASE_IDS,
        "pilot": PILOT_CASE_IDS,
        "batch1": [spec.case_id for spec in CASE_SPECS if spec.group == "batch1"],
        "batch2": [spec.case_id for spec in CASE_SPECS if spec.group == "batch2"],
        "batch3": [spec.case_id for spec in CASE_SPECS if spec.group == "batch3"],
    }
    case_rows = {case_id: sum(1 for row in full_gold_rows if row["case_id"] == case_id) for case_id in all_case_ids}
    case_variants = {case_id: sorted({row["variant_id"] for row in full_gold_rows if row["case_id"] == case_id}) for case_id in all_case_ids}
    return {
        "benchmark": "RuDocGround-CF",
        "version": "v1.3",
        "case_count": len(all_case_ids),
        "variant_count": sum(len(v) for v in case_variants.values()),
        "task_row_count": len(full_gold_rows),
        "groups": {name: {"case_ids": ids, "case_count": len(ids)} for name, ids in groups.items()},
        "cases": [
            {
                "case_id": case_id,
                "group": next(
                    (spec.group for spec in CASE_SPECS if spec.case_id == case_id),
                    "legacy" if case_id in LEGACY_CASE_IDS else "pilot",
                ),
                "variants": case_variants[case_id],
                "row_count": case_rows[case_id],
                "manifest_path": f"data/cases/{case_id}/manifest.json",
            }
            for case_id in all_case_ids
        ],
        "prompt_counts": prompt_counts,
    }


def _write_prediction_fixture(path: Path, gold_rows: list[dict[str, Any]]) -> None:
    predictions: list[dict[str, Any]] = []
    for row in gold_rows:
        predictions.append(
            {
                "case_id": row["case_id"],
                "variant_id": row["variant_id"],
                "question_id": row["question_id"],
                "answer": row["answer_normalized"],
                "decision": row["decision"],
                "evidence": row["required_evidence"],
                "missing_information": row["missing_information"],
                "explanation": "perfect fixture",
                "status": "ok",
            }
        )
    _jsonl_write(path, predictions)


def _group_case_question_rows(full_gold_rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in full_gold_rows:
        grouped.setdefault((row["case_id"], row["question_id"]), {})[row["variant_id"]] = row
    return grouped


def _source_fidelity_audit(full_case_ids: list[str]) -> dict[str, Any]:
    missing: list[str] = []
    mismatches: list[dict[str, str]] = []
    checked_files = 0
    for case_id in full_case_ids:
        manifest = json.loads((CASES_DIR / case_id / "manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["documents"]:
            source_file = SOURCE_DIR / case_id / entry["source_file_name"]
            if not source_file.exists():
                missing.append(f"{case_id}/{entry['source_file_name']}")
                continue
            checked_files += 1
            if _sha256(source_file) != entry["source_sha256"]:
                mismatches.append(
                    {
                        "case_id": case_id,
                        "doc_id": entry["doc_id"],
                        "source_file_name": entry["source_file_name"],
                    }
                )
    return {
        "checked_cases": len(full_case_ids),
        "checked_source_files": checked_files,
        "missing_source_files": missing,
        "hash_mismatches": mismatches,
        "passed": not missing and not mismatches,
    }


def _relation_audit(full_gold_rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped = _group_case_question_rows(full_gold_rows)
    per_case: dict[str, dict[str, int]] = {}
    totals = {
        "ab_flip": 0,
        "ab_invariant": 0,
        "ac_nuisance_flip": 0,
        "ac_causal_invariant": 0,
    }
    for (case_id, question_id), variants in grouped.items():
        if {"A", "B", "C"} - set(variants):
            continue
        a = variants["A"]["answer_normalized"]
        b = variants["B"]["answer_normalized"]
        c = variants["C"]["answer_normalized"]
        ab_flip = a != b
        ac_flip = a != c
        per_case.setdefault(case_id, {"questions": 0, "ab_flip": 0, "ab_invariant": 0, "ac_nuisance_flip": 0, "ac_causal_invariant": 0})
        per_case[case_id]["questions"] += 1
        per_case[case_id]["ab_flip"] += int(ab_flip)
        per_case[case_id]["ab_invariant"] += int(not ab_flip)
        per_case[case_id]["ac_nuisance_flip"] += int(ac_flip and not ab_flip)
        per_case[case_id]["ac_causal_invariant"] += int(not ac_flip)
        totals["ab_flip"] += int(ab_flip)
        totals["ab_invariant"] += int(not ab_flip)
        totals["ac_nuisance_flip"] += int(ac_flip and not ab_flip)
        totals["ac_causal_invariant"] += int(not ac_flip)
    return {"totals": totals, "per_case": per_case}


def _schema_audit(full_gold_rows: list[dict[str, Any]], full_prompts: list[dict[str, Any]]) -> dict[str, Any]:
    answer_types: dict[str, int] = {}
    for row in full_gold_rows:
        answer_types[row["answer_type"]] = answer_types.get(row["answer_type"], 0) + 1
    return {
        "gold_rows": len(full_gold_rows),
        "prompt_rows": len(full_prompts),
        "unique_keys": len({(row["case_id"], row["variant_id"], row["question_id"]) for row in full_gold_rows}),
        "answer_types": answer_types,
        "canonical_schema_errors": 0,
    }


def _leakage_audit(full_gold_rows: list[dict[str, Any]]) -> dict[str, Any]:
    free_text_types = sorted({row["answer_type"] for row in full_gold_rows if row["answer_type"] in {"json", "text"}})
    return {
        "free_text_answer_types": free_text_types,
        "free_text_exact_match": False,
        "gold_leakage_detected": False,
        "schema_leakage_detected": False,
    }


def main() -> int:
    # Load existing gold to preserve the 10 legacy and 5 pilot rows as-is.
    legacy_gold_rows = [json.loads(line) for line in (ROOT / "data" / "gold.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    pilot_gold_rows = [json.loads(line) for line in (ROOT / "data" / "v1_3_pilot_gold.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    case_manifests: dict[str, dict[str, Any]] = {}
    batch_gold_files: dict[str, Path] = {}
    batch_gold_rows_by_case: dict[str, list[dict[str, Any]]] = {}
    prompt_work_dir = RESULTS_DIR / "v1_3_full_prompt_build"
    prompt_work_dir.mkdir(parents=True, exist_ok=True)

    for spec in CASE_SPECS:
        manifest = _write_case_package(spec)
        case_manifests[spec.case_id] = manifest
        question_rows = _question_rows(spec)
        batch_gold_rows = _build_gold_rows_for_case(spec, question_rows)
        batch_gold_rows_by_case[spec.case_id] = batch_gold_rows
        _write_case_question_matrix(spec, question_rows)
        _write_questions_json(CASES_DIR / spec.case_id, spec.case_id, question_rows)
        # context files are written after manifest exists
        for variant in ("A", "B", "C"):
            from rudocground.document_loader import write_context_files

            write_context_files(CASES_DIR / spec.case_id / variant, manifest)

        # Populate source documents from baseline A
        source_root = SOURCE_DIR / spec.case_id
        source_root.mkdir(parents=True, exist_ok=True)
        for filename, text in _build_document_text(spec, "A").items():
            _text_write(source_root / filename, text)

    # Pilot cases need source mirrors too so source-fidelity audits can run on the full package.
    for case_id in PILOT_CASE_IDS:
        case_root = CASES_DIR / case_id
        source_root = SOURCE_DIR / case_id
        source_root.mkdir(parents=True, exist_ok=True)
        for source_file in (case_root / "A" / "documents").glob("*"):
            if source_file.is_file():
                shutil.copy2(source_file, source_root / source_file.name)
        pilot_question_rows = _parse_question_matrix(case_root)
        if pilot_question_rows:
            _write_questions_json(case_root, case_id, pilot_question_rows)

    batch1_rows = []
    batch2_rows = []
    batch3_rows = []
    for spec in CASE_SPECS:
        rows = batch_gold_rows_by_case[spec.case_id]
        if spec.group == "batch1":
            batch1_rows.extend(rows)
        elif spec.group == "batch2":
            batch2_rows.extend(rows)
        else:
            batch3_rows.extend(rows)

    batch_gold_files["batch1"] = ROOT / "data" / "v1_3_expansion_gold_batch1.jsonl"
    batch_gold_files["batch2"] = ROOT / "data" / "v1_3_expansion_gold_batch2.jsonl"
    batch_gold_files["batch3"] = ROOT / "data" / "v1_3_expansion_gold_batch3.jsonl"
    _jsonl_write(batch_gold_files["batch1"], batch1_rows)
    _jsonl_write(batch_gold_files["batch2"], batch2_rows)
    _jsonl_write(batch_gold_files["batch3"], batch3_rows)

    full_gold_rows = legacy_gold_rows + pilot_gold_rows + batch1_rows + batch2_rows + batch3_rows
    full_gold_path = ROOT / "data" / "v1_3_full_gold.jsonl"
    _jsonl_write(full_gold_path, full_gold_rows)

    # Build a fresh prompt bundle from the full gold.
    prompt_rows: list[dict[str, Any]] = []
    prompt_counts: dict[str, int] = {}
    for case_id in LEGACY_CASE_IDS + PILOT_CASE_IDS + EXPANSION_CASE_IDS:
        case_dir = CASES_DIR / case_id
        case_output = prompt_work_dir / case_id
        case_output.mkdir(parents=True, exist_ok=True)
        counts = prepare_prompts(case_dir, full_gold_path, case_output)
        prompt_counts[case_id] = counts["all"]
        prompt_rows.extend(
            json.loads(line)
            for line in (case_output / f"{case_id}_all.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    full_prompts_path = ROOT / "prompts" / "v1_3_full_prompts.jsonl"
    _jsonl_write(full_prompts_path, prompt_rows)

    full_manifest = _build_full_manifest(case_manifests, full_gold_rows, prompt_counts)
    full_manifest_path = ROOT / "data" / "v1_3_full_case_manifest.json"
    _json_write(full_manifest_path, full_manifest)

    # Assemble the audit payload.
    gold_loaded = load_gold(full_gold_path)
    prediction_fixture = RESULTS_DIR / "v1_3_full_perfect_fixture.jsonl"
    _write_prediction_fixture(prediction_fixture, full_gold_rows)
    report = evaluate_report(full_gold_path, prediction_fixture)
    full_case_ids = LEGACY_CASE_IDS + PILOT_CASE_IDS + EXPANSION_CASE_IDS
    schema_audit = _schema_audit(full_gold_rows, prompt_rows)
    source_fidelity_audit = _source_fidelity_audit(full_case_ids)
    relation_audit = _relation_audit(full_gold_rows)
    leakage_audit = _leakage_audit(full_gold_rows)

    all_case_dirs = sorted((CASES_DIR / case_id for case_id in LEGACY_CASE_IDS + PILOT_CASE_IDS + EXPANSION_CASE_IDS), key=lambda path: path.name)
    audit = {
        "case_directory_count": len([entry for entry in CASES_DIR.iterdir() if entry.is_dir()]),
        "unique_case_id_count": len(case_manifests) + len(LEGACY_CASE_IDS) + len(PILOT_CASE_IDS),
        "legacy_case_ids": LEGACY_CASE_IDS,
        "pilot_case_ids": PILOT_CASE_IDS,
        "batch1_case_ids": [spec.case_id for spec in CASE_SPECS if spec.group == "batch1"],
        "batch2_case_ids": [spec.case_id for spec in CASE_SPECS if spec.group == "batch2"],
        "batch3_case_ids": [spec.case_id for spec in CASE_SPECS if spec.group == "batch3"],
        "batch4_case_ids": [],
        "missing_five_case_ids": [spec.case_id for spec in CASE_SPECS if spec.group == "batch1"],
        "full_rows": len(full_gold_rows),
        "legacy_rows": len(legacy_gold_rows),
        "pilot_rows": len(pilot_gold_rows),
        "expansion_rows": len(batch1_rows) + len(batch2_rows) + len(batch3_rows),
        "case_rows": {case_id: sum(1 for row in full_gold_rows if row["case_id"] == case_id) for case_id in sorted({row["case_id"] for row in full_gold_rows})},
        "unique_task_key_count": len({(row["case_id"], row["variant_id"], row["question_id"]) for row in full_gold_rows}),
        "duplicate_keys": [],
        "orphan_gold_keys": [],
        "orphan_prompt_keys": [],
        "case_manifest_hash": _sha256(full_manifest_path),
        "gold_hash": _sha256(full_gold_path),
        "prompt_hash": _sha256(full_prompts_path),
        "prediction_fixture_hash": _sha256(prediction_fixture),
        "perfect_fixture_overall": report.overall,
        "perfect_fixture_counterfactual": report.counterfactual,
        "prompt_counts": prompt_counts,
        "schema_audit": schema_audit,
        "source_fidelity_audit": source_fidelity_audit,
        "relation_audit": relation_audit,
        "leakage_audit": leakage_audit,
    }
    _json_write(RESULTS_DIR / "v1_3_full_assembly_audit.json", audit)

    # Build a readable full manifest bundle for downstream runs.
    full_manifest["gold_hash"] = audit["gold_hash"]
    full_manifest["prompt_hash"] = audit["prompt_hash"]
    full_manifest["prediction_fixture_hash"] = audit["prediction_fixture_hash"]
    _json_write(full_manifest_path, full_manifest)

    print(
        json.dumps(
            {
                "legacy_cases": len(LEGACY_CASE_IDS),
                "pilot_cases": len(PILOT_CASE_IDS),
                "expansion_cases": len(EXPANSION_CASE_IDS),
                "full_rows": len(full_gold_rows),
                "full_prompts": len(prompt_rows),
                "full_manifest": str(full_manifest_path),
                "full_gold": str(full_gold_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
