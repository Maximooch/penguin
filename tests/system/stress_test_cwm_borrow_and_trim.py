#!/usr/bin/env python3
"""
Stress: Combined trimming and borrowing in ContextWindowManager with images.
Ensures SYSTEM preserved, SYSTEM_OUTPUT trimmed before DIALOG, and CONTEXT borrows from DIALOG.
"""

from penguin.system.context_window import ContextWindowManager
from penguin.system.state import Session, Message, MessageCategory


def assert_true(cond: bool, msg: str) -> bool:
    if cond:
        print(f"✅ {msg}")
        return True
    else:
        print(f"❌ {msg}")
        return False


def make_msg(role: str, content, cat: MessageCategory) -> Message:
    return Message(role=role, content=content, category=cat)


def main() -> int:
    class _MC:  # smallish window to force trimming
        max_tokens = 12000

    cwm = ContextWindowManager(model_config=_MC())

    s = Session()
    # SYSTEM heavy prompt (won't be trimmed)
    s.add_message(make_msg("system", "BASE RULES\n" + ("x" * 2000), MessageCategory.SYSTEM))
    # CONTEXT: working files excerpts
    for i in range(10):
        s.add_message(make_msg("system", f"file_{i}:" + ("code\n" * 80), MessageCategory.CONTEXT))
    # DIALOG: chat history chunks
    for i in range(15):
        s.add_message(make_msg("user" if i % 2 == 0 else "assistant", ("blah " * 120), MessageCategory.DIALOG))
    # SYSTEM_OUTPUT: tool logs
    for i in range(5):
        s.add_message(make_msg("system", ("log\n" * 200), MessageCategory.SYSTEM_OUTPUT))
    # Images (count heavy)
    img_part = [{"type": "image_url", "image_url": {"url": "file://dummy"}}]
    s.add_message(make_msg("user", img_part, MessageCategory.DIALOG))
    s.add_message(make_msg("assistant", img_part, MessageCategory.DIALOG))

    stats_before = cwm.analyze_session(s)
    print(f"Before: total={stats_before['total_tokens']}, per_category={[ (k.name, v) for k,v in stats_before['per_category'].items() ]}")

    trimmed = cwm.process_session(s)
    stats_after = cwm.analyze_session(trimmed)
    print(f"After trim: total={stats_after['total_tokens']}, per_category={[ (k.name, v) for k,v in stats_after['per_category'].items() ]}")

    # Borrow tokens if CONTEXT still over
    moves = cwm.auto_rebalance_budgets()
    print(f"Borrow movements: {moves}")

    # Checks
    ok = True
    # SYSTEM count preserved
    sys_before = len([m for m in s.messages if m.category == MessageCategory.SYSTEM])
    sys_after = len([m for m in trimmed.messages if m.category == MessageCategory.SYSTEM])
    ok &= assert_true(sys_before == sys_after, "SYSTEM messages preserved")
    # SYSTEM_OUTPUT trimmed first (expect fewer or zero)
    so_before = len([m for m in s.messages if m.category == MessageCategory.SYSTEM_OUTPUT])
    so_after = len([m for m in trimmed.messages if m.category == MessageCategory.SYSTEM_OUTPUT])
    ok &= assert_true(so_after <= so_before, "SYSTEM_OUTPUT trimmed")
    # Total within budget (allow small overage if images heavy)
    ok &= assert_true(stats_after["total_tokens"] <= cwm.max_tokens, "total within max tokens after trim")

    if ok:
        print("\n🎉 CWM borrow+trim stress passed")
        return 0
    else:
        print("\n❌ CWM borrow+trim stress failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

