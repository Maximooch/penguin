#!/usr/bin/env python3
"""
Integration-flavored test: exercise ContextWindowManager via ConversationManager.

Uses a temporary workspace to mimic real initialization and grabs the active
ContextWindowManager from ConversationManager. Then triggers the borrowing
logic and validates budgets move as expected. Print + exit code style.
"""

import tempfile
from pathlib import Path

from penguin.system.conversation_manager import ConversationManager
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

    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        # Minimal manager; no API calls performed
        cm = ConversationManager(model_config=None, api_client=None, workspace_path=ws)
        cwm = cm.get_current_context_window()
        ctx = cwm._budgets[MessageCategory.CONTEXT]
        dlg = cwm._budgets[MessageCategory.DIALOG]

        print("Initial budgets (via ConversationManager):")
        print(f"  CONTEXT: max={ctx.max_tokens}, current={ctx.current_tokens}")
        print(f"  DIALOG:  max={dlg.max_tokens}, current={dlg.current_tokens}")

        # Configure usage to trigger borrowing
        ctx.current_tokens = ctx.max_tokens + 80   # over by 80
        dlg.current_tokens = dlg.max_tokens - 250  # 250 available

        ctx_max_before = ctx.max_tokens
        dlg_max_before = dlg.max_tokens
        context_over = ctx.current_tokens - ctx_max_before
        dialog_available = dlg_max_before - dlg.current_tokens
        expected_borrow = min(max(0, context_over), max(0, dialog_available), max(0, dialog_available // 2))
        print("\nPre-borrow state:")
        print(f"  context_over={context_over}, dialog_available={dialog_available}, expected_borrow={expected_borrow}")

        movements = cwm.auto_rebalance_budgets()

        ctx_max_after = cwm._budgets[MessageCategory.CONTEXT].max_tokens
        dlg_max_after = cwm._budgets[MessageCategory.DIALOG].max_tokens
        actual_borrow = movements.get("DIALOG -> CONTEXT", 0)

        print("\nPost-borrow state:")
        print(f"  movements={movements}")
        print(f"  CONTEXT: max_before={ctx_max_before} -> max_after={ctx_max_after}")
        print(f"  DIALOG:  max_before={dlg_max_before} -> max_after={dlg_max_after}")

        ok = True
        ok &= assert_true("DIALOG -> CONTEXT" in movements, "movement recorded DIALOG -> CONTEXT")
        ok &= assert_true(actual_borrow == expected_borrow, f"borrow matches expectation ({actual_borrow} == {expected_borrow})")
        ok &= assert_true(ctx_max_after == ctx_max_before + actual_borrow, "CONTEXT budget increased correctly")
        ok &= assert_true(dlg_max_after == dlg_max_before - actual_borrow, "DIALOG budget decreased correctly")

        if not ok:
            failures += 1

    if failures == 0:
        print("\n🎉 Context borrowing (integration) passed")
        return 0
    else:
        print(f"\n❌ {failures} failure(s) in integration borrowing test")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

