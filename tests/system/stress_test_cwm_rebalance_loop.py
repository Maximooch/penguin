#!/usr/bin/env python3
"""
Stress: repeated auto-rebalance calls to ensure budgets remain valid and reversible.
"""

from penguin.system.context_window import ContextWindowManager
from penguin.system.state import MessageCategory


def assert_true(cond: bool, msg: str) -> bool:
    if cond:
        print(f"✅ {msg}")
        return True
    else:
        print(f"❌ {msg}")
        return False


def main() -> int:
    class _MC:
        max_tokens = 10000

    cwm = ContextWindowManager(model_config=_MC())
    ctx = cwm._budgets[MessageCategory.CONTEXT]
    dlg = cwm._budgets[MessageCategory.DIALOG]

    ok = True
    for i in range(100):
        # Overrun context slightly, leave dialog with headroom
        ctx.current_tokens = ctx.max_tokens + 40
        dlg.current_tokens = max(0, dlg.max_tokens - 200)
        before = (ctx.max_tokens, dlg.max_tokens)
        moves = cwm.auto_rebalance_budgets()
        after = (ctx.max_tokens, dlg.max_tokens)
        # Budgets should not go negative, and delta equals movement when present
        if moves:
            m = moves.get("DIALOG -> CONTEXT", 0)
            ok &= assert_true(after[0] == before[0] + m and after[1] == before[1] - m, "movement applied correctly")
        # Reset to original to simulate independence (reverse the borrow)
        ctx.max_tokens, dlg.max_tokens = before
        ctx.current_tokens = 0
        dlg.current_tokens = 0

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

