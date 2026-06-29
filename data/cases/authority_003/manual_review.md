# authority_003 manual review

## 1. Краткое описание кейса

- Основной нормативный конфликт: договор от имени общества может подписать только генеральный директор или представитель в пределах доверенности.
- Единственное различие A/B: предмет доверенности.
- Дата договора: 12 ноября 2026 г.
- Денежный предел в A: 1 500 000 руб.
- Денежный предел в B: 1 500 000 руб.
- Правильный итоговый статус A: подписан в пределах представленной доверенности.
- Правильный итоговый статус B: подписан вне пределов представленной доверенности.

## 2. Полные тексты документов
### `contract_policy`
```text
ООО «Северный контур»
ПОЛОЖЕНИЕ О ПОРЯДКЕ ЗАКЛЮЧЕНИЯ ДОГОВОРОВ № ПЗД-03/2026
1. Общие положения
1.1. Договоры от имени Общества подписывает генеральный директор либо представитель, действующий в пределах предоставленных ему полномочий.
1.2. Содержание полномочий представителя определяется доверенностью.
1.3. Финансовое и юридическое согласование подтверждает проверку бюджета и условий проекта договора.
1.4. Право подписи определяется отдельно от процедуры внутреннего согласования.
1.5. Документы об исполнении договора оформляются после совершения сделки.
```

### `power_of_attorney_A`
```text
ООО «Северный контур»
ДОВЕРЕННОСТЬ № 17/П-26
г. Екатеринбург
1 сентября 2026 г.
Действует по 31 декабря 2026 г. включительно.
ООО «Северный контур» в лице генерального директора Орлова Дмитрия Александровича доверяет директору Уральского филиала Смирнову Игорю Петровичу
подписывать от имени Общества договоры приобретения и поставки компьютерного, серверного и сетевого оборудования стоимостью до 1 500 000 руб. включительно.
```

### `power_of_attorney_B`
```text
ООО «Северный контур»
ДОВЕРЕННОСТЬ № 17/П-26
г. Екатеринбург
1 сентября 2026 г.
Действует по 31 декабря 2026 г. включительно.
ООО «Северный контур» в лице генерального директора Орлова Дмитрия Александровича доверяет директору Уральского филиала Смирнову Игорю Петровичу
подписывать от имени Общества договоры технического обслуживания, ремонта и технической поддержки компьютерного, серверного и сетевого оборудования стоимостью до 1 500 000 руб. включительно.
```

### `service_memo`
```text
СЛУЖЕБНАЯ ЗАПИСКА № 11/11-26
1 ноября 2026 г.
От: начальника Уральского филиала
Кому: коммерческому директору
Просим приобрести сетевое оборудование для Уральского филиала на сумму 1 180 000 руб. и передать проект договора на согласование.
```

### `authority_approval_sheet`
```text
ЛИСТ СОГЛАСОВАНИЯ ПРОЕКТА ДОГОВОРА
Финансовый директор: финансирование подтверждено.
Юридическая служба: условия и форма проекта договора проверены.
Директор Уральского филиала: передать договор на подписание директору Уральского филиала.
```

### `authority_contract`
```text
ДОГОВОР ПОСТАВКИ № УФ-12/11-26
Дата: 12 ноября 2026 г.
Поставщик: ООО «ИнфраСеть».
Покупатель: ООО «Северный контур».
Предмет договора: поставка сетевого оборудования для Уральского филиала.
Сумма договора: 1 180 000 руб.
От имени покупателя договор подписал директор Уральского филиала Смирнов Игорь Петрович.
Договор подписан сторонами.
```

### `transfer_act`
```text
АКТ ПРИЕМА-ПЕРЕДАЧИ ОБОРУДОВАНИЯ № 1/12-11-26
Дата: 18 ноября 2026 г.
По договору № УФ-12/11-26 поставщик передал, а покупатель принял сетевое оборудование для Уральского филиала.
Передача подтверждена по номенклатуре, количеству и состоянию на момент приемки.
Стороны претензий по факту передачи не имеют.
```

