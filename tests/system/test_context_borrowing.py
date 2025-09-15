#!/usr/bin/env python3
"""
Tests dynamic budget borrowing in ContextWindowManager.
Print + exit style.
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
    failures = 0

    class _MC:
        max_tokens = 1000

    cwm = ContextWindowManager(model_config=_MC())

    # Force CONTEXT over budget and DIALOG with headroom
    ctx = cwm._budgets[MessageCategory.CONTEXT]
    dlg = cwm._budgets[MessageCategory.DIALOG]

    # Display initial budgets
    print("Initial budgets:")
    print(f"  CONTEXT: max={ctx.max_tokens}, current={ctx.current_tokens}")
    print(f"  DIALOG:  max={dlg.max_tokens}, current={dlg.current_tokens}")

    # Configure usage to trigger borrowing
    ctx.current_tokens = ctx.max_tokens + 50   # over by 50
    dlg.current_tokens = dlg.max_tokens - 120  # 120 available

    # Snapshot pre-borrow maxes
    ctx_max_before = ctx.max_tokens
    dlg_max_before = dlg.max_tokens

    # Compute expected borrow
    context_over = ctx.current_tokens - ctx_max_before
    dialog_available = dlg_max_before - dlg.current_tokens
    expected_borrow = min(max(0, context_over), max(0, dialog_available), max(0, dialog_available // 2))
    print("\nPre-borrow state:")
    print(f"  context_over={context_over}, dialog_available={dialog_available}, expected_borrow={expected_borrow}")

    movements = cwm.auto_rebalance_budgets()

    # Post-borrow values
    ctx_max_after = cwm._budgets[MessageCategory.CONTEXT].max_tokens
    dlg_max_after = cwm._budgets[MessageCategory.DIALOG].max_tokens
    actual_borrow = movements.get("DIALOG -> CONTEXT", 0)

    print("\nPost-borrow state:")
    print(f"  movements={movements}")
    print(f"  CONTEXT: max_before={ctx_max_before} -> max_after={ctx_max_after}")
    print(f"  DIALOG:  max_before={dlg_max_before} -> max_after={dlg_max_after}")

    # After borrowing, CONTEXT max should have grown by borrow amount, DIALOG decreased by same amount
    ok = True
    ok &= assert_true("DIALOG -> CONTEXT" in movements, "movement recorded DIALOG -> CONTEXT")
    ok &= assert_true(actual_borrow == expected_borrow, f"borrow amount matches expectation ({actual_borrow} == {expected_borrow})")
    ok &= assert_true(ctx_max_after == ctx_max_before + actual_borrow, "CONTEXT budget increased correctly")
    ok &= assert_true(dlg_max_after == dlg_max_before - actual_borrow, "DIALOG budget decreased correctly")

    if not ok:
        failures += 1

    if failures == 0:
        print("\n🎉 Context borrowing tests passed")
        return 0
    else:
        print(f"\n❌ {failures} failure(s) in context borrowing tests")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
