from __future__ import annotations

import hashlib
import json
from pathlib import Path


CASE_DIR = Path('data/cases/asset_scope_010')
SOURCE_DIR = Path('data/source_documents/asset_scope_010')
PROMPTS_DIR = Path('prompts')
SNAPSHOT_PATH = CASE_DIR / 'asset_scope_010_gold_snapshot.jsonl'
REVIEW_PATH = CASE_DIR / 'asset_scope_010_gold_review.jsonl'


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open('r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _hash_map(directory: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for file_path in sorted(directory.iterdir()):
        if file_path.is_file():
            hashes[file_path.name] = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return hashes


def test_asset_scope_case_has_seven_documents_and_prompts():
    assert SNAPSHOT_PATH.exists()
    assert REVIEW_PATH.exists()

    source_files = sorted(p.name for p in SOURCE_DIR.iterdir() if p.is_file())
    assert len(source_files) == 8

    hashes_a = _hash_map(CASE_DIR / 'A' / 'documents')
    hashes_b = _hash_map(CASE_DIR / 'B' / 'documents')
    assert len(hashes_a) == len(hashes_b) == 7
    differing = [name for name in hashes_a if hashes_a[name] != hashes_b[name]]
    assert differing == ['03_Инвентарная_карточка.txt']

    card_a = (CASE_DIR / 'A' / 'documents' / '03_Инвентарная_карточка.txt').read_text(encoding='utf-8')
    card_b = (CASE_DIR / 'B' / 'documents' / '03_Инвентарная_карточка.txt').read_text(encoding='utf-8')
    assert card_a != card_b
    assert card_a.replace('NX-7421', 'NX-7427') == card_b

    prompt_a_rows = _read_jsonl(PROMPTS_DIR / 'asset_scope_010_A.jsonl')
    prompt_b_rows = _read_jsonl(PROMPTS_DIR / 'asset_scope_010_B.jsonl')
    prompt_all_rows = _read_jsonl(PROMPTS_DIR / 'asset_scope_010_all.jsonl')
    assert len(prompt_a_rows) == 16
    assert len(prompt_b_rows) == 16
    assert len(prompt_all_rows) == 32

    prompt_head = prompt_a_rows[0]['prompt'].split('Context:', 1)[0]
    assert 'gold_status' not in prompt_head
    assert 'required_evidence' not in prompt_head
    assert 'must_change_from_other_variant' not in prompt_head
    assert 'answer_normalized' not in prompt_head
    assert '[DOCUMENT doc_id=inventory_card_A]' in prompt_a_rows[0]['prompt']
    assert '[DOCUMENT doc_id=inventory_card_B]' in prompt_b_rows[0]['prompt']

    keys_all = {(row['case_id'], row['variant_id'], row['question_id']) for row in prompt_all_rows}
    assert len(keys_all) == 32
    assert len({row['question_id'] for row in prompt_all_rows}) == 16


def test_asset_scope_snapshot_has_required_counts_and_decisions():
    snapshot_rows = [row for row in _read_jsonl(SNAPSHOT_PATH) if row['case_id'] == 'asset_scope_010']
    review_rows = [row for row in _read_jsonl(REVIEW_PATH) if row['case_id'] == 'asset_scope_010']

    assert len(snapshot_rows) == 32
    assert len(review_rows) == 32
    assert {row['variant_id'] for row in snapshot_rows} == {'A', 'B'}
    assert {row['question_id'] for row in snapshot_rows} == {f'Q{i}' for i in range(1, 17)}

    by_qid: dict[str, dict[str, dict]] = {}
    for row in snapshot_rows:
        by_qid.setdefault(row['question_id'], {})[row['variant_id']] = row

    assert by_qid['Q1']['A']['answer_type'] == 'status'
    assert by_qid['Q1']['A']['answer_normalized'] == 'ООО «ТехРесурс»'
    assert by_qid['Q2']['A']['answer_normalized'] == 'ООО «Северный контур»'
    assert by_qid['Q3']['A']['answer_type'] == 'money'
    assert by_qid['Q3']['A']['answer_normalized'] == 300000
    assert by_qid['Q4']['A']['answer_normalized'] == 'NX-7421'
    assert by_qid['Q5']['A']['answer_normalized'] == 'DB-1'
    assert by_qid['Q6']['A']['answer_normalized'] == 'NX-7421'
    assert by_qid['Q6']['B']['answer_normalized'] == 'NX-7427'
    assert by_qid['Q6']['A']['decision'] == 'inventory_serial_nx_7421'
    assert by_qid['Q6']['B']['decision'] == 'inventory_serial_nx_7427'
    assert by_qid['Q6']['A']['decision_required'] is False
    assert by_qid['Q6']['A']['required_evidence'] == ['inventory_card_A#NX-7421']
    assert by_qid['Q6']['B']['required_evidence'] == ['inventory_card_B#NX-7427']
    assert by_qid['Q6']['A']['rationale'] == 'В инвентарной карточке сервера DB-1 указан серийный номер NX-7421.'
    assert by_qid['Q6']['B']['rationale'] == 'В инвентарной карточке сервера DB-1 указан серийный номер NX-7427.'
    assert by_qid['Q7']['A']['rationale'] == 'Серийный номер NX-7421 из инвентарной карточки совпадает с номером NX-7421 в Перечне.'
    assert by_qid['Q7']['B']['rationale'] == 'Серийный номер NX-7427 из инвентарной карточки не совпадает с номером NX-7421 в Перечне.'
    assert by_qid['Q7']['A']['decision_required'] is True
    assert by_qid['Q8']['A']['decision_required'] is True
    assert by_qid['Q8']['A']['required_evidence'] == [
        'maintenance_contract#Абонентская плата включает диагностику и ремонт оборудования, включённого в Перечень обслуживаемого оборудования.',
        'maintenance_contract#Оборудование считается включённым в Перечень при совпадении серийного номера производителя с номером, указанным в Перечне.',
        'covered_equipment_list#NX-7421',
        'inventory_card_A#NX-7421',
        'repair_request#сервер DB-1',
    ]
    assert by_qid['Q8']['B']['required_evidence'] == [
        'maintenance_contract#Абонентская плата включает диагностику и ремонт оборудования, включённого в Перечень обслуживаемого оборудования.',
        'maintenance_contract#Оборудование считается включённым в Перечень при совпадении серийного номера производителя с номером, указанным в Перечне.',
        'covered_equipment_list#NX-7421',
        'inventory_card_B#NX-7427',
        'repair_request#сервер DB-1',
    ]
    assert by_qid['Q8']['A']['rationale'] == 'Серийный номер NX-7421 из инвентарной карточки соответствует Перечню, поэтому ремонт входит в абонентскую плату.'
    assert by_qid['Q8']['B']['rationale'] == 'Серийный номер NX-7427 из инвентарной карточки не соответствует Перечню, поэтому ремонт не входит в абонентскую плату.'
    assert by_qid['Q9']['A']['answer_type'] == 'date'
    assert by_qid['Q9']['A']['answer_normalized'] == '2026-11-21'
    assert by_qid['Q10']['A']['answer_normalized'] is True
    assert by_qid['Q11']['A']['answer_normalized'] == 180000
    assert by_qid['Q12']['A']['answer_normalized'] == 'inventory_card'
    assert by_qid['Q12']['B']['answer_normalized'] == 'inventory_card'
    assert by_qid['Q12']['A']['required_evidence'] == [
        'inventory_card_A#Наименование: сервер DB-1; Серийный номер: NX-7421'
    ]
    assert by_qid['Q12']['B']['required_evidence'] == [
        'inventory_card_B#Наименование: сервер DB-1; Серийный номер: NX-7427'
    ]
    assert by_qid['Q13']['A']['answer_type'] == 'categorical'
    assert by_qid['Q13']['A']['answer_normalized'] == 'manufacturer_serial_identifier'
    assert by_qid['Q14']['A']['answer_normalized'] is False
    assert by_qid['Q14']['B']['answer_normalized'] is True
    assert by_qid['Q14']['A']['required_evidence'] == [
        'maintenance_contract#Абонентская плата включает диагностику и ремонт оборудования, включённого в Перечень обслуживаемого оборудования.',
        'maintenance_contract#Оборудование считается включённым в Перечень при совпадении серийного номера производителя с номером, указанным в Перечне.',
        'maintenance_contract#Работы на оборудовании, отсутствующем в Перечне, оплачиваются отдельно на основании подписанного акта и счёта.',
        'covered_equipment_list#NX-7421',
        'inventory_card_A#NX-7421',
        'repair_act#Работы приняты заказчиком',
    ]
    assert by_qid['Q14']['B']['required_evidence'] == [
        'maintenance_contract#Абонентская плата включает диагностику и ремонт оборудования, включённого в Перечень обслуживаемого оборудования.',
        'maintenance_contract#Оборудование считается включённым в Перечень при совпадении серийного номера производителя с номером, указанным в Перечне.',
        'maintenance_contract#Работы на оборудовании, отсутствующем в Перечне, оплачиваются отдельно на основании подписанного акта и счёта.',
        'covered_equipment_list#NX-7421',
        'inventory_card_B#NX-7427',
        'repair_act#Работы приняты заказчиком',
    ]
    assert by_qid['Q14']['A']['rationale'] == 'Оборудование с серийным номером NX-7421 включено в Перечень, поэтому отдельная оплата ремонта не требуется.'
    assert by_qid['Q14']['B']['rationale'] == 'Оборудование с серийным номером NX-7427 не включено в Перечень, поэтому ремонт оплачивается отдельно.'
    assert by_qid['Q15']['A']['answer_normalized'] is False
    assert by_qid['Q15']['B']['answer_normalized'] is True
    assert by_qid['Q15']['A']['required_evidence'] == [
        'maintenance_contract#Абонентская плата включает диагностику и ремонт оборудования, включённого в Перечень обслуживаемого оборудования.',
        'maintenance_contract#Оборудование считается включённым в Перечень при совпадении серийного номера производителя с номером, указанным в Перечне.',
        'maintenance_contract#Работы на оборудовании, отсутствующем в Перечне, оплачиваются отдельно на основании подписанного акта и счёта.',
        'covered_equipment_list#NX-7421',
        'inventory_card_A#NX-7421',
        'repair_act#Работы приняты заказчиком',
        'repair_invoice#Основание: договор № ТР-11/26 и акт выполненных ремонтных работ № 21-11/26',
    ]
    assert by_qid['Q15']['B']['required_evidence'] == [
        'maintenance_contract#Абонентская плата включает диагностику и ремонт оборудования, включённого в Перечень обслуживаемого оборудования.',
        'maintenance_contract#Оборудование считается включённым в Перечень при совпадении серийного номера производителя с номером, указанным в Перечне.',
        'maintenance_contract#Работы на оборудовании, отсутствующем в Перечне, оплачиваются отдельно на основании подписанного акта и счёта.',
        'covered_equipment_list#NX-7421',
        'inventory_card_B#NX-7427',
        'repair_act#Работы приняты заказчиком',
        'repair_invoice#Основание: договор № ТР-11/26 и акт выполненных ремонтных работ № 21-11/26',
    ]
    assert by_qid['Q15']['A']['rationale'] == 'Оборудование с серийным номером NX-7421 включено в Перечень, поэтому отдельный счёт не имеет договорного основания.'
    assert by_qid['Q15']['B']['rationale'] == 'Оборудование с серийным номером NX-7427 не включено в Перечень, а акт и счёт оформлены для отдельной оплаты.'
    assert by_qid['Q16']['A']['answer_normalized'] is False
    assert by_qid['Q16']['B']['answer_normalized'] is True
    assert by_qid['Q16']['A']['required_evidence'] == [
        'maintenance_contract#Абонентская плата включает диагностику и ремонт оборудования, включённого в Перечень обслуживаемого оборудования.',
        'maintenance_contract#Оборудование считается включённым в Перечень при совпадении серийного номера производителя с номером, указанным в Перечне.',
        'maintenance_contract#Работы на оборудовании, отсутствующем в Перечне, оплачиваются отдельно на основании подписанного акта и счёта.',
        'covered_equipment_list#NX-7421',
        'inventory_card_A#NX-7421',
        'repair_act#Работы приняты заказчиком',
        'repair_invoice#Сумма к оплате: 180 000 руб.',
        'payment_request#Пакет направлен на проверку и оплату',
    ]
    assert by_qid['Q16']['B']['required_evidence'] == [
        'maintenance_contract#Абонентская плата включает диагностику и ремонт оборудования, включённого в Перечень обслуживаемого оборудования.',
        'maintenance_contract#Оборудование считается включённым в Перечень при совпадении серийного номера производителя с номером, указанным в Перечне.',
        'maintenance_contract#Работы на оборудовании, отсутствующем в Перечне, оплачиваются отдельно на основании подписанного акта и счёта.',
        'covered_equipment_list#NX-7421',
        'inventory_card_B#NX-7427',
        'repair_act#Работы приняты заказчиком',
        'repair_invoice#Сумма к оплате: 180 000 руб.',
        'payment_request#Пакет направлен на проверку и оплату',
    ]
    assert by_qid['Q16']['A']['rationale'] == 'Оборудование с серийным номером NX-7421 включено в Перечень, поэтому отдельную оплату по этому пакету одобрять нельзя.'
    assert by_qid['Q16']['B']['rationale'] == 'Оборудование с серийным номером NX-7427 не включено в Перечень, а пакет документов оформлен для отдельной оплаты.'

    flip_questions = {row['question_id'] for row in snapshot_rows if row['must_change_from_other_variant']}
    assert flip_questions == {'Q6', 'Q7', 'Q8', 'Q14', 'Q15', 'Q16'}
    invariant_questions = {row['question_id'] for row in snapshot_rows if not row['must_change_from_other_variant']}
    assert invariant_questions == {'Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q10', 'Q11', 'Q12', 'Q13'}

    qids_false = {'Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6', 'Q9', 'Q10', 'Q11', 'Q12', 'Q13'}
    assert {row['question_id'] for row in snapshot_rows if row['decision_required'] is False} == qids_false
    assert {row['question_id'] for row in snapshot_rows if row['decision_required'] is True} == {'Q7', 'Q8', 'Q14', 'Q15', 'Q16'}


def test_asset_scope_has_no_cross_variant_evidence():
    snapshot_rows = [row for row in _read_jsonl(SNAPSHOT_PATH) if row['case_id'] == 'asset_scope_010']

    for row in snapshot_rows:
        evidence_items = list(row['required_evidence']) + list(row['supporting_evidence'])
        if row['variant_id'] == 'A':
            assert all('inventory_card_B' not in item for item in evidence_items)
        else:
            assert all('inventory_card_A' not in item for item in evidence_items)

    common_files = [
        '01_Договор_технического_обслуживания.txt',
        '02_Перечень_обслуживаемого_оборудования.txt',
        '04_Заявка_на_аварийный_ремонт.txt',
        '05_Акт_выполненных_ремонтных_работ.txt',
        '06_Счёт_за_аварийный_ремонт.txt',
        '07_Заявка_на_оплату_ремонта.txt',
    ]
    for name in common_files:
        assert (CASE_DIR / 'A' / 'documents' / name).read_text(encoding='utf-8') == (
            CASE_DIR / 'B' / 'documents' / name
        ).read_text(encoding='utf-8')

    card_a = (CASE_DIR / 'A' / 'documents' / '03_Инвентарная_карточка.txt').read_text(encoding='utf-8')
    card_b = (CASE_DIR / 'B' / 'documents' / '03_Инвентарная_карточка.txt').read_text(encoding='utf-8')
    assert 'NX-7421' in card_a
    assert 'NX-7427' in card_b
    assert 'NX-7421' not in card_b
    assert 'NX-7427' not in card_a

    assert any(row['question_id'] == 'Q14' and row['variant_id'] == 'A' and row['answer_normalized'] is False for row in snapshot_rows)
    assert any(row['question_id'] == 'Q14' and row['variant_id'] == 'B' and row['answer_normalized'] is True for row in snapshot_rows)
    assert any(row['question_id'] == 'Q15' and row['variant_id'] == 'A' and row['answer_normalized'] is False for row in snapshot_rows)
    assert any(row['question_id'] == 'Q15' and row['variant_id'] == 'B' and row['answer_normalized'] is True for row in snapshot_rows)
    assert any(row['question_id'] == 'Q16' and row['variant_id'] == 'A' and row['answer_normalized'] is False for row in snapshot_rows)
    assert any(row['question_id'] == 'Q16' and row['variant_id'] == 'B' and row['answer_normalized'] is True for row in snapshot_rows)