### `authority_payment_request`
```text
ЗАЯВКА НА ОПЛАТУ № 18/11-26/П
Просим оплатить 1 180 000 руб. по договору № УФ-12/11-26.
Основание: договор, акт приёма-передачи и лист согласования.
Платежная заявка оформлена для исполнения договорного обязательства.
```

### Точная строка различия в доверенности
- A: `подписывать от имени Общества договоры приобретения и поставки компьютерного, серверного и сетевого оборудования стоимостью до 1 500 000 руб. включительно.`
- B: `подписывать от имени Общества договоры технического обслуживания, ремонта и технической поддержки компьютерного, серверного и сетевого оборудования стоимостью до 1 500 000 руб. включительно.`

## 3. Таблица всех вопросов

| Q | Полный текст вопроса | answer type | decision_required | skill | flip/invariant | gold answer A | gold answer B | gold decision A | gold decision B | required evidence A | required evidence B | Краткое объяснение |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Q1 | Кто подписал договор от имени покупателя? | status | false | signatory_extraction | invariant | director_ural_branch | director_ural_branch | signed_by_branch_director | signed_by_branch_director | authority_contract#buyer_signatory | authority_contract#buyer_signatory | Подписантом со стороны покупателя указан директор Уральского филиала. |
| Q2 | Каков предмет договора? | status | false | subject_extraction | invariant | supply_of_network_equipment_for_ural_branch | supply_of_network_equipment_for_ural_branch | network_equipment_supply_contract | network_equipment_supply_contract | authority_contract#subject | authority_contract#subject | Предмет договора прямо сформулирован как поставка сетевого оборудования для Уральского филиала. |
| Q3 | Какова сумма договора? | money | false | amount_extraction | invariant | 1180000 | 1180000 | contract_amount_1180000 | contract_amount_1180000 | authority_contract#amount | authority_contract#amount | Сумма договора указана как 1 180 000 руб. |
| Q4 | Действовала ли доверенность на дату договора? | boolean | true | temporal_extraction | invariant | True | True | poa_valid_on_contract_date | poa_valid_on_contract_date | power_of_attorney_A#limit_term; authority_contract#date | power_of_attorney_B#limit_term; authority_contract#date | Доверенность действовала с 1 сентября по 31 декабря 2026 г., а договор заключён 12 ноября 2026 г. |
| Q5 | Соблюдён ли денежный предел доверенности? | boolean | true | limit_check | invariant | True | True | power_of_attorney_limit_respected | power_of_attorney_limit_respected | power_of_attorney_A#limit_term; authority_contract#amount | power_of_attorney_B#limit_term; authority_contract#amount | Сумма договора 1 180 000 руб. не превышает лимит доверенности 1 500 000 руб. |
| Q6 | Охватывает ли доверенность договор поставки сетевого оборудования? | boolean | true | authority_scope | flip | True | False | within_poa_subject_scope | outside_poa_subject_scope | power_of_attorney_A#subject_scope; authority_contract#subject | power_of_attorney_B#subject_scope; authority_contract#subject | В версии A предмет доверенности включает поставку оборудования, в версии B — только обслуживание, ремонт и поддержку. |
| Q7 | Действовал ли директор филиала в пределах представленной доверенности? | boolean | true | authority_scope | flip | True | False | within_presented_authority | outside_presented_authority | power_of_attorney_A#subject_scope; authority_contract#buyer_signatory; authority_contract#subject | power_of_attorney_B#subject_scope; authority_contract#buyer_signatory; authority_contract#subject | В версии A договор соответствует предмету доверенности, в версии B выходит за его пределы. |
| Q8 | Достаточно ли листа согласования для установления полномочий подписанта? | boolean | true | authority_vs_approval | invariant | False | False | approval_sheet_not_enough_for_authority | approval_sheet_not_enough_for_authority | authority_approval_sheet#finance_confirmed; authority_approval_sheet#legal_reviewed; contract_policy#authority_defined | authority_approval_sheet#finance_confirmed; authority_approval_sheet#legal_reviewed; contract_policy#authority_defined | Лист согласования подтверждает внутреннюю проверку, но не определяет полномочия представителя. |
| Q9 | Подтверждает ли подписание договора само по себе наличие полномочий? | boolean | true | authority_vs_signature | invariant | False | False | signature_alone_not_proof_of_authority | signature_alone_not_proof_of_authority | contract_policy#signatory_rule; contract_policy#authority_defined; authority_contract#buyer_signatory | contract_policy#signatory_rule; contract_policy#authority_defined; authority_contract#buyer_signatory | Подписание договора показывает факт подписи, но полномочия определяются доверенностью. |
| Q10 | Подтверждает ли акт фактическую передачу оборудования? | boolean | true | execution_confirmation | invariant | True | True | act_confirms_transfer | act_confirms_transfer | transfer_act#transfer_confirmed | transfer_act#transfer_confirmed | Акт прямо фиксирует передачу и приёмку оборудования. |
| Q11 | Устраняет ли последующее исполнение вопрос о пределах доверенности? | boolean | true | post_execution_logic | invariant | False | False | post_execution_does_not_extend_authority | post_execution_does_not_extend_authority | contract_policy#post_execution; authority_contract#buyer_signatory; transfer_act#transfer_confirmed | contract_policy#post_execution; authority_contract#buyer_signatory; transfer_act#transfer_confirmed | Исполнение договора происходит после сделки и не расширяет уже определённые полномочия. |
| Q12 | Требовалось ли отдельное подписание или подтверждение со стороны генерального директора исходя из представленного пакета? | boolean | true | ceo_confirmation | flip | False | True | no_separate_ceo_confirmation_required | separate_ceo_confirmation_required | power_of_attorney_A#subject_scope; authority_contract#subject; contract_policy#authority_defined | power_of_attorney_B#subject_scope; authority_contract#subject; contract_policy#authority_defined | В версии A доверенность покрывает сделку, в версии B для такой сделки понадобилось бы отдельное подтверждение. |
| Q13 | Какой документ непосредственно определяет предмет полномочий директора филиала? | status | false | authority_document | invariant | power_of_attorney | power_of_attorney | power_of_attorney_is_controlling_document | power_of_attorney_is_controlling_document | contract_policy#authority_defined; power_of_attorney_A#subject_scope; power_of_attorney_B#subject_scope | contract_policy#authority_defined; power_of_attorney_A#subject_scope; power_of_attorney_B#subject_scope | Содержание полномочий представителя определяется доверенностью. |
| Q14 | Каков правильный статус подписания договора? | status | true | signing_status | flip | signed_within_presented_authority | signed_outside_presented_authority | signed_within_presented_authority | signed_outside_presented_authority | authority_contract#buyer_signatory; power_of_attorney_A#subject_scope; authority_contract#subject | authority_contract#buyer_signatory; power_of_attorney_B#subject_scope; authority_contract#subject | В версии A подпись укладывается в доверенность, в версии B — выходит за её пределы. |
| Q15 | Какое обстоятельство является решающим: срок, сумма или предмет доверенности? | status | false | authority_factor | invariant | subject | subject | subject_is_decisive | subject_is_decisive | contract_policy#authority_defined; power_of_attorney_A#subject_scope; power_of_attorney_B#subject_scope; power_of_attorney_A#limit_term | contract_policy#authority_defined; power_of_attorney_A#subject_scope; power_of_attorney_B#subject_scope; power_of_attorney_A#limit_term | Предмет доверенности определяет, может ли директор филиала подписывать именно этот договор. |
| Q16 | Можно ли на основании всего пакета заключить, что подписант был уполномочен именно на эту сделку? | boolean | true | authority_conclusion | flip | True | False | authorized_for_this_deal | not_authorized_for_this_deal | power_of_attorney_A#subject_scope; authority_contract#buyer_signatory; authority_contract#subject | power_of_attorney_B#subject_scope; authority_contract#buyer_signatory; authority_contract#subject | В версии A пакет документов подтверждает полномочие, в версии B этого не хватает. |

