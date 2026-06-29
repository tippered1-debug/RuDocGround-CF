from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import copy
import hashlib
import json
import re
from typing import Any

from .document_loader import extract_document_structure, write_context_files
from .models import normalize_answer_value


FORBIDDEN_HINTS = (
    "version",
    "variant",
    "counterfactual",
    "broken",
    "gold",
)


SYSTEM_PROMPT = (
    "You answer questions using only the provided documents.\n"
    "Do not use external knowledge.\n"
    "If the documents do not contain enough information, set decision to insufficient_information.\n"
    "Do not treat preliminary approval as final reimbursement.\n"
    "Do not replace a limit with an extra validation step.\n"
    "Only cite documents that directly support the answer.\n"
    "Do not refer to documents that are not present.\n"
    "Return only valid JSON. No Markdown."
)


EXPECTED_OUTPUT_SCHEMA = {
    "case_id": "trip_001",
    "variant_id": "A",
    "question_id": "Q1",
    "answer": None,
    "decision": None,
    "evidence": [],
    "missing_information": [],
    "explanation": "",
}

CASE_PROMPT_COUNTS = {
    "trip_001": 34,
    "procurement_002": 30,
    "authority_003": 32,
    "acceptance_004": 32,
    "notice_005": 32,
    "reconciliation_006": 32,
    "amendment_007": 32,
    "sla_008": 32,
    "approval_chain_009": 32,
    "asset_scope_010": 32,
}


DECISION_LABEL_OPTIONS: dict[str, dict[str, list[str]]] = {
    "trip_001": {
        "Q4": ["is_a_reimbursement_cap", "not_a_reimbursement_cap"],
        "Q6": ["max_allowable_hotel_cost", "not_max_allowable_hotel_cost"],
        "Q7": ["reimburse", "partially_reimburse"],
        "Q8": ["preapproved", "not_preapproved"],
        "Q9": ["preapproval_not_final_reimbursement", "preapproval_is_final_reimbursement"],
        "Q11": ["approved_in_time", "approved_after_deadline"],
        "Q12": ["presence_and_business_activity_confirmed", "presence_or_business_activity_not_confirmed"],
        "Q14": ["taxi_expense_supported", "taxi_expense_not_supported"],
        "Q15": ["insufficient_information", "sufficient_information"],
        "Q16": ["submitted_on_time", "submitted_late"],
        "Q17": ["request_additional_documents", "no_additional_documents_needed"],
    }
}


QUESTION_ANSWER_TYPE_OVERRIDES: dict[tuple[str, str], str] = {
    ("authority_003", "Q1"): "categorical",
    ("authority_003", "Q2"): "categorical",
    ("authority_003", "Q13"): "categorical",
    ("acceptance_004", "Q3"): "categorical",
    ("acceptance_004", "Q13"): "categorical",
    ("amendment_007", "Q2"): "categorical",
    ("amendment_007", "Q12"): "categorical",
    ("asset_scope_010", "Q12"): "categorical",
    ("asset_scope_010", "Q13"): "categorical",
    ("notice_005", "Q2"): "categorical",
    ("notice_005", "Q12"): "categorical",
    ("reconciliation_006", "Q12"): "categorical",
    ("sla_008", "Q9"): "categorical",
    ("sla_008", "Q12"): "categorical",
    ("approval_chain_009", "Q9"): "code_set",
}


CONTRACT_SUBJECT_VALUES = [
    "managed_backup_services",
    "network_infrastructure_assessment_and_technical_report",
    "supply_of_network_equipment_for_ural_branch",
    "аренда_выделенного_серверного_ресурса",
]


ROLE_ENTITY_VALUES = [
    "general_director",
    "director_ural_branch",
    "ООО «Северный контур»",
    "Смирнов Игорь Петрович",
    "Орлов Дмитрий Александрович",
]


IDENTIFIER_KIND_VALUES = [
    "inventory_card_identifier",
    "manufacturer_serial_identifier",
]


EVENT_KIND_VALUES = [
    "support_request_received",
    "automatic_monitoring_registration",
]


CODE_SET_VALUES = [
    "system_owner_approval",
    "information_security_approval",
]


