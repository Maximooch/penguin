# Penguin Checkpointing & Branching - UI Mockups

> Visual mockups for the V2.1 automatic checkpointing and branching system

---

## 1. Chat Interface with Checkpoint Controls

### GUI Version (Web/Desktop)
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🐧 Penguin AI Assistant                                    [⚙️] [🌳] [📊]    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ 👤 User: Create a login form with validation                               │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ 🤖 Assistant: I'll create a login form with validation for you.        │ │
│ │                                                                         │ │
│ │ ```html                                                                 │ │
│ │ <form id="loginForm">                                                   │ │
│ │   <input type="email" id="email" required>                             │ │
│ │   <input type="password" id="password" required>                       │ │
│ │   <button type="submit">Login</button>                                 │ │
│ │ </form>                                                                 │ │
│ │ ```                                                                     │ │
│ │                                                                         │ │
│ │ I've also added JavaScript validation...                               │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│ [↩️ Rollback] [🌿 Branch] [⭐ Bookmark] [📋 Copy]                          │
│                                                                             │
│ 👤 User: Add CSS styling to make it look modern                            │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ 🤖 Assistant: I'll add modern CSS styling to the login form.           │ │
│ │                                                                         │ │
│ │ ```css                                                                  │ │
│ │ .login-form {                                                           │ │
│ │   background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);       │ │
│ │   padding: 2rem;                                                        │ │
│ │   border-radius: 10px;                                                  │ │
│ │   box-shadow: 0 10px 25px rgba(0,0,0,0.2);                            │ │
│ │ }                                                                       │ │
│ │ ```                                                                     │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│ [↩️ Rollback] [🌿 Branch] [⭐ Bookmark] [📋 Copy]                          │
│                                                                             │
│ 👤 User: Actually, let's try a different approach with React               │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ 🤖 Assistant: I'll convert this to a React component instead.          │ │
│ │                                                                         │ │
│ │ ```jsx                                                                  │ │
│ │ import React, { useState } from 'react';                               │ │
│ │                                                                         │ │
│ │ const LoginForm = () => {                                               │ │
│ │   const [email, setEmail] = useState('');                              │ │
│ │   const [password, setPassword] = useState('');                        │ │
│ │   // ... component logic                                                │ │
│ │ };                                                                      │ │
│ │ ```                                                                     │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│ [↩️ Rollback] [🌿 Branch] [⭐ Bookmark] [📋 Copy]                          │
│                                                                             │
│ [Type your message...]                                    [📎] [🎤] [📤]   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### CLI Version
```
┌─ Penguin CLI ─────────────────────────────────────────────────────────────┐
│                                                                           │
│ 👤 User: Create a login form with validation                             │
│                                                                           │
│ 🤖 Assistant: I'll create a login form with validation for you.          │
│                                                                           │
│ ┌─ login.html ─────────────────────────────────────────────────────────┐  │
│ │ <form id="loginForm">                                                │  │
│ │   <input type="email" id="email" required>                          │  │
│ │   <input type="password" id="password" required>                    │  │
│ │   <button type="submit">Login</button>                              │  │
│ │ </form>                                                              │  │
│ └──────────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│ [msg_a1b2c3d4] ↩️ rollback  🌿 branch  ⭐ bookmark                       │
│                                                                           │
│ 👤 User: Add CSS styling to make it look modern                          │
│                                                                           │
│ 🤖 Assistant: I'll add modern CSS styling to the login form.             │
│                                                                           │
│ ┌─ styles.css ─────────────────────────────────────────────────────────┐  │
│ │ .login-form {                                                        │  │
│ │   background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);    │  │
│ │   padding: 2rem;                                                     │  │
│ │   border-radius: 10px;                                               │  │
│ │ }                                                                    │  │
│ └──────────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│ [msg_e5f6g7h8] ↩️ rollback  🌿 branch  ⭐ bookmark                       │
│                                                                           │
│ > _                                                                       │
└───────────────────────────────────────────────────────────────────────────┘

Commands: /rollback <msg_id> | /branch <msg_id> | /tree | /checkpoints
```

---

## 2. Rollback Modal/Dialog