## 4. Отдельная проверка ключевых вопросов
### Q6
- Однозначен ли вопрос только по предоставленным документам: да.
- Нет ли двух разумных трактовок: нет, предмет доверенности и текст договора дают один вывод.
- Соответствует ли decision_required смыслу вопроса: true.
- Является ли answer_type наиболее подходящим: boolean.
- Достаточно ли required evidence: да.
- Нет ли в evidence лишних документов: нет.
- Не раскрывается ли ответ формулировкой вопроса: нет.
- Действительно ли вопрос flip: да.

### Q7
- Однозначен ли вопрос только по предоставленным документам: да.
- Нет ли двух разумных трактовок: нет, предмет доверенности и текст договора дают один вывод.
- Соответствует ли decision_required смыслу вопроса: true.
- Является ли answer_type наиболее подходящим: boolean.
- Достаточно ли required evidence: да.
- Нет ли в evidence лишних документов: нет.
- Не раскрывается ли ответ формулировкой вопроса: нет.
- Действительно ли вопрос flip: да.

### Q12
- Однозначен ли вопрос только по предоставленным документам: да.
- Нет ли двух разумных трактовок: нет, предмет доверенности и текст договора дают один вывод.
- Соответствует ли decision_required смыслу вопроса: true.
- Является ли answer_type наиболее подходящим: boolean.
- Достаточно ли required evidence: да.
- Нет ли в evidence лишних документов: нет.
- Не раскрывается ли ответ формулировкой вопроса: нет.
- Действительно ли вопрос flip: да.