def _allowed_doc_kind_values(manifest: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for entry in manifest.get("documents", []):
        doc_id = entry.get("doc_id")
        if isinstance(doc_id, str) and doc_id not in values:
            if doc_id.startswith("amendment_"):
                normalized = "additional_agreement"
            else:
                normalized = doc_id[:-2] if doc_id.endswith(("_A", "_B")) else doc_id
            if normalized not in values:
                values.append(normalized)
    return values


def _derive_companion_decision_label(label: str) -> str:
    normalized = label.strip()
    if not normalized:
        return "not_specified"
    if normalized == "insufficient_information":
        return "sufficient_information"

    replacements = [
        ("does_not_", "does_"),
        ("doesn't_", "does_"),
        ("not_", ""),
        ("_not_", "_"),
        ("no_", ""),
        ("_required", "_not_required"),
        ("_not_required", "_required"),
        ("_allowed", "_not_allowed"),
        ("_not_allowed", "_allowed"),
        ("_permitted", "_not_permitted"),
        ("_not_permitted", "_permitted"),
        ("_complies_with_policy", "_not_compliant_with_policy"),
        ("_not_compliant_with_policy", "_complies_with_policy"),
        ("_payable_as_presented", "_requires_correction"),
        ("_requires_correction", "_payable_as_presented"),
        ("_approved_in_time", "_approved_after_deadline"),
        ("_approved_after_deadline", "_approved_in_time"),
        ("_active_in_november", "_not_active_in_november"),
        ("_not_active_in_november", "_active_in_november"),
        ("_matches_order", "_does_not_match_order"),
        ("_does_not_match_order", "_matches_order"),
        ("_matches_listed", "_does_not_match_listed"),
        ("_does_not_match_listed", "_matches_listed"),
        ("_inside_subscription", "_outside_subscription"),
        ("_outside_subscription", "_inside_subscription"),
        ("_authorized_for_this_deal", "_not_authorized_for_this_deal"),
        ("_not_authorized_for_this_deal", "_authorized_for_this_deal"),
        ("_submitted_on_time", "_submitted_late"),
        ("_submitted_late", "_submitted_on_time"),
        ("_not_payable_as_presented", "_payable_as_presented"),
        ("_payable_without_correction", "_requires_correction"),
    ]
    for needle, replacement in replacements:
        if needle in normalized:
            candidate = normalized.replace(needle, replacement, 1)
            if candidate != normalized:
                return candidate
    if normalized.endswith("_allowed"):
        return normalized[: -len("_allowed")] + "_not_allowed"
    if normalized.endswith("_required"):
        return normalized[: -len("_required")] + "_not_required"
    if normalized.endswith("_permitted"):
        return normalized[: -len("_permitted")] + "_not_permitted"
    if normalized.endswith("_complies_with_policy"):
        return normalized[: -len("_complies_with_policy")] + "_not_compliant_with_policy"
    if normalized.endswith("_payable_as_presented"):
        return normalized[: -len("_payable_as_presented")] + "_requires_correction"
    if normalized.endswith("_approved_in_time"):
        return normalized[: -len("_approved_in_time")] + "_approved_after_deadline"
    if normalized.endswith("_active_in_november"):
        return normalized[: -len("_active_in_november")] + "_not_active_in_november"
    return f"not_{normalized}"


class CaseAuditError(ValueError):
    pass


LOCATOR_PATTERNS: dict[str, dict[str, list[str]]] = {
    "policy_01": {
        "appendix_1": ["Приложение 1 к Положению о служебных командировках"],
        "1.8": ["1.8."],
        "1.8-1.9": ["1.8.", "1.9."],
        "2.6": ["2.6."],
        "4.1,4.4": ["4.1.", "4.4."],
        "4.4-4.5": ["4.4.", "4.5."],
        "7.1,7.6": ["7.1.", "7.6."],
        "7.3-7.4": ["7.3.", "7.4."],
        "8.1": ["8.1."],
        "8.1-8.3": ["8.1.", "8.3."],
        "10.1-10.2": ["10.1.", "10.2."],
    },
    "finance_memo": {
        "paragraph_1": ["В целях единообразного контроля командировочных расходов"],
        "item_4": ["4) применимый к расходу лимит"],
    },
    "trip_request": {
        "hotel_preapproval": ["Статус заявки в СЭД: согласована"],
        "hotel_cost": ["Проживание | 34 200 руб. | 3 ночи × 11 400 руб."],
        "trip_dates": ["Срок командировки: с 15 сентября 2026 г. по 18 сентября 2026 г. включительно"],
        "approval_status": ["Статус заявки в СЭД: согласована, передана в отдел кадров для оформления приказа."],
    },
    "trip_order_241": {
        "1": ["1. Направить Крылова Андрея Сергеевича"],
    },
    "sed_extension": {
        "final_decision": ["Итоговое решение зафиксировано в СЭД 17 сентября 2026 г. в 12:26"],
        "extra_night": ["Дополнительное проживание: 1 ночь, с 18 на 19 сентября 2026 г.; стоимость — 11 400 руб."],
    },
    "trip_order_249": {
        "basis": ["Основание: карточка СЭД № СЭД-КМ-2026-0917-38, итоговое решение зафиксировано 17 сентября 2026 г. в 12:26."],
    },
    "hotel_invoice": {
        "rows_1_4": [
            "Проживание 15.09–16.09",
            "Проживание 16.09–17.09",
            "Проживание 17.09–18.09",
            "Проживание 18.09–19.09",
        ],
        "checkin_checkout": [
            "Заезд: 15 сентября 2026 г., 14:12",
            "Выезд: 19 сентября 2026 г., 08:36",
        ],
        "checkout": ["Выезд: 19 сентября 2026 г., 08:36"],
    },
    "hotel_payment": {
        "payment": ["Сумма платежа: 45 600,00 руб."],
    },
    "transport_pack": {
        "taxi_1": [
            "СЕРВИС «ГОРОД ТАКСИ»: ЭЛЕКТРОННЫЙ ЧЕК № GT-190926-7714",
            "Точка назначения: АО «Казанский приборный завод», проходная № 2",
        ],
        "taxi_2": [
            "СЕРВИС «ГОРОД ТАКСИ»: ЭЛЕКТРОННЫЙ ЧЕК № GT-190926-8842",
            "Точка назначения: Не указана в электронном чеке",
            "Документ подтверждает факт оплаты и точку отправления, но не содержит адреса назначения и сведений о служебной цели поездки.",
        ],
        "return_flight": [
            "Рейс VA 418",
            "Казань (KZN) | Москва (SVO)",
            "Новая перевозка: Рейс VA 418, 19.09.2026, Казань — Москва",
        ],
    },
    "meeting_protocol": {
        "date_time_participants_decisions": [
            "Дата проведения: 19 сентября 2026 г.",
            "Время: 09:30–15:55",
            "АО «Казанский приборный завод»: Громов Павел Ильич — директор по информационным технологиям",
            "ООО «Проектные системы»: Крылов Андрей Сергеевич — руководитель проектов",
            "Результаты обсуждения и принятые решения",
        ],
        "location_and_purpose": [
            "Место: АО «Казанский приборный завод», переговорная № 3",
            "приёмке первого этапа внедрения",
        ],
    },
    "expense_report": {
        "submission_date": ["Дата представления отчёта: 23 сентября 2026 г."],
        "taxi_2_review": [
            "4 | Такси после встречи | Чек № GT-190926-8842",
            "Не указан адрес назначения и служебная цель",
        ],
        "taxi_2_note": [
            "Примечание бухгалтерии: расход по чеку такси № GT-190926-8842",
        ],
    },
    "procurement_policy": {
        "threshold_300000": ["Прямая закупка допустима при цене договора до 300 000 руб. включительно."],
        "competitive_procedure": ["При цене договора свыше 300 000 руб. требуется конкурентная процедура."],
        "ceo_exception": [
            "Прямая закупка свыше 300 000 руб. возможна только на основании отдельного письменного решения генерального директора"
        ],
        "priority": [
            "временный приказ действует только в пределах указанного срока и по дате заключения договора",
            "лист согласования, договор и платёжная заявка сами по себе не отменяют",
        ],
        "no_override": [
            "отдельное решение генерального директора",
        ],
        "insufficient_docs": [
            "по первичным документам",
        ],
    },
    "temporary_order": {
        "limit_500000": ["предел прямой закупки по договорам на серверное оборудование для регионального офиса увеличивается до 500 000 руб."],
        "date_scope": ["Приказ применяется по дате заключения договора"],
        "valid_until_a": ["31 октября 2026 г. включительно"],
        "valid_until_b": ["15 октября 2026 г. включительно"],
    },
    "purchase_request": {
        "amount": ["на сумму 460 000 руб."],
        "direct_request": ["Просим приобрести напрямую без конкурентной процедуры"],
        "no_authorization": ["Заявка не является решением генерального директора"],
    },
    "commercial_offer": {
        "supplier": ["Поставщик: ООО «СеверТех»"],
        "amount": ["Общая цена 460 000 руб."],
        "validity": ["Срок действия предложения"],
    },
    "approval_sheet": {
        "approvals": ["Руководитель подразделения"],
        "finance_and_lawyer": ["Финансовый директор", "Юрист"],
        "review_only": ["Передать договор и оплату в работу"],
        "счёт направлен на сверку с договором и заказом": ["Комплект документов передан на сверку перед оплатой."],
        "подтверждает проверку, но не заменяет сверку цены и количества": ["Комплект документов передан на сверку перед оплатой."],
    },
    "supply_contract": {
        "date": ["Дата заключения: 20 октября 2026 г."],
        "signed": ["Договор подписан обеими сторонами."],
        "amount": ["Сумма договора: 460 000 руб."],
        "Поставщик: ООО «СеверТех».": ["Поставщик: ООО «СеверТех»."],
        "Цена за единицу: 32 000 руб.": ["Цена за единицу: 32 000 руб."],
        "Поставщик: ООО «СеверТех»": ["Поставщик: ООО «СеверТех»."],
        "Цена за единицу: 32 000 руб": ["Цена за единицу: 32 000 руб."],
    },
    "payment_request": {
        "basis": ["Основание: договор поставки от 20 октября 2026 г., лист согласования"],
        "amount": ["Просим оплатить 460 000 руб.", "Просим оплатить счёт ООО «СеверТех» по заказу № ЗП-06/26."],
        "reviewed": ["Комплект документов передан на сверку перед оплатой."],
        "Перед оплатой необходимо сверить количество и итоговую сумму в счёте с договором и заказом.": ["Основание: заказ поставщику, товарная накладная, приходный ордер склада и счёт."],
        "Просим оплатить счёт поставщика № 07/2026-14.": ["Просим оплатить счёт ООО «СеверТех» по заказу № ЗП-06/26."],
    },
    "payment_control_policy": {
        "payment_basis": ["Счёт может быть оплачен только при отсутствии расхождений между заказом, документами о фактической поставке и счётом."],
        "quantity_and_sum_match": ["При сверке проверяются наименование товара, количество, цена за единицу и сумма к оплате."],
        "corrections_required": ["Если в счёте количество или сумма не совпадают с заказом и приёмкой, комплект направляется на исправление."],
        "Счёт поставщика принимается к оплате только после сверки с договором поставки, заказом и актом приёмки.": ["Счёт может быть оплачен только при отсутствии расхождений между заказом, документами о фактической поставке и счётом."],
        "Документы внутреннего согласования подтверждают проверку, но не заменяют сверку цены и количества.": ["Внутренняя заявка на оплату не заменяет обязательную сверку документов."],
        "Если счёт содержит расхождение по количеству или сумме, требуется корректировка счёта до оплаты.": ["Если в счёте количество или сумма не совпадают с заказом и приёмкой, комплект направляется на исправление."],
    },
    "goods_receipt_act": {
        "received_quantity": ["На склад приняты 50 шт. мониторов MT-270."],
        "Получено: 50 шт.": ["На склад приняты 50 шт. мониторов MT-270."],
    },
    "supplier_invoice_A": {
        "invoice_title": ["СЧЁТ № 06/26-01"],
        "invoice_quantity": ["Количество: 50 шт."],
        "invoice_total": ["Сумма к оплате: 1 600 000 руб."],
        "СЧЁТ ПОСТАВЩИКА": ["СЧЁТ № 06/26-01"],
    },
    "supplier_invoice_B": {
        "invoice_title": ["СЧЁТ № 06/26-01"],
        "invoice_quantity": ["Количество: 55 шт."],
        "invoice_total": ["Сумма к оплате: 1 760 000 руб."],
        "СЧЁТ ПОСТАВЩИКА": ["СЧЁТ № 06/26-01"],
    },
    "contract_policy": {
        "signatory_rule": ["Договоры от имени Общества подписывает генеральный директор либо представитель, действующий в пределах предоставленных ему полномочий."],
        "authority_defined": ["Содержание полномочий представителя определяется доверенностью"],
        "approval_is_separate": ["Право подписи определяется отдельно от процедуры внутреннего согласования"],
        "post_execution": ["Документы об исполнении договора оформляются после совершения сделки"],
    },
    "power_of_attorney_A": {
        "subject_scope": ["договоры приобретения и поставки компьютерного, серверного и сетевого оборудования"],
        "limit_term": ["1 500 000 руб.", "1 сентября 2026 г.", "31 декабря 2026 г."],
    },
    "power_of_attorney_B": {
        "subject_scope": ["договоры технического обслуживания, ремонта и технической поддержки компьютерного, серверного и сетевого оборудования"],
        "limit_term": ["1 500 000 руб.", "1 сентября 2026 г.", "31 декабря 2026 г."],
    },
    "service_memo": {
        "request_amount": ["1 180 000 руб."],
        "request_subject": ["приобрести сетевое оборудование для Уральского филиала"],
        "approval_request": ["передать проект договора на согласование"],
    },
    "authority_approval_sheet": {
        "finance_confirmed": ["Финансовый директор: финансирование подтверждено."],
        "legal_reviewed": ["Юридическая служба: условия и форма проекта договора проверены."],
        "handoff": ["Передать договор на подписание директору Уральского филиала."],
    },
    "authority_contract": {
        "buyer_signatory": ["От имени покупателя договор подписал директор Уральского филиала"],
        "subject": ["поставка сетевого оборудования для Уральского филиала"],
        "amount": ["1 180 000 руб."],
        "date": ["12 ноября 2026 г."],
    },
    "transfer_act": {
        "transfer_confirmed": ["передал, а покупатель принял", "УФ-12/11-26"],
    },
    "authority_payment_request": {
        "payment_amount": ["1 180 000 руб."],
        "basis": ["на основании договора, акта и листа согласования", "по договору УФ-12/11-26"],
        "execution": ["для исполнения договорного обязательства"],
    },
    "service_contract": {
        "executor": ["Исполнитель: ООО «ПроектЛаб»"],
        "subject": [
            "Исполнитель обязуется провести обследование сетевой инфраструктуры заказчика, подготовить технический отчёт и рекомендации по результатам обследования.",
        ],
        "price": ["780 000", "Стоимость услуг составляет 780 000"],
        "acceptance_clause": [
            "после подписания акта сдачи-приёмки обеими сторонами",
            "после документально оформленной приёмки",
        ],
    },
    "technical_specification": {
        "scope": [
            "обследование сетевой инфраструктуры",
            "анализ текущей схемы",
            "подготовку рекомендаций",
        ]
    },
    "technical_report": {
        "prepared": ["Исполнитель подготовил технический отчёт"],
        "delivered": [
            "Исполнитель подготовил технический отчёт по результатам обследования сетевой инфраструктуры ООО «Северный контур» и передал его заказчику.",
        ],
    },
    "project_correspondence": {
        "no_comments": ["Содержательных замечаний к представленным материалам нет"],
        "forward_package": ["Просьба передать комплект документов для дальнейшего оформления"],
    },
    "acceptance_act_A": {
        "signed_by_both": ["Акт подписан обеими сторонами"],
        "customer_signature": ["Подпись заказчика:", "/Кузнецов Илья Андреевич/"],
        "acceptance_mark": ["Отметка о подписании: Акт подписан обеими сторонами."],
    },
    "acceptance_act_B": {
        "customer_signature_blank": ["Подпись заказчика:"],
        "acceptance_mark_blank": ["Отметка о подписании:"],
    },
    "service_invoice": {
        "invoice_amount": ["Сумма к оплате: 780 000 руб."],
        "invoice_basis": ["Основание: договор № СИ-14/09-26 от 14 сентября 2026 г."],
    },
    "service_payment_request": {
        "basis": [
            "Основание: договор, технический отчёт, акт сдачи-приёмки и счёт",
            "Просим оплатить счёт ООО «ПроектЛаб» на сумму 780 000 руб.",
        ],
        "contract": ["№ СИ-14/09-26", "14 сентября 2026 г."],
    },
    "system_owner_approval": {
        "владелец системы согласовал предоставление доступа": [
            "Владелец информационной системы согласовал предоставление доступа"
        ],
    },
    "access_policy": {
        "согласования владельца информационной системы и службы информационной безопасности": [
            "Привилегированный доступ предоставляется только после согласования владельца информационной системы и службы информационной безопасности."
        ],
    },
    "sla_contract": {
        "executor": ["Исполнитель: ООО «ОблакоСервис»."],
        "monthly_fee": ["500 000 руб. в месяц"],
        "recovery_limit": ["не более 4 часов"],
        "monitoring_start": ["с момента автоматической регистрации инцидента системой мониторинга"],
        "reduction_rate": ["уменьшается на 5 %"],
    },
    "sla_monitoring_log": {
        "incident_registered": [
            "Критический инцидент № CI-2026-08-12-01 зарегистрирован автоматически системой мониторинга",
            "12 августа 2026 г., 10:00",
        ],
    },
    "sla_support_request": {
        "received_at": ["10:15"],
        "same_incident": ["тот же инцидент"],
    },
    "technical_report_A": {
        "prepared": ["Исполнитель подготовил технический отчёт"],
        "restoration_time": ["Восстановление завершено в 13:59."],
        "operability_restored": ["Работоспособность корпоративной облачной платформы восстановлена."],
    },
    "technical_report_B": {
        "prepared": ["Исполнитель подготовил технический отчёт"],
        "restoration_time": ["Восстановление завершено в 14:01."],
        "operability_restored": ["Работоспособность корпоративной облачной платформы восстановлена."],
    },
    "sla_monthly_report": {
        "august_services": ["услуги оказывались в августе"],
        "incident_reflected": ["критический инцидент отражён"],
        "continued_work": ["работа платформы после восстановления продолжилась"],
    },
    "sla_invoice": {
        "invoice_amount": ["Сумма к оплате: 500 000 руб."],
        "invoice_period": ["Период: август 2026 г."],
        "invoice_basis": ["Основание: договор № СК-08/26"],
    },
    "sla_payment_request": {
        "basis": ["договор, журнал, обращение, технический отчёт и ежемесячный отчёт"],
        "payment_check": ["на проверку и оплату"],
        "invoice": ["счёт на 500 000 руб."],
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_gold_rows(gold_path: Path) -> list[dict[str, Any]]:
    rows = []
    with gold_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _contains_forbidden_hint(value: str) -> bool:
    lowered = value.lower()
    return any(hint in lowered for hint in FORBIDDEN_HINTS)


def _entry_filename(entry: dict[str, Any]) -> str:
    return entry.get("neutral_file_name") or entry.get("filename")


def _package_entries(manifest: dict[str, Any], variant: str) -> list[dict[str, Any]]:
    return [
        entry
        for entry in sorted(manifest["documents"], key=lambda item: (item["order"], item["doc_id"]))
        if variant in entry.get("included_in_variants", [])
    ]


def _package_expected_filenames(manifest: dict[str, Any], variant: str) -> list[str]:
    return [_entry_filename(entry) for entry in _package_entries(manifest, variant)]


def _case_id(manifest: dict[str, Any]) -> str:
    case_id = manifest.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise CaseAuditError("manifest missing case_id")
    return case_id


def _load_context(context_path: Path) -> dict[str, Any]:
    if not context_path.exists():
        raise CaseAuditError(f"missing context file: {context_path}")
    return json.loads(context_path.read_text(encoding="utf-8"))


def _context_text(package_dir: Path) -> str:
    context = _load_context(package_dir / "context.json")
    text = context.get("text")
    if not isinstance(text, str) or not text.strip():
        raise CaseAuditError(f"empty context text: {package_dir / 'context.json'}")
    return text


def _extract_package_docs(package_dir: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    docs_dir = package_dir / "documents"
    extracted: dict[str, dict[str, Any]] = {}
    for entry in _package_entries(manifest, package_dir.name):
        filename = _entry_filename(entry)
        doc_path = docs_dir / filename
        if not doc_path.exists():
            raise CaseAuditError(f"missing document: {doc_path}")
        extracted[filename] = extract_document_structure(doc_path, entry["doc_id"])
    return extracted


def _assert_order_docs_match_only_on_final_date(text_a: str, text_b: str) -> None:
    date_a = "20 сентября 2026 г."
    date_b = "18 сентября 2026 г."
    if date_a not in text_a or date_b not in text_b:
        raise CaseAuditError("order dates do not match expected values")
    if text_a.replace(date_a, date_b) != text_b:
        raise CaseAuditError("orders differ in more than the final date of the period")


def _generic_locator_resolves(locator: str, text: str) -> bool:
    tokens = re.findall(r"\d+(?:\.\d+)?|[A-Za-zА-Яа-я_]+", locator)
    if not tokens:
        return False
    return all(token in text for token in tokens)


def _locator_resolves(doc_id: str, locator: str, text: str) -> bool:
    patterns = LOCATOR_PATTERNS.get(doc_id, {}).get(locator)
    if patterns is not None:
        return all(pattern in text for pattern in patterns)
    return _generic_locator_resolves(locator, text)


def _validate_evidence_locators(gold_rows: list[dict[str, Any]], context_texts: dict[str, str]) -> None:
    unresolved: list[str] = []
    for row in gold_rows:
        for field in ("required_evidence", "supporting_evidence"):
            for evidence in row.get(field, []):
                if not isinstance(evidence, str) or "#" not in evidence:
                    continue
                doc_id, locator = evidence.split("#", 1)
                if doc_id not in context_texts:
                    continue
                if not _locator_resolves(doc_id, locator, context_texts[doc_id]):
                    unresolved.append(evidence)
    if unresolved:
        raise CaseAuditError(f"unresolved evidence locator(s): {unresolved[:5]}")


def _load_manifest(case_dir: Path) -> dict[str, Any]:
    manifest_path = case_dir / "manifest.json"
    if not manifest_path.exists():
        raise CaseAuditError(f"missing manifest: {manifest_path}")
    return _load_json(manifest_path)


def audit_case(case_dir: str | Path) -> None:
    case_path = Path(case_dir)
    manifest = _load_manifest(case_path)
    case_id = _case_id(manifest)
    if case_id == "approval_chain_009":
        _audit_approval_chain_case(case_path, manifest)
        return
    if case_id == "procurement_002":
        _audit_procurement_case(case_path, manifest)
        return
    if case_id == "authority_003":
        _audit_authority_case(case_path, manifest)
        return
    if case_id == "acceptance_004":
        _audit_acceptance_case(case_path, manifest)
        return
    if case_id == "notice_005":
        _audit_notice_case(case_path, manifest)
        return
    if case_id == "reconciliation_006":
        _audit_reconciliation_case(case_path, manifest)
        return
    if case_id == "amendment_007":
        _audit_amendment_case(case_path, manifest)
        return
    if case_id == "sla_008":
        _audit_sla_case(case_path, manifest)
        return
    if case_id == "asset_scope_010":
        _audit_asset_scope_case(case_path, manifest)
        return
    variants = ("A", "B")
    package_files: dict[str, list[str]] = {}
    package_hashes: dict[str, dict[str, str]] = {}
    order_files: dict[str, Path] = {}

    for variant in variants:
        documents_dir = case_path / variant / "documents"
        if not documents_dir.is_dir():
            raise CaseAuditError(f"missing documents directory: {documents_dir}")
        files = sorted(p.name for p in documents_dir.glob("*.docx"))
        if len(files) != 12:
            raise CaseAuditError(f"expected 12 documents in {variant}, found {len(files)}")
        if len(files) != len(set(files)):
            raise CaseAuditError(f"duplicate filenames in {documents_dir}")
        for filename in files:
            if _contains_forbidden_hint(filename):
                raise CaseAuditError(f"forbidden hint in filename: {filename}")
        expected_files = _package_expected_filenames(manifest, variant)
        if files != expected_files:
            raise CaseAuditError(f"{variant} filenames do not match manifest")
        package_files[variant] = files
        package_hashes[variant] = {name: _sha256(documents_dir / name) for name in files}
        order_files[variant] = next((documents_dir / name for name in files if "86-ОД" in name), None)
        if order_files[variant] is None:
            raise CaseAuditError(f"expected exactly one 86-ОД order in {variant}")

    if package_files["A"] != package_files["B"]:
        raise CaseAuditError("A and B must contain the same filenames in the same order")

    for variant in variants:
        for entry in _package_entries(manifest, variant):
            filename = _entry_filename(entry)
            expected_hash = entry["variant_a_sha256"] if variant == "A" else entry["variant_b_sha256"]
            actual_hash = package_hashes[variant][filename]
            if actual_hash != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for {variant}/{filename}")

    for filename in package_files["A"]:
        if "86-ОД" in filename:
            continue
        if package_hashes["A"][filename] != package_hashes["B"][filename]:
            raise CaseAuditError(f"non-order document differs: {filename}")

    text_a = extract_document_structure(order_files["A"], "order_A")["text"]
    text_b = extract_document_structure(order_files["B"], "order_B")["text"]
    _assert_order_docs_match_only_on_final_date(text_a, text_b)


def _audit_procurement_case(case_path: Path, manifest: dict[str, Any]) -> None:
    variants = ("A", "B")
    package_files: dict[str, list[str]] = {}
    package_hashes: dict[str, dict[str, str]] = {}
    order_doc_name = None
    for entry in manifest["documents"]:
        if entry["doc_id"] == "temporary_order":
            order_doc_name = _entry_filename(entry)
            break
    if order_doc_name is None:
        raise CaseAuditError("missing temporary_order document in manifest")

    for variant in variants:
        documents_dir = case_path / variant / "documents"
        if not documents_dir.is_dir():
            raise CaseAuditError(f"missing documents directory: {documents_dir}")
        files = sorted(p.name for p in documents_dir.glob("*.txt"))
        if len(files) != 7:
            raise CaseAuditError(f"expected 7 documents in {variant}, found {len(files)}")
        if len(files) != len(set(files)):
            raise CaseAuditError(f"duplicate filenames in {documents_dir}")
        for filename in files:
            if _contains_forbidden_hint(filename):
                raise CaseAuditError(f"forbidden hint in filename: {filename}")
        expected_files = _package_expected_filenames(manifest, variant)
        if files != expected_files:
            raise CaseAuditError(f"{variant} filenames do not match manifest")
        package_files[variant] = files
        package_hashes[variant] = {name: _sha256(documents_dir / name) for name in files}

    if package_files["A"] != package_files["B"]:
        raise CaseAuditError("A and B must contain the same filenames in the same order")

    for entry in manifest["documents"]:
        filename = _entry_filename(entry)
        expected_a = entry["variant_a_sha256"]
        expected_b = entry["variant_b_sha256"]
        if expected_a is None or expected_b is None:
            raise CaseAuditError(f"missing sha256 in manifest for {entry['doc_id']}")
        if package_hashes["A"][filename] != expected_a:
            raise CaseAuditError(f"sha256 mismatch for A/{filename}")
        if package_hashes["B"][filename] != expected_b:
            raise CaseAuditError(f"sha256 mismatch for B/{filename}")

    for filename in package_files["A"]:
        if filename == order_doc_name:
            continue
        if package_hashes["A"][filename] != package_hashes["B"][filename]:
            raise CaseAuditError(f"non-order document differs: {filename}")

    text_a = extract_document_structure(case_path / "A" / "documents" / order_doc_name, "temporary_order_A")["text"]
    text_b = extract_document_structure(case_path / "B" / "documents" / order_doc_name, "temporary_order_B")["text"]
    if "31 октября 2026 г." not in text_a or "15 октября 2026 г." not in text_b:
        raise CaseAuditError("temporary order dates do not match expected values")
    if text_a.replace("31 октября 2026 г.", "15 октября 2026 г.") != text_b:
        raise CaseAuditError("temporary orders differ in more than the final date of the period")


def _audit_authority_case(case_path: Path, manifest: dict[str, Any]) -> None:
    variants = ("A", "B")
    package_files: dict[str, list[str]] = {}
    package_hashes: dict[str, dict[str, str]] = {}
    poa_entries = [entry for entry in manifest["documents"] if entry["doc_id"] in {"power_of_attorney_A", "power_of_attorney_B"}]
    if len(poa_entries) != 2:
        raise CaseAuditError("expected two power of attorney entries in manifest")
    poa_filename = _entry_filename(poa_entries[0])
    if _entry_filename(poa_entries[1]) != poa_filename:
        raise CaseAuditError("power of attorney filenames must match across variants")

    for variant in variants:
        documents_dir = case_path / variant / "documents"
        if not documents_dir.is_dir():
            raise CaseAuditError(f"missing documents directory: {documents_dir}")
        files = sorted(p.name for p in documents_dir.glob("*.txt"))
        if len(files) != 7:
            raise CaseAuditError(f"expected 7 documents in {variant}, found {len(files)}")
        if len(files) != len(set(files)):
            raise CaseAuditError(f"duplicate filenames in {documents_dir}")
        for filename in files:
            if _contains_forbidden_hint(filename):
                raise CaseAuditError(f"forbidden hint in filename: {filename}")
        expected_files = _package_expected_filenames(manifest, variant)
        if files != expected_files:
            raise CaseAuditError(f"{variant} filenames do not match manifest")
        package_files[variant] = files
        package_hashes[variant] = {name: _sha256(documents_dir / name) for name in files}

    if package_files["A"] != package_files["B"]:
        raise CaseAuditError("A and B must contain the same filenames in the same order")

    for entry in manifest["documents"]:
        filename = _entry_filename(entry)
        if entry["doc_id"] == "power_of_attorney_A":
            expected_hash = entry["variant_a_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for power_of_attorney_A")
            if package_hashes["A"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for A/{filename}")
            if entry["variant_b_sha256"] is not None:
                raise CaseAuditError("power_of_attorney_A must not have B sha256")
            continue
        if entry["doc_id"] == "power_of_attorney_B":
            expected_hash = entry["variant_b_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for power_of_attorney_B")
            if package_hashes["B"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for B/{filename}")
            if entry["variant_a_sha256"] is not None:
                raise CaseAuditError("power_of_attorney_B must not have A sha256")
            continue
        expected_a = entry["variant_a_sha256"]
        expected_b = entry["variant_b_sha256"]
        if expected_a is None or expected_b is None:
            raise CaseAuditError(f"missing sha256 in manifest for {entry['doc_id']}")
        if package_hashes["A"][filename] != expected_a:
            raise CaseAuditError(f"sha256 mismatch for A/{filename}")
        if package_hashes["B"][filename] != expected_b:
            raise CaseAuditError(f"sha256 mismatch for B/{filename}")

    for filename in package_files["A"]:
        if filename == poa_filename:
            continue
        if package_hashes["A"][filename] != package_hashes["B"][filename]:
            raise CaseAuditError(f"non-authority document differs: {filename}")

    text_a = extract_document_structure(case_path / "A" / "documents" / poa_filename, "power_of_attorney_A")["text"]
    text_b = extract_document_structure(case_path / "B" / "documents" / poa_filename, "power_of_attorney_B")["text"]
    subject_a = "договоры приобретения и поставки компьютерного, серверного и сетевого оборудования"
    subject_b = "договоры технического обслуживания, ремонта и технической поддержки компьютерного, серверного и сетевого оборудования"
    if subject_a not in text_a or subject_b not in text_b:
        raise CaseAuditError("power of attorney subjects do not match expected values")
    if text_a.replace(subject_a, subject_b) != text_b:
        raise CaseAuditError("power of attorney versions differ in more than the subject clause")


def _audit_acceptance_case(case_path: Path, manifest: dict[str, Any]) -> None:
    variants = ("A", "B")
    package_files: dict[str, list[str]] = {}
    package_hashes: dict[str, dict[str, str]] = {}
    act_entries = {
        "A": next((entry for entry in manifest["documents"] if entry["doc_id"] == "acceptance_act_A"), None),
        "B": next((entry for entry in manifest["documents"] if entry["doc_id"] == "acceptance_act_B"), None),
    }
    if act_entries["A"] is None or act_entries["B"] is None:
        raise CaseAuditError("expected acceptance act entries in manifest")
    act_filename = _entry_filename(act_entries["A"])
    if _entry_filename(act_entries["B"]) != act_filename:
        raise CaseAuditError("acceptance act filenames must match across variants")

    for variant in variants:
        documents_dir = case_path / variant / "documents"
        if not documents_dir.is_dir():
            raise CaseAuditError(f"missing documents directory: {documents_dir}")
        files = sorted(p.name for p in documents_dir.glob("*.txt"))
        if len(files) != 7:
            raise CaseAuditError(f"expected 7 documents in {variant}, found {len(files)}")
        if len(files) != len(set(files)):
            raise CaseAuditError(f"duplicate filenames in {documents_dir}")
        for filename in files:
            if _contains_forbidden_hint(filename):
                raise CaseAuditError(f"forbidden hint in filename: {filename}")
        expected_files = _package_expected_filenames(manifest, variant)
        if files != expected_files:
            raise CaseAuditError(f"{variant} filenames do not match manifest")
        package_files[variant] = files
        package_hashes[variant] = {name: _sha256(documents_dir / name) for name in files}

    if package_files["A"] != package_files["B"]:
        raise CaseAuditError("A and B must contain the same filenames in the same order")

    for entry in manifest["documents"]:
        filename = _entry_filename(entry)
        if entry["doc_id"] == "acceptance_act_A":
            expected_hash = entry["variant_a_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for acceptance_act_A")
            if package_hashes["A"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for A/{filename}")
            if entry["variant_b_sha256"] is not None:
                raise CaseAuditError("acceptance_act_A must not have B sha256")
            continue
        if entry["doc_id"] == "acceptance_act_B":
            expected_hash = entry["variant_b_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for acceptance_act_B")
            if package_hashes["B"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for B/{filename}")
            if entry["variant_a_sha256"] is not None:
                raise CaseAuditError("acceptance_act_B must not have A sha256")
            continue
        expected_a = entry["variant_a_sha256"]
        expected_b = entry["variant_b_sha256"]
        if expected_a is None or expected_b is None:
            raise CaseAuditError(f"missing sha256 in manifest for {entry['doc_id']}")
        if package_hashes["A"][filename] != expected_a:
            raise CaseAuditError(f"sha256 mismatch for A/{filename}")
        if package_hashes["B"][filename] != expected_b:
            raise CaseAuditError(f"sha256 mismatch for B/{filename}")

    for filename in package_files["A"]:
        if filename == act_filename:
            continue
        if package_hashes["A"][filename] != package_hashes["B"][filename]:
            raise CaseAuditError(f"non-acceptance document differs: {filename}")

    text_a = extract_document_structure(case_path / "A" / "documents" / act_filename, "acceptance_act_A")["text"]
    text_b = extract_document_structure(case_path / "B" / "documents" / act_filename, "acceptance_act_B")["text"]
    signature_a = "[PARAGRAPH] Подпись заказчика: __________ /Кузнецов Илья Андреевич/"
    signature_b = "[PARAGRAPH] Подпись заказчика:"
    mark_a = "[PARAGRAPH] 4. Отметка о подписании: Акт подписан обеими сторонами."
    mark_b = "[PARAGRAPH] 4. Отметка о подписании:"
    if signature_a not in text_a or signature_b not in text_b:
        raise CaseAuditError("acceptance act customer signature blocks do not match expected values")
    if mark_a not in text_a or mark_b not in text_b:
        raise CaseAuditError("acceptance act signature marks do not match expected values")
    if text_a.replace(signature_a, signature_b).replace(mark_a, mark_b) != text_b:
        raise CaseAuditError("acceptance acts differ in more than the customer signature block and mark")


def _audit_notice_case(case_path: Path, manifest: dict[str, Any]) -> None:
    variants = ("A", "B")
    package_files: dict[str, list[str]] = {}
    package_hashes: dict[str, dict[str, str]] = {}

    delivery_entries = {
        "A": next((entry for entry in manifest["documents"] if entry["doc_id"] == "delivery_confirmation_A"), None),
        "B": next((entry for entry in manifest["documents"] if entry["doc_id"] == "delivery_confirmation_B"), None),
    }
    if delivery_entries["A"] is None or delivery_entries["B"] is None:
        raise CaseAuditError("expected delivery confirmation entries in manifest")
    confirmation_filename = _entry_filename(delivery_entries["A"])
    if _entry_filename(delivery_entries["B"]) != confirmation_filename:
        raise CaseAuditError("delivery confirmation filenames must match across variants")

    for variant in variants:
        documents_dir = case_path / variant / "documents"
        if not documents_dir.is_dir():
            raise CaseAuditError(f"missing documents directory: {documents_dir}")
        files = sorted(p.name for p in documents_dir.glob("*.txt"))
        if len(files) != 7:
            raise CaseAuditError(f"expected 7 documents in {variant}, found {len(files)}")
        if len(files) != len(set(files)):
            raise CaseAuditError(f"duplicate filenames in {documents_dir}")
        for filename in files:
            if _contains_forbidden_hint(filename):
                raise CaseAuditError(f"forbidden hint in filename: {filename}")
        expected_files = _package_expected_filenames(manifest, variant)
        if files != expected_files:
            raise CaseAuditError(f"{variant} filenames do not match manifest")
        package_files[variant] = files
        package_hashes[variant] = {name: _sha256(documents_dir / name) for name in files}

    if package_files["A"] != package_files["B"]:
        raise CaseAuditError("A and B must contain the same filenames in the same order")

    for entry in manifest["documents"]:
        filename = _entry_filename(entry)
        if entry["doc_id"] == "delivery_confirmation_A":
            expected_hash = entry["variant_a_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for delivery_confirmation_A")
            if package_hashes["A"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for A/{filename}")
            if entry["variant_b_sha256"] is not None:
                raise CaseAuditError("delivery_confirmation_A must not have B sha256")
            continue
        if entry["doc_id"] == "delivery_confirmation_B":
            expected_hash = entry["variant_b_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for delivery_confirmation_B")
            if package_hashes["B"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for B/{filename}")
            if entry["variant_a_sha256"] is not None:
                raise CaseAuditError("delivery_confirmation_B must not have A sha256")
            continue
        expected_a = entry["variant_a_sha256"]
        expected_b = entry["variant_b_sha256"]
        if expected_a is None or expected_b is None:
            raise CaseAuditError(f"missing sha256 in manifest for {entry['doc_id']}")
        if package_hashes["A"][filename] != expected_a:
            raise CaseAuditError(f"sha256 mismatch for A/{filename}")
        if package_hashes["B"][filename] != expected_b:
            raise CaseAuditError(f"sha256 mismatch for B/{filename}")

    for filename in package_files["A"]:
        if filename == confirmation_filename:
            continue
        if package_hashes["A"][filename] != package_hashes["B"][filename]:
            raise CaseAuditError(f"non-notice document differs: {filename}")

    text_a = extract_document_structure(case_path / "A" / "documents" / confirmation_filename, "delivery_confirmation_A")["text"]
    text_b = extract_document_structure(case_path / "B" / "documents" / confirmation_filename, "delivery_confirmation_B")["text"]
    if "19 октября 2026 г." not in text_a or "22 октября 2026 г." not in text_b:
        raise CaseAuditError("delivery confirmation dates do not match expected values")
    if text_a.replace("19 октября 2026 г.", "22 октября 2026 г.") != text_b:
        raise CaseAuditError("delivery confirmations differ in more than the delivery date")


def _audit_reconciliation_case(case_path: Path, manifest: dict[str, Any]) -> None:
    variants = ("A", "B")
    package_files: dict[str, list[str]] = {}
    package_hashes: dict[str, dict[str, str]] = {}

    invoice_entries = {
        "A": next((entry for entry in manifest["documents"] if entry["doc_id"] == "supplier_invoice_A"), None),
        "B": next((entry for entry in manifest["documents"] if entry["doc_id"] == "supplier_invoice_B"), None),
    }
    if invoice_entries["A"] is None or invoice_entries["B"] is None:
        raise CaseAuditError("expected supplier invoice entries in manifest")
    invoice_filename = _entry_filename(invoice_entries["A"])
    if _entry_filename(invoice_entries["B"]) != invoice_filename:
        raise CaseAuditError("supplier invoice filenames must match across variants")

    for variant in variants:
        documents_dir = case_path / variant / "documents"
        if not documents_dir.is_dir():
            raise CaseAuditError(f"missing documents directory: {documents_dir}")
        files = sorted(p.name for p in documents_dir.glob("*.txt"))
        if len(files) != 7:
            raise CaseAuditError(f"expected 7 documents in {variant}, found {len(files)}")
        if len(files) != len(set(files)):
            raise CaseAuditError(f"duplicate filenames in {documents_dir}")
        for filename in files:
            if _contains_forbidden_hint(filename):
                raise CaseAuditError(f"forbidden hint in filename: {filename}")
        expected_files = _package_expected_filenames(manifest, variant)
        if files != expected_files:
            raise CaseAuditError(f"{variant} filenames do not match manifest")
        package_files[variant] = files
        package_hashes[variant] = {name: _sha256(documents_dir / name) for name in files}

    if package_files["A"] != package_files["B"]:
        raise CaseAuditError("A and B must contain the same filenames in the same order")

    for entry in manifest["documents"]:
        filename = _entry_filename(entry)
        if entry["doc_id"] == "supplier_invoice_A":
            expected_hash = entry["variant_a_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for supplier_invoice_A")
            if package_hashes["A"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for A/{filename}")
            if entry["variant_b_sha256"] is not None:
                raise CaseAuditError("supplier_invoice_A must not have B sha256")
            continue
        if entry["doc_id"] == "supplier_invoice_B":
            expected_hash = entry["variant_b_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for supplier_invoice_B")
            if package_hashes["B"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for B/{filename}")
            if entry["variant_a_sha256"] is not None:
                raise CaseAuditError("supplier_invoice_B must not have A sha256")
            continue
        expected_a = entry["variant_a_sha256"]
        expected_b = entry["variant_b_sha256"]
        if expected_a is None or expected_b is None:
            raise CaseAuditError(f"missing sha256 in manifest for {entry['doc_id']}")
        if package_hashes["A"][filename] != expected_a:
            raise CaseAuditError(f"sha256 mismatch for A/{filename}")
        if package_hashes["B"][filename] != expected_b:
            raise CaseAuditError(f"sha256 mismatch for B/{filename}")

    for filename in package_files["A"]:
        if filename == invoice_filename:
            continue
        if package_hashes["A"][filename] != package_hashes["B"][filename]:
            raise CaseAuditError(f"non-reconciliation document differs: {filename}")

    text_a = extract_document_structure(case_path / "A" / "documents" / invoice_filename, "supplier_invoice_A")["text"]
    text_b = extract_document_structure(case_path / "B" / "documents" / invoice_filename, "supplier_invoice_B")["text"]
    if "Количество: 50 шт." not in text_a or "Количество: 55 шт." not in text_b:
        raise CaseAuditError("supplier invoice quantities do not match expected values")
    if "Сумма к оплате: 1 600 000 руб." not in text_a or "Сумма к оплате: 1 760 000 руб." not in text_b:
        raise CaseAuditError("supplier invoice totals do not match expected values")
    if text_a.replace("Количество: 50 шт.", "Количество: 55 шт.").replace("Сумма к оплате: 1 600 000 руб.", "Сумма к оплате: 1 760 000 руб.") != text_b:
        raise CaseAuditError("supplier invoice versions differ in more than quantity and total")


def _audit_amendment_case(case_path: Path, manifest: dict[str, Any]) -> None:
    variants = ("A", "B")
    package_files: dict[str, list[str]] = {}
    package_hashes: dict[str, dict[str, str]] = {}

    amendment_entries = {
        "A": next((entry for entry in manifest["documents"] if entry["doc_id"] == "amendment_A"), None),
        "B": next((entry for entry in manifest["documents"] if entry["doc_id"] == "amendment_B"), None),
    }
    if amendment_entries["A"] is None or amendment_entries["B"] is None:
        raise CaseAuditError("expected amendment entries in manifest")
    amendment_filename = _entry_filename(amendment_entries["A"])
    if _entry_filename(amendment_entries["B"]) != amendment_filename:
        raise CaseAuditError("amendment filenames must match across variants")

    for variant in variants:
        documents_dir = case_path / variant / "documents"
        if not documents_dir.is_dir():
            raise CaseAuditError(f"missing documents directory: {documents_dir}")
        files = sorted(p.name for p in documents_dir.glob("*.txt"))
        if len(files) != 7:
            raise CaseAuditError(f"expected 7 documents in {variant}, found {len(files)}")
        if len(files) != len(set(files)):
            raise CaseAuditError(f"duplicate filenames in {documents_dir}")
        for filename in files:
            if _contains_forbidden_hint(filename):
                raise CaseAuditError(f"forbidden hint in filename: {filename}")
        expected_files = _package_expected_filenames(manifest, variant)
        if files != expected_files:
            raise CaseAuditError(f"{variant} filenames do not match manifest")
        package_files[variant] = files
        package_hashes[variant] = {name: _sha256(documents_dir / name) for name in files}

    if package_files["A"] != package_files["B"]:
        raise CaseAuditError("A and B must contain the same filenames in the same order")

    for entry in manifest["documents"]:
        filename = _entry_filename(entry)
        if entry["doc_id"] == "amendment_A":
            expected_hash = entry["variant_a_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for amendment_A")
            if package_hashes["A"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for A/{filename}")
            if entry["variant_b_sha256"] is not None:
                raise CaseAuditError("amendment_A must not have B sha256")
            continue
        if entry["doc_id"] == "amendment_B":
            expected_hash = entry["variant_b_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for amendment_B")
            if package_hashes["B"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for B/{filename}")
            if entry["variant_a_sha256"] is not None:
                raise CaseAuditError("amendment_B must not have A sha256")
            continue
        expected_a = entry["variant_a_sha256"]
        expected_b = entry["variant_b_sha256"]
        if expected_a is None or expected_b is None:
            raise CaseAuditError(f"missing sha256 in manifest for {entry['doc_id']}")
        if package_hashes["A"][filename] != expected_a:
            raise CaseAuditError(f"sha256 mismatch for A/{filename}")
        if package_hashes["B"][filename] != expected_b:
            raise CaseAuditError(f"sha256 mismatch for B/{filename}")

    for filename in package_files["A"]:
        if filename == amendment_filename:
            continue
        if package_hashes["A"][filename] != package_hashes["B"][filename]:
            raise CaseAuditError(f"non-amendment document differs: {filename}")

    text_a = extract_document_structure(case_path / "A" / "documents" / amendment_filename, "amendment_A")["text"]
    text_b = extract_document_structure(case_path / "B" / "documents" / amendment_filename, "amendment_B")["text"]
    if "С 1 июля 2026 г." not in text_a or "С 1 августа 2026 г." not in text_b:
        raise CaseAuditError("amendment dates do not match expected values")
    if text_a.replace("С 1 июля 2026 г.", "С 1 августа 2026 г.") != text_b:
        raise CaseAuditError("amendment versions differ in more than the effective date")


def _audit_sla_case(case_path: Path, manifest: dict[str, Any]) -> None:
    variants = ("A", "B")
    package_files: dict[str, list[str]] = {}
    package_hashes: dict[str, dict[str, str]] = {}

    report_entries = {
        "A": next((entry for entry in manifest["documents"] if entry["doc_id"] == "technical_report_A"), None),
        "B": next((entry for entry in manifest["documents"] if entry["doc_id"] == "technical_report_B"), None),
    }
    if report_entries["A"] is None or report_entries["B"] is None:
        raise CaseAuditError("expected technical report entries in manifest")
    report_filename = _entry_filename(report_entries["A"])
    if _entry_filename(report_entries["B"]) != report_filename:
        raise CaseAuditError("technical report filenames must match across variants")

    for variant in variants:
        documents_dir = case_path / variant / "documents"
        if not documents_dir.is_dir():
            raise CaseAuditError(f"missing documents directory: {documents_dir}")
        files = sorted(p.name for p in documents_dir.glob("*.txt"))
        if len(files) != 7:
            raise CaseAuditError(f"expected 7 documents in {variant}, found {len(files)}")
        if len(files) != len(set(files)):
            raise CaseAuditError(f"duplicate filenames in {documents_dir}")
        for filename in files:
            if _contains_forbidden_hint(filename):
                raise CaseAuditError(f"forbidden hint in filename: {filename}")
        expected_files = _package_expected_filenames(manifest, variant)
        if files != expected_files:
            raise CaseAuditError(f"{variant} filenames do not match manifest")
        package_files[variant] = files
        package_hashes[variant] = {name: _sha256(documents_dir / name) for name in files}

    if package_files["A"] != package_files["B"]:
        raise CaseAuditError("A and B must contain the same filenames in the same order")

    for entry in manifest["documents"]:
        filename = _entry_filename(entry)
        if entry["doc_id"] == "technical_report_A":
            expected_hash = entry["variant_a_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for technical_report_A")
            if package_hashes["A"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for A/{filename}")
            if entry["variant_b_sha256"] is not None:
                raise CaseAuditError("technical_report_A must not have B sha256")
            continue
        if entry["doc_id"] == "technical_report_B":
            expected_hash = entry["variant_b_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for technical_report_B")
            if package_hashes["B"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for B/{filename}")
            if entry["variant_a_sha256"] is not None:
                raise CaseAuditError("technical_report_B must not have A sha256")
            continue
        expected_a = entry["variant_a_sha256"]
        expected_b = entry["variant_b_sha256"]
        if expected_a is None or expected_b is None:
            raise CaseAuditError(f"missing sha256 in manifest for {entry['doc_id']}")
        if package_hashes["A"][filename] != expected_a:
            raise CaseAuditError(f"sha256 mismatch for A/{filename}")
        if package_hashes["B"][filename] != expected_b:
            raise CaseAuditError(f"sha256 mismatch for B/{filename}")

    for filename in package_files["A"]:
        if filename == report_filename:
            continue
        if package_hashes["A"][filename] != package_hashes["B"][filename]:
            raise CaseAuditError(f"non-sla document differs: {filename}")

    text_a = extract_document_structure(case_path / "A" / "documents" / report_filename, "technical_report_A")["text"]
    text_b = extract_document_structure(case_path / "B" / "documents" / report_filename, "technical_report_B")["text"]
    if "Восстановление завершено в 13:59" not in text_a or "Восстановление завершено в 14:01" not in text_b:
        raise CaseAuditError("technical report recovery times do not match expected values")
    if "Длительность:" in text_a or "Длительность:" in text_b:
        raise CaseAuditError("technical report must not contain duration lines")
    if (
        text_a.replace("Восстановление завершено в 13:59", "Восстановление завершено в 14:01")
        != text_b
    ):
        raise CaseAuditError("technical reports differ in more than the recovery time")


def _audit_asset_scope_case(case_path: Path, manifest: dict[str, Any]) -> None:
    variants = ("A", "B")
    package_files: dict[str, list[str]] = {}
    package_hashes: dict[str, dict[str, str]] = {}

    inventory_entries = {
        "A": next((entry for entry in manifest["documents"] if entry["doc_id"] == "inventory_card_A"), None),
        "B": next((entry for entry in manifest["documents"] if entry["doc_id"] == "inventory_card_B"), None),
    }
    if inventory_entries["A"] is None or inventory_entries["B"] is None:
        raise CaseAuditError("expected inventory card entries in manifest")
    inventory_filename = _entry_filename(inventory_entries["A"])
    if _entry_filename(inventory_entries["B"]) != inventory_filename:
        raise CaseAuditError("inventory card filenames must match across variants")

    for variant in variants:
        documents_dir = case_path / variant / "documents"
        if not documents_dir.is_dir():
            raise CaseAuditError(f"missing documents directory: {documents_dir}")
        files = sorted(p.name for p in documents_dir.glob("*.txt"))
        if len(files) != 7:
            raise CaseAuditError(f"expected 7 documents in {variant}, found {len(files)}")
        if len(files) != len(set(files)):
            raise CaseAuditError(f"duplicate filenames in {documents_dir}")
        for filename in files:
            if _contains_forbidden_hint(filename):
                raise CaseAuditError(f"forbidden hint in filename: {filename}")
        expected_files = _package_expected_filenames(manifest, variant)
        if files != expected_files:
            raise CaseAuditError(f"{variant} filenames do not match manifest")
        package_files[variant] = files
        package_hashes[variant] = {name: _sha256(documents_dir / name) for name in files}

    if package_files["A"] != package_files["B"]:
        raise CaseAuditError("A and B must contain the same filenames in the same order")

    for entry in manifest["documents"]:
        filename = _entry_filename(entry)
        if entry["doc_id"] == "inventory_card_A":
            expected_hash = entry["variant_a_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for inventory_card_A")
            if package_hashes["A"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for A/{filename}")
            if entry["variant_b_sha256"] is not None:
                raise CaseAuditError("inventory_card_A must not have B sha256")
            continue
        if entry["doc_id"] == "inventory_card_B":
            expected_hash = entry["variant_b_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for inventory_card_B")
            if package_hashes["B"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for B/{filename}")
            if entry["variant_a_sha256"] is not None:
                raise CaseAuditError("inventory_card_B must not have A sha256")
            continue
        expected_a = entry["variant_a_sha256"]
        expected_b = entry["variant_b_sha256"]
        if expected_a is None or expected_b is None:
            raise CaseAuditError(f"missing sha256 in manifest for {entry['doc_id']}")
        if package_hashes["A"][filename] != expected_a:
            raise CaseAuditError(f"sha256 mismatch for A/{filename}")
        if package_hashes["B"][filename] != expected_b:
            raise CaseAuditError(f"sha256 mismatch for B/{filename}")

    for filename in package_files["A"]:
        if filename == inventory_filename:
            continue
        if package_hashes["A"][filename] != package_hashes["B"][filename]:
            raise CaseAuditError(f"non-asset-scope document differs: {filename}")

    text_a = extract_document_structure(case_path / "A" / "documents" / inventory_filename, "inventory_card_A")["text"]
    text_b = extract_document_structure(case_path / "B" / "documents" / inventory_filename, "inventory_card_B")["text"]
    serial_a = "NX-7421"
    serial_b = "NX-7427"
    if serial_a not in text_a or serial_b not in text_b:
        raise CaseAuditError("inventory card serial numbers do not match expected values")
    if text_a.replace(serial_a, serial_b) != text_b:
        raise CaseAuditError("inventory cards differ in more than the serial number")


def _audit_approval_chain_case(case_path: Path, manifest: dict[str, Any]) -> None:
    variants = ("A", "B")
    package_files: dict[str, list[str]] = {}
    package_hashes: dict[str, dict[str, str]] = {}

    review_entries = {
        "A": next((entry for entry in manifest["documents"] if entry["doc_id"] == "security_review_A"), None),
        "B": next((entry for entry in manifest["documents"] if entry["doc_id"] == "security_review_B"), None),
    }
    if review_entries["A"] is None or review_entries["B"] is None:
        raise CaseAuditError("expected security review entries in manifest")
    review_filename = _entry_filename(review_entries["A"])
    if _entry_filename(review_entries["B"]) != review_filename:
        raise CaseAuditError("security review filenames must match across variants")

    for variant in variants:
        documents_dir = case_path / variant / "documents"
        if not documents_dir.is_dir():
            raise CaseAuditError(f"missing documents directory: {documents_dir}")
        files = sorted(p.name for p in documents_dir.glob("*.txt"))
        if len(files) != 7:
            raise CaseAuditError(f"expected 7 documents in {variant}, found {len(files)}")
        if len(files) != len(set(files)):
            raise CaseAuditError(f"duplicate filenames in {documents_dir}")
        for filename in files:
            if _contains_forbidden_hint(filename):
                raise CaseAuditError(f"forbidden hint in filename: {filename}")
        expected_files = _package_expected_filenames(manifest, variant)
        if files != expected_files:
            raise CaseAuditError(f"{variant} filenames do not match manifest")
        package_files[variant] = files
        package_hashes[variant] = {name: _sha256(documents_dir / name) for name in files}

    if package_files["A"] != package_files["B"]:
        raise CaseAuditError("A and B must contain the same filenames in the same order")

    for entry in manifest["documents"]:
        filename = _entry_filename(entry)
        if entry["doc_id"] == "security_review_A":
            expected_hash = entry["variant_a_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for security_review_A")
            if package_hashes["A"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for A/{filename}")
            if entry["variant_b_sha256"] is not None:
                raise CaseAuditError("security_review_A must not have B sha256")
            continue
        if entry["doc_id"] == "security_review_B":
            expected_hash = entry["variant_b_sha256"]
            if expected_hash is None:
                raise CaseAuditError("missing sha256 in manifest for security_review_B")
            if package_hashes["B"][filename] != expected_hash:
                raise CaseAuditError(f"sha256 mismatch for B/{filename}")
            if entry["variant_a_sha256"] is not None:
                raise CaseAuditError("security_review_B must not have A sha256")
            continue
        expected_a = entry["variant_a_sha256"]
        expected_b = entry["variant_b_sha256"]
        if expected_a is None or expected_b is None:
            raise CaseAuditError(f"missing sha256 in manifest for {entry['doc_id']}")
        if package_hashes["A"][filename] != expected_a:
            raise CaseAuditError(f"sha256 mismatch for A/{filename}")
        if package_hashes["B"][filename] != expected_b:
            raise CaseAuditError(f"sha256 mismatch for B/{filename}")

    for filename in package_files["A"]:
        if filename == review_filename:
            continue
        if package_hashes["A"][filename] != package_hashes["B"][filename]:
            raise CaseAuditError(f"non-approval-chain document differs: {filename}")

    text_a = extract_document_structure(case_path / "A" / "documents" / review_filename, "security_review_A")["text"]
    text_b = extract_document_structure(case_path / "B" / "documents" / review_filename, "security_review_B")["text"]
    if "Результат проверки: согласовано." not in text_a or "Результат проверки: рассмотрение не завершено." not in text_b:
        raise CaseAuditError("security review results do not match expected values")
    if text_a.replace("Результат проверки: согласовано.", "Результат проверки: рассмотрение не завершено.") != text_b:
        raise CaseAuditError("security review versions differ in more than the review result")


def audit_source_fidelity(case_dir: str | Path, sources_dir: str | Path) -> dict[str, Any]:
    case_path = Path(case_dir)
    source_path = Path(sources_dir)
    manifest = _load_manifest(case_path)

    audit_case(case_path)

    missing_sources: list[str] = []
    source_hashes: dict[str, str] = {}
    for entry in manifest["documents"]:
        source_file = source_path / entry["source_file_name"]
        if not source_file.exists():
            missing_sources.append(entry["source_file_name"])
            continue
        source_hash = _sha256(source_file)
        source_hashes[entry["doc_id"]] = source_hash
        if source_hash != entry["source_sha256"]:
            raise CaseAuditError(
                f"source sha256 mismatch for {entry['doc_id']}: expected {entry['source_sha256']}, got {source_hash}"
            )
    if missing_sources:
        raise CaseAuditError(f"missing source file(s): {missing_sources}")

    for variant in ("A", "B"):
        package_dir = case_path / variant
        docs_dir = package_dir / "documents"
        for entry in _package_entries(manifest, variant):
            filename = _entry_filename(entry)
            package_file = docs_dir / filename
            actual_hash = _sha256(package_file)
            expected_hash = entry["variant_a_sha256"] if variant == "A" else entry["variant_b_sha256"]
            if actual_hash != expected_hash:
                raise CaseAuditError(f"package sha256 mismatch for {variant}/{filename}")
            if entry["doc_id"] not in source_hashes:
                raise CaseAuditError(f"source hash missing for {entry['doc_id']}")
            if entry["doc_id"] not in {"temporary_order", "order_86_A", "order_86_B"} and actual_hash != source_hashes[entry["doc_id"]]:
                raise CaseAuditError(f"non-order package file does not match source for {filename}")

    source_texts: dict[str, str] = {}
    for entry in manifest["documents"]:
        source_file = source_path / entry["source_file_name"]
        source_texts[entry["doc_id"]] = extract_document_structure(source_file, entry["doc_id"])["text"]

    for variant in ("A", "B"):
        package_dir = case_path / variant
        context_text = _context_text(package_dir)
        extracted_docs = _extract_package_docs(package_dir, manifest)
        for filename, structure in extracted_docs.items():
            if structure["text"] not in context_text:
                raise CaseAuditError(f"context does not include full text for {filename}")
        context_json = _load_context(package_dir / "context.json")
        context_docs = context_json.get("documents", [])
        expected_context_docs = len(_package_entries(manifest, variant))
        if len(context_docs) != expected_context_docs:
            raise CaseAuditError(f"context document count mismatch for {variant}")
        expected_order = [entry["doc_id"] for entry in _package_entries(manifest, variant)]
        actual_order = [doc["doc_id"] for doc in context_docs]
        if actual_order != expected_order:
            raise CaseAuditError(f"context order mismatch for {variant}")

    gold_rows = [row for row in _load_gold_rows(Path("data/gold.jsonl")) if row.get("case_id") == manifest["case_id"]]
    _validate_evidence_locators(gold_rows, source_texts)

    return {
        "case_id": manifest["case_id"],
        "documents_in_a": len(_package_expected_filenames(manifest, "A")),
        "documents_in_b": len(_package_expected_filenames(manifest, "B")),
        "source_files": len(manifest["documents"]),
    }


def _render_prompt_text(context_text: str, question_text: str, *, decision_required: bool, allowed_decisions: list[str] | None = None) -> str:
    if decision_required:
        if allowed_decisions and len(allowed_decisions) > 1:
            decision_block = "Allowed decision labels for this question (order does not matter): " + ", ".join(allowed_decisions) + "."
        else:
            decision_block = "Decision is required for this question, but do not copy the answer value into the decision field."
    else:
        decision_block = "Decision is optional for this question and will not be graded."
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "Each document in Context is wrapped as [DOCUMENT doc_id=...]. "
        "Use those doc_id values in evidence and do not invent new document labels.\n\n"
        f"{decision_block}\n\n"
        f"Context:\n{context_text}\n\n"
        f"Question:\n{question_text}\n\n"
        "Return a JSON object with the answer."
    )


def _allowed_decisions_for_question(case_id: str, question_id: str, decisions: list[str], *, decision_required: bool) -> list[str]:
    if not decision_required:
        return []
    case_options = DECISION_LABEL_OPTIONS.get(case_id, {})
    if question_id in case_options:
        return list(case_options[question_id])
    unique: list[str] = []
    for decision in decisions:
        if decision not in unique:
            unique.append(decision)
    if len(unique) >= 2:
        return unique
    if unique:
        companion = _derive_companion_decision_label(unique[0])
        if companion not in unique:
            return [companion, unique[0]]
    return unique


def _allowed_code_values_for_question(case_id: str, question_id: str, answer_type: str | None, rows: list[dict[str, Any]]) -> list[str]:
    if (case_id, question_id) == ("approval_chain_009", "Q9"):
        return list(CODE_SET_VALUES)
    if answer_type != "code_set":
        return []
    values: list[str] = []
    for row in rows:
        normalized = row.get("answer_normalized")
        if isinstance(normalized, list):
            items = normalized
        elif isinstance(normalized, str):
            items = [normalized]
        else:
            items = []
        for item in items:
            text = str(item).strip()
            if text and text not in values:
                values.append(text)
    return values


def _allowed_answer_values_for_question(
    case_id: str,
    question_id: str,
    answer_type: str | None,
    rows: list[dict[str, Any]],
    *,
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    if answer_type == "categorical":
        if (case_id, question_id) in {
            ("acceptance_004", "Q13"),
            ("amendment_007", "Q12"),
            ("asset_scope_010", "Q12"),
            ("authority_003", "Q13"),
            ("notice_005", "Q12"),
            ("reconciliation_006", "Q12"),
            ("sla_008", "Q12"),
        }:
            if manifest is None:
                return []
            return _allowed_doc_kind_values(manifest)
        if (case_id, question_id) == ("authority_003", "Q1"):
            return list(ROLE_ENTITY_VALUES)
        if (case_id, question_id) == ("asset_scope_010", "Q13"):
            return list(IDENTIFIER_KIND_VALUES)
        if (case_id, question_id) in {
            ("acceptance_004", "Q3"),
            ("amendment_007", "Q2"),
            ("authority_003", "Q2"),
            ("notice_005", "Q2"),
        }:
            return list(CONTRACT_SUBJECT_VALUES)
        if (case_id, question_id) == ("sla_008", "Q9"):
            return list(EVENT_KIND_VALUES)
        values = []
        for row in rows:
            normalized = row.get("answer_normalized")
            if isinstance(normalized, str):
                text = normalized.strip()
                if text and text not in values:
                    values.append(text)
        return values if len(values) >= 2 else []
    if answer_type != "status":
        return []
    values: list[str] = []
    for row in rows:
        normalized = row.get("answer_normalized")
        if isinstance(normalized, str):
            try:
                text = normalize_answer_value("status", normalized)
            except Exception:
                text = normalized.strip().rstrip(".,;:!?").lower()
        elif isinstance(normalized, (int, float, bool)):
            try:
                text = normalize_answer_value("status", normalized)
            except Exception:
                text = str(normalized).strip().lower()
        else:
            text = ""
        if text and text not in values:
            values.append(text)
    if len(values) < 2:
        return []
    return sorted(values, key=lambda item: item)


def _effective_answer_type(case_id: str, question_id: str, answer_type: str | None) -> str | None:
    override = QUESTION_ANSWER_TYPE_OVERRIDES.get((case_id, question_id))
    if override:
        return override
    return answer_type


def _load_question_texts(case_dir: Path, gold_rows: list[dict[str, Any]]) -> dict[str, str]:
    question_texts: dict[str, str] = {}
    for row in gold_rows:
        question_text = row.get("question")
        if isinstance(question_text, str) and question_text.strip():
            question_texts[row["question_id"]] = question_text.strip()
    if question_texts:
        return question_texts
    questions_path = case_dir / "questions.json"
    if not questions_path.exists():
        raise CaseAuditError(f"missing question text in gold and no fallback file: {questions_path}")
    raw = _load_json(questions_path)
    return {row["question_id"]: row["question"] for row in raw["questions"]}


def prepare_prompts(case_dir: str | Path, gold_path: str | Path, output_dir: str | Path) -> dict[str, int]:
    case_path = Path(case_dir)
    manifest = _load_manifest(case_path)
    case_id = _case_id(manifest)
    gold_rows = _load_gold_rows(Path(gold_path))
    case_gold_rows = [row for row in gold_rows if row.get("case_id") == case_id]
    if not case_gold_rows:
        raise CaseAuditError(f"no gold rows found for case {case_id}")
    question_texts = _load_question_texts(case_path, case_gold_rows)
    decisions_by_question: dict[str, list[str]] = {}
    decision_required_by_question: dict[str, bool] = {}
    answer_type_by_question: dict[str, str | None] = {}
    code_values_by_question: dict[str, list[str]] = {}
    answer_values_by_question: dict[str, list[str]] = {}
    for row in case_gold_rows:
        qid = row["question_id"]
        decisions_by_question.setdefault(qid, [])
        if row.get("decision") not in decisions_by_question[qid]:
            decisions_by_question[qid].append(row["decision"])
        decision_required_by_question[qid] = bool(row.get("decision_required", True))
        answer_type_by_question[qid] = row.get("answer_type")
    for qid in {row["question_id"] for row in case_gold_rows}:
        effective_answer_type = _effective_answer_type(case_id, qid, answer_type_by_question.get(qid))
        code_values_by_question[qid] = _allowed_code_values_for_question(
            case_id,
            qid,
            effective_answer_type,
            [row for row in case_gold_rows if row["question_id"] == qid],
        )
        answer_values_by_question[qid] = _allowed_answer_values_for_question(
            case_id,
            qid,
            effective_answer_type,
            [row for row in case_gold_rows if row["question_id"] == qid],
            manifest=manifest,
        )
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    variants = tuple(variant for variant in ("A", "B", "C") if (case_path / variant).is_dir())
    if not variants:
        raise CaseAuditError(f"no variant directories found for case {case_id}")

    contexts: dict[str, dict[str, Any]] = {}
    for variant in variants:
        contexts[variant] = write_context_files(case_path / variant, manifest)

    grouped: dict[str, list[dict[str, Any]]] = {variant: [] for variant in variants}
    grouped["all"] = []
    for row in case_gold_rows:
        variant = row["variant_id"]
        context_text = contexts[variant]["text"]
        question_text = question_texts.get(row["question_id"])
        if question_text is None:
            raise CaseAuditError(f"missing question text for {row['question_id']}")
        prompt = _render_prompt_text(
            context_text,
            question_text,
            decision_required=decision_required_by_question.get(row["question_id"], True),
            allowed_decisions=_allowed_decisions_for_question(
                case_id,
                row["question_id"],
                sorted(decisions_by_question.get(row["question_id"], [])),
                decision_required=decision_required_by_question.get(row["question_id"], True),
            ),
        )
        response_schema = copy.deepcopy(EXPECTED_OUTPUT_SCHEMA)
        effective_answer_type = _effective_answer_type(case_id, row["question_id"], row.get("answer_type"))
        response_schema.update(
            {
                "case_id": row["case_id"],
                "variant_id": variant,
                "question_id": row["question_id"],
                "answer_type": effective_answer_type,
                "decision_required": bool(row.get("decision_required", True)),
                "allowed_decision_labels": _allowed_decisions_for_question(
                    case_id,
                    row["question_id"],
                    decisions_by_question.get(row["question_id"], []),
                    decision_required=bool(row.get("decision_required", True)),
                ),
                "allowed_answer_values": answer_values_by_question.get(row["question_id"], []),
                "allowed_code_values": code_values_by_question.get(row["question_id"], []),
            }
        )
        task = {
            "case_id": row["case_id"],
            "variant_id": variant,
            "question_id": row["question_id"],
            "answer_type": effective_answer_type,
            "decision_required": bool(row.get("decision_required", True)),
            "prompt": prompt,
            "system_prompt": SYSTEM_PROMPT,
            "response_schema": response_schema,
        }
        grouped[variant].append(task)
        grouped["all"].append(task)

    for name, tasks in grouped.items():
        target = output_path / f"{case_id}_{name}.jsonl"
        with target.open("w", encoding="utf-8") as handle:
            for task in tasks:
                handle.write(json.dumps(task, ensure_ascii=False) + "\n")

    return {name: len(tasks) for name, tasks in grouped.items()}
