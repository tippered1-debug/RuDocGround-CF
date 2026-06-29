# asset_scope_010 integration handoff

После интеграции `approval_chain_009` этот case-specific draft нужно перенести на новую базу.

## Что потребуется сделать

- Rebase или cherry-pick case-specific коммита на новую чистую базу.
- Добавить поддержку `asset_scope_010` в `rudocground/case_tools.py`.
- Добавить 32 записи в `data/gold.jsonl`.
- Пересобрать prompts.
- Пересобрать `perfect`, `broken` и `partial` fixtures.
- Перепроверить shared count assertions после интеграции общей базы.

## Примечание

- Этот draft intentionally не меняет shared fixtures и общий gold.
- Единственное контрфактическое различие находится в инвентарной карточке сервера DB-1.