### Q14
- Однозначен ли вопрос только по предоставленным документам: да.
- Нет ли двух разумных трактовок: нет, предмет доверенности и текст договора дают один вывод.
- Соответствует ли decision_required смыслу вопроса: true.
- Является ли answer_type наиболее подходящим: status.
- Достаточно ли required evidence: да.
- Нет ли в evidence лишних документов: нет.
- Не раскрывается ли ответ формулировкой вопроса: нет.
- Действительно ли вопрос flip: да.

### Q16
- Однозначен ли вопрос только по предоставленным документам: да.
- Нет ли двух разумных трактовок: нет, предмет доверенности и текст договора дают один вывод.
- Соответствует ли decision_required смыслу вопроса: true.
- Является ли answer_type наиболее подходящим: boolean.
- Достаточно ли required evidence: да.
- Нет ли в evidence лишних документов: нет.
- Не раскрывается ли ответ формулировкой вопроса: нет.
- Действительно ли вопрос flip: да.

## 5. Проверка документов на естественность
- Противоречий в датах, суммах, номерах и должностях не обнаружено.
- Документы выглядят как обычный внутренний корпоративный пакет.
- Прямых benchmark-подсказок в текстах нет.
- Доверенности дублируются по структуре и отличаются только предметом полномочий.
- Иерархия документов задана достаточно ясно через положение и доверенность.

## 6. Проверка контрфактического дизайна
- A и B различаются только предметом доверенности.
- Все пять flip-вопросов действительно меняют ответ между A и B.
- Все одиннадцать invariant-вопросов сохраняют ответ.
- Изменение не вносит дополнительных побочных эффектов в договор, акт или заявку на оплату.

## 7. Итог

### Критические проблемы
- Не обнаружены.

### Желательные улучшения
- При желании можно добавить ещё один нейтральный документ о маршруте согласования, но для текущего дизайна это не требуется.

### Можно оставить без изменений
- Текущий пакет и матрица вопросов достаточны для benchmark-оценки.
