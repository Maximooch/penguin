# Banner Ordering Fix

Date: 2025-11-02
Status: Fixed

## Issue

Banner (ASCII logo) was appearing AFTER the first messages in the timeline, instead of before them.

**Symptom:**
```
[1] You:
  /chat list
[2] Penguin:
  📋 Found 20 conversation(s):
  ...

 ▄▄▄▄▄ ooooooooo.     <-- Banner appears here (WRONG)
 ▄▄▄▄▄ `888   `Y88.
 ...
```

**Expected:**
```
 ▄▄▄▄▄ ooooooooo.     <-- Banner should appear first
 ▄▄▄▄▄ `888   `Y88.
 ...

[1] You:
  /chat list
[2] Penguin:
  📋 Found 20 conversation(s):
```

## Root Cause

The banner was rendered in `App.tsx` OUTSIDE the `<Static>` component, while messages were rendered INSIDE `<Static>` in `EventTimeline.tsx`.

Ink's `<Static>` component renders its children as permanent terminal text that never updates. When messages were added to the Static component, they appeared in the terminal BEFORE the banner which was rendered separately.

## Solution

Following Gemini CLI's pattern ([MainContent.tsx](../reference/gemini-cli/packages/cli/src/ui/components/MainContent.tsx#L32-L50)), moved the banner INSIDE the Static component as the **first item**.

### Implementation

**1. EventTimeline accepts optional header prop**

[EventTimeline.tsx](../penguin-cli/src/ui/components/EventTimeline.tsx):
```typescript
interface EventTimelineProps {
  ...
  header?: React.ReactNode; // Optional header (banner) to display as first Static item
}

export const EventTimeline = React.memo(function EventTimeline({
  ...,
  header
}: EventTimelineProps) {
  // Build array of React elements for Static component (Gemini CLI pattern)
  const staticItems: React.ReactNode[] = [];

  if (header) {
    staticItems.push(
      <React.Fragment key="header">{header}</React.Fragment>
    );
  }

  // Add all visible event items
  visibleCompleted.forEach((ev, idx) => {
    staticItems.push(
      <EventItem key={`${ev.kind}:${ev.id}:${idx}`} index={idx + 1 + start} event={ev} showReasoning={showReasoning} />
    );
  });

  return (
    <Box flexDirection="column" gap={1}>
      {/* Single Static component with header + all events (Gemini CLI pattern) */}
      <Static items={staticItems}>
        {(item) => item}
      </Static>

      {/* Dynamic box: streaming event */}
      {streamingEvent && <EventItem ... />}
    </Box>
  );
});
```

**2. App passes banner to ChatSession**

[App.tsx](../penguin-cli/src/ui/components/App.tsx):
```typescript
// Render banner (only for chat tab, passed to ChatSession)
const banner = showBanner && activeTab?.type === 'chat' ? (
  <BannerRenderer
    version="0.1.0"
    workspace={workspace}
  />
) : undefined;

// Pass banner to ChatSession
return <ChatSession conversationId={currentConversationId} header={banner} />;
```

**3. ChatSession passes header to EventTimeline**

[ChatSession.tsx](../penguin-cli/src/ui/components/ChatSession.tsx):
```typescript
interface ChatSessionProps {
  conversationId?: string;
  header?: React.ReactNode; // Optional header (banner)
}

export function ChatSession({ conversationId, header }: ChatSessionProps) {
  ...
  return (
    <>
      <EventTimeline
        messages={messages}
        streamingText={streamingText}
        toolEvents={toolEvents}
        header={header}  // Pass header to EventTimeline
      />
    </>
  );
}
```

## Key Insight: Gemini CLI Pattern

Gemini CLI ([MainContent.tsx](../reference/gemini-cli/packages/cli/src/ui/components/MainContent.tsx#L32-L50)) renders the header INSIDE the Static items array:

```typescript
<Static
  items={[
    <AppHeader key="app-header" version={version} />,  // ← Header first
    ...uiState.history.map((h) => <HistoryItemDisplay ... />),
  ]}
>
  {(item) => item}
</Static>
```

This ensures the header is rendered as permanent terminal text BEFORE any messages, maintaining correct chronological order.

## Files Modified

1. **[EventTimeline.tsx](../penguin-cli/src/ui/components/EventTimeline.tsx)**
   - Added `header?: React.ReactNode` prop
   - Render header as separate Static component before events
   - Lines 6-14, 58-66

2. **[App.tsx](../penguin-cli/src/ui/components/App.tsx)**
   - Removed banner from outside ChatSession
   - Create banner and pass to ChatSession as header prop
   - Lines 25-31, 39

3. **[ChatSession.tsx](../penguin-cli/src/ui/components/ChatSession.tsx)**
   - Added `header?: React.ReactNode` to ChatSessionProps
   - Pass header to EventTimeline
   - Lines 48-51, 1032

## Result

Now the banner appears as the first Static item, ensuring it's rendered before any messages:

```
 ▄▄▄▄▄ ooooooooo.     <-- Banner appears FIRST ✓
 ▄▄▄▄▄ `888   `Y88.
 ...

 v0.1.0 • Software Engineer Agent
 📁 Workspace: penguin-cli • Type /help for commands

[1] You:
  /chat list
[2] Penguin:
  📋 Found 20 conversation(s):
```

## Why This Matters

### Critical: Use ONE Static Component, Not Multiple

**WRONG ❌:**
```typescript
{header && (
  <Static items={[1]}>
    {() => header}
  </Static>
)}
<Static items={events}>
  {(ev) => <EventItem ... />}
</Static>
```

When you use **multiple Static components**, each one renders independently. As new messages arrive, the second Static grows and pushes the first Static (with header) up and out of view.

**CORRECT ✅:**
```typescript
<Static items={[header, ...events]}>
  {(item) => item}
</Static>
```

With a **single Static component**, all items (header + events) are in one permanent block. New messages are added to the same Static items array, maintaining the header at the top.

### Ink's Static Component Behavior

- Content INSIDE Static renders once as permanent terminal text
- Content OUTSIDE Static can cause ordering issues
- Multiple Static components don't coordinate with each other
- The first item in a Static array always appears first
- Following established patterns (like Gemini CLI) ensures correct behavior

## Related Fixes

This fix complements the other timeline fixes:
- [Bug Fixes - Keyboard and Tool Events](bug_fixes_keyboard_and_tool_events.md) - Issues 1-6
- [UI Performance Fix - Static Component](ui_performance_fix_static_component.md) - Static component pattern
- [Input Improvements](input_improvements.md) - Input handling fixes

All timeline ordering issues are now resolved!
