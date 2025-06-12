# Stop Conditions

Penguin's `Engine` supports pluggable stop conditions that control when an autonomous run should finish. The default implementation ships with `TokenBudgetStop` and `WallClockStop`.

## TokenBudgetStop

`TokenBudgetStop` monitors the current conversation's context window. When the token usage exceeds the configured budget the engine stops processing further steps. This prevents runaway tasks from exhausting API quotas.

To enable it, create the engine with `token_budget_stop_enabled=True` or add the condition manually when constructing the engine.