### GUI Rollback Modal
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          🔄 Rollback Confirmation                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ You're about to rollback to message: msg_a1b2c3d4                          │
│ "Create a login form with validation"                                       │
│                                                                             │
│ ⚠️  This will undo the following changes:                                   │
│                                                                             │
│ 📝 Conversation:                                                            │
│   • Remove 2 messages (CSS styling, React conversion)                      │
│                                                                             │
│ 📋 Tasks:                                                                   │
│   • Revert task "Build login component" to earlier state                   │
│   • Undo progress on "Add modern styling" subtask                          │
│                                                                             │
│ 💻 Code Changes:                                                            │
│   • Delete: src/components/LoginForm.jsx                                   │
│   • Revert: styles.css (remove 47 lines)                                   │
│   • Restore: login.html (original version)                                 │
│                                                                             │
│ ┌─ Git Diff Preview ─────────────────────────────────────────────────────┐ │
│ │ - import React, { useState } from 'react';                             │ │
│ │ - const LoginForm = () => {                                             │ │
│ │ + <form id="loginForm">                                                 │ │
│ │ +   <input type="email" id="email" required>                           │ │
│ │ [Show full diff...]                                                     │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ 🔄 What would you like to do?                                              │
│                                                                             │
│ [🔙 Rollback & Continue]  [🌿 Rollback & Branch]  [❌ Cancel]              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### CLI Rollback Confirmation
```
┌─ Rollback Confirmation ───────────────────────────────────────────────────┐
│                                                                           │
│ 🔄 Rollback to: msg_a1b2c3d4 "Create a login form with validation"       │
│                                                                           │
│ ⚠️  Changes to be undone:                                                 │
│                                                                           │
│ 📝 Conversation: Remove 2 messages                                        │
│ 📋 Tasks: Revert "Build login component" task                            │
│ 💻 Code: Delete LoginForm.jsx, revert styles.css                         │
│                                                                           │
│ ┌─ Git Diff ─────────────────────────────────────────────────────────────┐ │
│ │ - import React, { useState } from 'react';                            │ │
│ │ - const LoginForm = () => {                                            │ │
│ │ + <form id="loginForm">                                                │ │
│ │ +   <input type="email" id="email" required>                          │ │
│ │ [Use 'git diff --full' to see complete changes]                       │ │
│ └────────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│ Continue? [y/N/b=branch]: _                                               │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Branch Creation Interface

### GUI Branch Dialog
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           🌿 Create New Branch                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ Branching from: msg_a1b2c3d4                                               │
│ "Create a login form with validation"                                       │
│                                                                             │
│ 📝 Branch Name (optional):                                                  │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ React Alternative Approach                                              │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ 📄 Description (optional):                                                  │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ Exploring React implementation instead of vanilla HTML/CSS             │ │
│ │                                                                         │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ 🎯 Starting Context:                                                        │
│ ✅ Conversation history (up to branch point)                               │
│ ✅ Task state: "Build login component" (in progress)                       │
│ ✅ Code state: login.html, basic validation.js                             │
│                                                                             │
│ 🔄 This will create a new conversation thread where you can explore        │
│    different approaches without affecting your main conversation.          │
│                                                                             │
│ [🌿 Create Branch]  [❌ Cancel]                                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### CLI Branch Creation
```
┌─ Create Branch ───────────────────────────────────────────────────────────┐
│                                                                           │
│ 🌿 Branching from: msg_a1b2c3d4 "Create a login form with validation"    │
│                                                                           │
│ Branch name (optional): React Alternative Approach                       │
│ Description (optional): Exploring React implementation                   │
│                                                                           │
│ 📋 Branch will include:                                                   │
│   ✅ 3 conversation messages                                              │
│   ✅ Task: "Build login component" (in progress)                         │
│   ✅ Files: login.html, validation.js                                    │
│                                                                           │
│ Create branch? [Y/n]: _                                                   │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Conversation Tree Sidebar

### GUI Tree Sidebar
```
┌─ Conversation Tree ─────────────────────────────────────────────────────────┐
│                                                                             │
│ 🌳 Login Form Project                                                       │
│ ├─ 📝 Main Thread (active)                                                  │
│ │  ├─ msg_a1b2c3d4: Create login form                                      │
│ │  ├─ msg_e5f6g7h8: Add CSS styling                                        │
│ │  └─ msg_i9j0k1l2: Convert to React ← You are here                       │
│ │                                                                           │
│ ├─ 🌿 React Alternative (3 messages)                                        │
│ │  ├─ msg_a1b2c3d4: Create login form                                      │
│ │  ├─ msg_m3n4o5p6: Use React hooks                                        │
│ │  └─ msg_q7r8s9t0: Add TypeScript                                         │
│ │                                                                           │
│ └─ 🌿 Vue.js Approach (2 messages)                                          │
│    ├─ msg_a1b2c3d4: Create login form                                      │
│    └─ msg_u1v2w3x4: Convert to Vue component                               │
│                                                                             │
│ ⭐ Bookmarked Checkpoints:                                                  │
│ ├─ 🔖 "Working HTML version" (msg_a1b2c3d4)                                │
│ ├─ 🔖 "Styled version" (msg_e5f6g7h8)                                      │
│ └─ 🔖 "React with hooks" (msg_m3n4o5p6)                                    │
│                                                                             │
│ 🗂️ Recent Auto-Checkpoints:                                                │
│ ├─ 2 hours ago: msg_i9j0k1l2                                               │
│ ├─ 3 hours ago: msg_e5f6g7h8                                               │
│ ├─ 4 hours ago: msg_a1b2c3d4                                               │
│ └─ [Show more...]                                                           │
│                                                                             │
│ [🧹 Cleanup Old] [📊 Storage Usage]                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### CLI Tree View
```
penguin tree

🌳 Conversation Tree: Login Form Project

📝 Main Thread (active)
├─ msg_a1b2c3d4: Create login form ⭐
├─ msg_e5f6g7h8: Add CSS styling ⭐
└─ msg_i9j0k1l2: Convert to React ← current

🌿 Branches:
├─ react-alt (3 msgs): React Alternative Approach
│  └─ Last: msg_q7r8s9t0 "Add TypeScript"
└─ vue-approach (2 msgs): Vue.js Approach  
   └─ Last: msg_u1v2w3x4 "Convert to Vue component"

⭐ Bookmarks:
├─ msg_a1b2c3d4: "Working HTML version"
├─ msg_e5f6g7h8: "Styled version"  
└─ msg_m3n4o5p6: "React with hooks"

Commands:
  penguin switch <branch>     - Switch to branch
  penguin goto <msg_id>       - Jump to checkpoint
  penguin bookmark <msg_id>   - Bookmark checkpoint
```

---

## 5. Settings/Configuration Panel

### GUI Settings Panel
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ⚙️ Checkpointing Settings                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ 🔄 Auto-Checkpointing                                                       │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ ☑️ Enable automatic checkpoints                                         │ │
│ │                                                                         │ │
│ │ Frequency: Every [1] message(s)                                        │ │
│ │ ┌─────┬─────┬─────┬─────┬─────┐                                         │ │
│ │ │  1  │  2  │  3  │  5  │ 10  │                                         │ │
│ │ └─────┴─────┴─────┴─────┴─────┘                                         │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ 📋 Checkpoint Planes                                                        │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ ☑️ Conversation (messages, context)                                     │ │
│ │ ☑️ Tasks (project state, task graph)                                    │ │
│ │ ☑️ Code (workspace files, git commits)                                  │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ 🗄️ Storage & Retention                                                      │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ Keep all checkpoints for: [24] hours                                    │ │
│ │ Then keep every: [10]th checkpoint                                      │ │
│ │ Maximum age: [30] days                                                   │ │
│ │                                                                         │ │
│ │ Current usage: 47.2 MB (estimated)                                      │ │
│ │ ├─ Conversations: 12.1 MB                                               │ │
│ │ ├─ Task snapshots: 28.7 MB                                              │ │
│ │ └─ Git commits: 6.4 MB                                                  │ │
│ │                                                                         │ │
│ │ [🧹 Clean Up Old Checkpoints]                                           │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ 🎨 UI Preferences                                                           │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ ☑️ Show rollback/branch buttons on messages                             │ │
│ │ ☑️ Show conversation tree sidebar                                        │ │
│ │ ☑️ Confirm before rollback operations                                    │ │
│ │ ☐ Auto-expand git diffs in rollback preview                             │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ [💾 Save Settings]  [🔄 Reset to Defaults]  [❌ Cancel]                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### CLI Settings
```
penguin config checkpointing

🔄 Checkpointing Configuration

Auto-checkpointing: ✅ enabled
Frequency: every 1 message(s)
Planes: conversation ✅, tasks ✅, code ✅

Retention Policy:
├─ Keep all: 24 hours
├─ Then keep every: 10th checkpoint  
└─ Maximum age: 30 days

Storage Usage:
├─ Total: 47.2 MB
├─ Conversations: 12.1 MB
├─ Task snapshots: 28.7 MB (compressed)
└─ Git commits: 6.4 MB

Commands:
  penguin config set checkpointing.frequency 5
  penguin config set checkpointing.planes.code false
  penguin cleanup --older-than 7d
  penguin storage --analyze
```

---

## 6. Status Indicators & Notifications

### GUI Status Bar
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Status: 🟢 Ready  |  💾 Last checkpoint: 2 min ago  |  🌿 3 branches  |  📊 47MB │
└─────────────────────────────────────────────────────────────────────────────┘

// During checkpointing:
┌─────────────────────────────────────────────────────────────────────────────┐
│ Status: 🔄 Creating checkpoint...  |  ⏱️ ETA: 3s  |  🌿 3 branches  |  📊 47MB │
└─────────────────────────────────────────────────────────────────────────────┘

// Notification toast:
┌─────────────────────────────────────┐
│ ✅ Checkpoint created successfully  │
│ msg_x1y2z3a4 • 2.3 MB saved        │
│ [View] [Dismiss]                    │
└─────────────────────────────────────┘
```

### CLI Status
```
penguin status

🐧 Penguin Status
├─ Checkpointing: 🟢 active (every 1 msg)
├─ Last checkpoint: msg_x1y2z3a4 (2 minutes ago)
├─ Current branch: main
├─ Available branches: 3 (react-alt, vue-approach, main)
├─ Storage usage: 47.2 MB
└─ Background workers: 🟢 running

Recent Activity:
├─ 14:32 - Checkpoint created (msg_x1y2z3a4)
├─ 14:30 - Branch created: react-alt
├─ 14:25 - Checkpoint created (msg_w9x0y1z2)
└─ 14:20 - Rollback to msg_a1b2c3d4
```

---

## 7. Error States & Recovery

### GUI Error Dialog
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ⚠️ Checkpoint Error                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ Failed to create checkpoint for message msg_x1y2z3a4                       │
│                                                                             │
│ 🔍 Details:                                                                 │
│ • Conversation: ✅ Saved successfully                                       │
│ • Tasks: ❌ Failed to serialize task graph                                  │
│ • Code: ⚠️ Git repository is in detached HEAD state                        │
│                                                                             │
│ 🛠️ Suggested Actions:                                                       │
│ • Continue without task checkpoint (conversation still saved)              │
│ • Retry checkpoint creation                                                 │
│ • Disable task checkpointing temporarily                                   │
│                                                                             │
│ 📋 Error Log:                                                               │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ TaskManager.snapshot() failed:                                          │ │
│ │ JSONEncodeError: Object of type 'datetime' is not JSON serializable    │ │
│ │ at line 247 in task_manager.py                                          │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│ [🔄 Retry]  [⚙️ Disable Tasks]  [📋 Copy Error]  [❌ Continue]             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### CLI Error Message
```
❌ Checkpoint creation failed for msg_x1y2z3a4

Status:
├─ Conversation: ✅ saved
├─ Tasks: ❌ serialization error  
└─ Code: ⚠️ git detached HEAD

Error: TaskManager.snapshot() failed
JSONEncodeError: Object of type 'datetime' is not JSON serializable

Actions:
  penguin retry-checkpoint
  penguin config set checkpointing.planes.tasks false
  penguin debug --show-full-error
```

---

These mockups show how the V2.1 checkpointing system would feel in practice - seamless, informative, and powerful while staying out of the user's way during normal conversation flow. The key design principles are:

1. **Non-intrusive**: Checkpoints happen automatically in the background
2. **Discoverable**: Clear visual cues for rollback/branch options
3. **Informative**: Users understand what will happen before taking action
4. **Recoverable**: Clear error states with actionable solutions
5. **Configurable**: Users can tune the system to their preferences

The UI strikes a balance between power-user features (detailed git diffs, storage management) and simplicity for casual users (one-click rollback, automatic checkpoints). 