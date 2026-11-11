# Project record

## Objective

Run versioned SQL migrations against SQLite with a cross-process lock table, checksums of applied files, transactional apply and rollback, and a dry-run plan.

## Scope

- In scope: the public Python API in `migration_runner`, the `python -m migration_runner` CLI, loading `V<version>__<name>.sql` files, applying forward migrations to SQLite, the lock row, checksums, transaction control rejection, plan/status output, and the errors and limits documented in [README.md](../README.md).
- Out of scope: down migrations, PostgreSQL and other database engines, Python migrations, repeatable migrations, and baselining.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 781977 / 77833 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.1003 |

## Factory run u285 (measured from API usage)

| Date (UTC) | Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|---|
| 2026-11-11 | generation | deepseek-v4-pro | yes | 1787 | 20729 | 0 | 3328 | 0.0423 |
| 2026-11-11 | fix-1 | deepseek-flash | no | 19766 | 10500 | 0 | 204800 | 0.0099 |
| 2026-11-11 | fix-2 | deepseek-flash | no | 8979 | 3722 | 0 | 31872 | 0.0037 |
| 2026-11-11 | audit | deepseek-flash | no | 16386 | 19582 | 0 | 217088 | 0.0149 |
| 2026-11-11 | fix-3 | deepseek-flash | no | 13938 | 10045 | 0 | 177408 | 0.0087 |
| 2026-11-11 | docs | deepseek-flash | no | 86369 | 13255 | 0 | 256 | 0.0209 |

Total: $0.1003. Prices: deepseek line, as measured by its adapter. Providers serve the current version of each model id, so the date tells which version answered; versions, launch stages and price sources per line are in the factory's model register (docs/MODELS.md).
