# Penguin Runtime Pseudo‑TLA+ Spec

This is a pseudo-code TLA+ style specification for Penguin's runtime behavior.
It is intentionally close to realistic TLA+ for demonstration purposes, while still
abstracting over implementation details such as exact tokenization, filesystem paths,
and concrete model/tool payloads.

**Grounding sources**
- `architecture.md`
- `README.md`

**Scope**
- Core conversation flow
- Engine loop and explicit termination semantics
- Tool execution lifecycle
- Context window trimming
- Checkpoints and restore
- Multi-agent spawning, messaging, and bounded concurrency
- Streaming lifecycle

**Important**
- This is **not guaranteed TLC-runnable as-is**.
- It is meant as a design/spec artifact rather than an executable model.
- The most important behavioral constraint preserved here is that conversational and task loops terminate **only** via `finish_response` and `finish_task`, respectively.

```tla
------------------------------ MODULE PenguinRuntime ------------------------------
EXTENDS Naturals, Sequences, FiniteSets, TLC

(***************************************************************************)
(* Pseudo-TLA+ spec for Penguin.                                           *)
(* Grounded in architecture.md and README.md, but abstracted where needed. *)
(***************************************************************************)

CONSTANTS
    Agents,              \* finite set of agent ids; includes "default"
    SessionIds,          \* finite set of session ids
    ToolNames,           \* tool registry names
    InterfaceNames,      \* {"cli","tui","web","python"}
    CheckpointIds,       \* finite set of checkpoint ids
    Channels,            \* {"direct","broadcast","human","telemetry"}
    MaxIterations,       \* safety limit for engine loop
    MaxConcurrentTasks,  \* semaphore bound for background work
    NULL

ASSUME "default" \in Agents
ASSUME {"cli","tui","web","python"} \subseteq InterfaceNames
ASSUME {"direct","broadcast","human","telemetry"} \subseteq Channels

MessageKinds == {"message", "action", "status", "event", "tool_result"}
MessageCategories == {
    "SYSTEM", "CONTEXT", "DIALOG", "SYSTEM_OUTPUT", "ERROR", "INTERNAL", "UNKNOWN"
}
AgentStates == {"IDLE", "PENDING", "RUNNING", "PAUSED", "COMPLETED", "FAILED", "CANCELLED"}
AgentPhases == {
    "ready",              \* idle / can accept work
    "await_llm",          \* waiting for model completion
    "streaming",          \* streaming output chunks
    "await_action_parse", \* assistant text exists; parser may extract actions
    "await_tool",         \* tool call(s) outstanding
    "responding",         \* preparing final user-visible response
    "finished"            \* only legal after explicit terminator tool
}
RunModes == {"chat", "task"}
StreamStates == {"inactive", "streaming", "finalized"}

(***************************************************************************)
(* Abstract record shapes                                                  *)
(***************************************************************************)

(*
Message ==
    [ sender    : Agents \cup {"human","system"},
      recipient : Agents \cup {"human","broadcast",NULL},
      kind      : MessageKinds,
      category  : MessageCategories,
      content   : Value,
      session   : SessionIds,
      channel   : Channels \cup {NULL},
      msgId     : Nat ]

ToolOp ==
    [ id        : Nat,
      agent     : Agents,
      tool      : ToolNames,
      params    : Value,
      status    : {"queued","running","ok","error"},
      result    : Value \cup {NULL} ]

AgentInfo ==
    [ state                    : AgentStates,
      phase                    : AgentPhases,
      parent                   : Agents \cup {NULL},
      sharedContextWith        : Agents \cup {NULL},
      maxContextWindowTokens   : Nat,
      maxOutputTokens          : Nat,
      enabledTools             : SUBSET ToolNames ]

Event ==
    [ type     : {"message","token_update","action_executed","progress","stream_chunk","agent_state"},
      payload  : Value,
      agent    : Agents \cup {NULL},
      session  : SessionIds \cup {NULL} ]
*)

VARIABLES
    coreReady,            \* PenguinCore initialized
    interfaces,           \* active interfaces
    agents,               \* AgentInfo per agent
    sessionOf,            \* session binding per agent
    messages,             \* persistent conversation history by session
    checkpoints,          \* checkpoint snapshots
    contextView,          \* currently selected context window per agent
    toolRegistry,         \* enabled tools
    pendingToolOps,       \* queued/running tool calls
    completedToolOps,     \* resolved tool calls
    streams,              \* stream state per agent
    eventBus,             \* system/UI event stream
    messageBus,           \* inter-agent message stream
    uiEvents,             \* emitted interface events
    runModeOf,            \* chat/task mode per agent
    engineIter,           \* iteration counter per agent
    responseTerminated,   \* true iff `finish_response` called
    taskTerminated,       \* true iff `finish_task` called
    tasks                 \* autonomous background tasks

vars ==
    << coreReady, interfaces, agents, sessionOf, messages, checkpoints,
       contextView, toolRegistry, pendingToolOps, completedToolOps, streams,
       eventBus, messageBus, uiEvents, runModeOf, engineIter,
       responseTerminated, taskTerminated, tasks >>

DefaultAgent == "default"

ActiveSession(a) == sessionOf[a]

TokenCount(msgSeq) ==
    Len(msgSeq)
    \* Pseudo abstraction:
    \* real implementation uses model/tokenizer-aware accounting.

WithinWorkspace(params) ==
    TRUE
    \* Pseudo abstraction:
    \* real implementation constrains file/network/tool effects.

NeedsTrim(a) ==
    TokenCount(messages[ActiveSession(a)]) > agents[a].maxContextWindowTokens

PreserveSystemThenRecent(msgSeq) ==
    CHOOSE kept \in SUBSET SeqToSet(msgSeq) :
        /\ \A m \in SeqToSet(msgSeq) : m.category = "SYSTEM" => m \in kept
        /\ RecentDialogPriority(msgSeq, kept)
        /\ LowestPriorityDroppedFirst(msgSeq, kept)
    \* Pseudo selector representing Context Window Manager policy:
    \* preserve SYSTEM, prefer recent DIALOG, drop oldest SYSTEM_OUTPUT first,
    \* retain CONTEXT selectively.

SeqToSet(seq) == { seq[i] : i \in 1..Len(seq) }

(***************************************************************************)
(* Type / shape invariants                                                 *)
(***************************************************************************)

TypeOK ==
    /\ coreReady \in BOOLEAN
    /\ interfaces \subseteq InterfaceNames
    /\ sessionOf \in [Agents -> SessionIds \cup {NULL}]
    /\ runModeOf \in [Agents -> RunModes]
    /\ engineIter \in [Agents -> Nat]
    /\ responseTerminated \in [Agents -> BOOLEAN]
    /\ taskTerminated \in [Agents -> BOOLEAN]
    /\ toolRegistry \subseteq ToolNames
    /\ streams \in [Agents -> StreamStates]
    /\ agents \in [Agents -> [
            state                  : AgentStates,
            phase                  : AgentPhases,
            parent                 : Agents \cup {NULL},
            sharedContextWith      : Agents \cup {NULL},
            maxContextWindowTokens : Nat,
            maxOutputTokens        : Nat,
            enabledTools           : SUBSET ToolNames
       ]]
    /\ messages \in [SessionIds -> Seq(Message)]
    /\ checkpoints \in [CheckpointIds -> [session : SessionIds, snapshot : Seq(Message)]]
    /\ pendingToolOps \subseteq ToolOp
    /\ completedToolOps \subseteq ToolOp
    /\ eventBus \in Seq(Event)
    /\ messageBus \in Seq([
            sender    : Agents \cup {"human"},
            recipient : Agents \cup {"human", NULL},
            kind      : MessageKinds,
            channel   : Channels,
            content   : STRING
       ])
    /\ uiEvents \in Seq(Event)
    /\ tasks \subseteq [
            owner     : Agents,
            status    : {"PENDING","RUNNING","COMPLETED","FAILED","CANCELLED"},
            objective : STRING
       ]

(***************************************************************************)
(* Initial state                                                           *)
(***************************************************************************)

Init ==
    /\ coreReady = TRUE
    /\ interfaces = {"cli","tui","web","python"}
    /\ toolRegistry = ToolNames
    /\ sessionOf = [a \in Agents |->
        IF a = DefaultAgent
        THEN CHOOSE s \in SessionIds : TRUE
        ELSE NULL
       ]
    /\ messages = [s \in SessionIds |-> << >>]
    /\ checkpoints = [c \in CheckpointIds |->
        [session |-> CHOOSE s \in SessionIds : TRUE, snapshot |-> << >>]
       ]
    /\ contextView = [a \in Agents |-> << >>]
    /\ pendingToolOps = {}
    /\ completedToolOps = {}
    /\ streams = [a \in Agents |-> "inactive"]
    /\ eventBus = << >>
    /\ messageBus = << >>
    /\ uiEvents = << >>
    /\ runModeOf = [a \in Agents |-> "chat"]
    /\ engineIter = [a \in Agents |-> 0]
    /\ responseTerminated = [a \in Agents |-> FALSE]
    /\ taskTerminated = [a \in Agents |-> FALSE]
    /\ tasks = {}
    /\ agents = [a \in Agents |->
        [ state                  |-> IF a = DefaultAgent THEN "IDLE" ELSE "PENDING",
          phase                  |-> "ready",
          parent                 |-> IF a = DefaultAgent THEN NULL ELSE DefaultAgent,
          sharedContextWith      |-> NULL,
          maxContextWindowTokens |-> 1000,
          maxOutputTokens        |-> 8000,
          enabledTools           |-> ToolNames
        ]
       ]

(***************************************************************************)
(* Core actions                                                            *)
(***************************************************************************)

ReceiveUserInput(i, a, txt) ==
    /\ i \in interfaces
    /\ a \in Agents
    /\ ActiveSession(a) # NULL
    /\ agents[a].state \in {"IDLE","RUNNING"}
    /\ messages' = [messages EXCEPT
        ![ActiveSession(a)] = Append(@,
            [ sender    |-> "human",
              recipient |-> a,
              kind      |-> "message",
              category  |-> "DIALOG",
              content   |-> txt,
              session   |-> ActiveSession(a),
              channel   |-> "human",
              msgId     |-> Len(@) + 1
            ])
       ]
    /\ agents' = [agents EXCEPT ![a].state = "RUNNING", ![a].phase = "await_llm"]
    /\ engineIter' = [engineIter EXCEPT ![a] = 0]
    /\ responseTerminated' = [responseTerminated EXCEPT ![a] = FALSE]
    /\ UNCHANGED << coreReady, interfaces, sessionOf, checkpoints, contextView,
                    toolRegistry, pendingToolOps, completedToolOps, streams,
                    eventBus, messageBus, uiEvents, runModeOf, taskTerminated, tasks >>

InvokeLLM(a) ==
    /\ a \in Agents
    /\ agents[a].phase = "await_llm"
    /\ engineIter[a] < MaxIterations
    /\ ~responseTerminated[a]
    /\ agents' = [agents EXCEPT ![a].phase = "streaming"]
    /\ streams' = [streams EXCEPT ![a] = "streaming"]
    /\ engineIter' = [engineIter EXCEPT ![a] = @ + 1]
    /\ eventBus' = Append(eventBus,
        [ type    |-> "progress",
          payload |-> "llm_request_started",
          agent   |-> a,
          session |-> ActiveSession(a)
        ])
    /\ UNCHANGED << coreReady, interfaces, sessionOf, messages, checkpoints,
                    contextView, toolRegistry, pendingToolOps, completedToolOps,
                    messageBus, uiEvents, runModeOf, responseTerminated,
                    taskTerminated, tasks >>

StreamChunk(a, chunk) ==
    /\ a \in Agents
    /\ agents[a].phase = "streaming"
    /\ streams[a] = "streaming"
    /\ uiEvents' = Append(uiEvents,
        [ type    |-> "stream_chunk",
          payload |-> chunk,
          agent   |-> a,
          session |-> ActiveSession(a)
        ])
    /\ eventBus' = Append(eventBus,
        [ type    |-> "stream_chunk",
          payload |-> chunk,
          agent   |-> a,
          session |-> ActiveSession(a)
        ])
    /\ UNCHANGED << coreReady, interfaces, agents, sessionOf, messages, checkpoints,
                    contextView, toolRegistry, pendingToolOps, completedToolOps,
                    streams, messageBus, runModeOf, engineIter,
                    responseTerminated, taskTerminated, tasks >>

FinalizeLLMMessage(a, txt) ==
    /\ a \in Agents
    /\ agents[a].phase = "streaming"
    /\ messages' = [messages EXCEPT
        ![ActiveSession(a)] = Append(@,
            [ sender    |-> a,
              recipient |-> "human",
              kind      |-> "message",
              category  |-> "DIALOG",
              content   |-> txt,
              session   |-> ActiveSession(a),
              channel   |-> "human",
              msgId     |-> Len(@) + 1
            ])
       ]
    /\ streams' = [streams EXCEPT ![a] = "finalized"]
    /\ agents' = [agents EXCEPT ![a].phase = "await_action_parse"]
    /\ UNCHANGED << coreReady, interfaces, sessionOf, checkpoints, contextView,
                    toolRegistry, pendingToolOps, completedToolOps, eventBus,
                    messageBus, uiEvents, runModeOf, engineIter,
                    responseTerminated, taskTerminated, tasks >>

ParseAndQueueToolAction(a, tool, params) ==
    /\ a \in Agents
    /\ agents[a].phase = "await_action_parse"
    /\ tool \in agents[a].enabledTools
    /\ tool \in toolRegistry
    /\ pendingToolOps' = pendingToolOps \cup {
        [ id     |-> Cardinality(pendingToolOps) + Cardinality(completedToolOps) + 1,
          agent  |-> a,
          tool   |-> tool,
          params |-> params,
          status |-> "queued",
          result |-> NULL
        ]
       }
    /\ agents' = [agents EXCEPT ![a].phase = "await_tool"]
    /\ messageBus' = Append(messageBus,
        [ sender    |-> a,
          recipient |-> NULL,
          kind      |-> "action",
          channel   |-> "direct",
          content   |-> tool
        ])
    /\ UNCHANGED << coreReady, interfaces, sessionOf, messages, checkpoints,
                    contextView, toolRegistry, completedToolOps, streams,
                    eventBus, uiEvents, runModeOf, engineIter,
                    responseTerminated, taskTerminated, tasks >>

ExecuteTool(op) ==
    /\ op \in pendingToolOps
    /\ op.tool \in toolRegistry
    /\ op.tool \in agents[op.agent].enabledTools
    /\ WithinWorkspace(op.params)
    /\ pendingToolOps' = pendingToolOps \ {op}
    /\ completedToolOps' = completedToolOps \cup {
        [op EXCEPT !.status = "ok", !.result = "tool-result"]
       }
    /\ messages' = [messages EXCEPT
        ![ActiveSession(op.agent)] = Append(@,
            [ sender    |-> "system",
              recipient |-> op.agent,
              kind      |-> "tool_result",
              category  |-> "SYSTEM_OUTPUT",
              content   |-> <<"tool:", op.tool, " result">>,
              session   |-> ActiveSession(op.agent),
              channel   |-> "direct",
              msgId     |-> Len(@) + 1
            ])
       ]
    /\ eventBus' = Append(eventBus,
        [ type    |-> "action_executed",
          payload |-> op.tool,
          agent   |-> op.agent,
          session |-> ActiveSession(op.agent)
        ])
    /\ agents' = [agents EXCEPT ![op.agent].phase = "await_llm"]
    /\ UNCHANGED << coreReady, interfaces, sessionOf, checkpoints, contextView,
                    toolRegistry, streams, messageBus, uiEvents, runModeOf,
                    engineIter, responseTerminated, taskTerminated, tasks >>

TrimContextWindow(a) ==
    /\ a \in Agents
    /\ ActiveSession(a) # NULL
    /\ NeedsTrim(a)
    /\ contextView' = [contextView EXCEPT
        ![a] = PreserveSystemThenRecent(messages[ActiveSession(a)])
       ]
    /\ UNCHANGED << coreReady, interfaces, agents, sessionOf, messages, checkpoints,
                    toolRegistry, pendingToolOps, completedToolOps, streams,
                    eventBus, messageBus, uiEvents, runModeOf, engineIter,
                    responseTerminated, taskTerminated, tasks >>

CreateCheckpoint(a, c) ==
    /\ a \in Agents
    /\ c \in CheckpointIds
    /\ ActiveSession(a) # NULL
    /\ checkpoints' = [checkpoints EXCEPT
        ![c] = [session |-> ActiveSession(a), snapshot |-> messages[ActiveSession(a)]]
       ]
    /\ eventBus' = Append(eventBus,
        [ type    |-> "progress",
          payload |-> "checkpoint_created",
          agent   |-> a,
          session |-> ActiveSession(a)
        ])
    /\ UNCHANGED << coreReady, interfaces, agents, sessionOf, messages, contextView,
                    toolRegistry, pendingToolOps, completedToolOps, streams,
                    messageBus, uiEvents, runModeOf, engineIter,
                    responseTerminated, taskTerminated, tasks >>

RestoreCheckpoint(a, c) ==
    /\ a \in Agents
    /\ c \in CheckpointIds
    /\ checkpoints[c].session = ActiveSession(a)
    /\ messages' = [messages EXCEPT
        ![ActiveSession(a)] = checkpoints[c].snapshot
       ]
    /\ agents' = [agents EXCEPT ![a].phase = "ready"]
    /\ eventBus' = Append(eventBus,
        [ type    |-> "progress",
          payload |-> "checkpoint_restored",
          agent   |-> a,
          session |-> ActiveSession(a)
        ])
    /\ UNCHANGED << coreReady, interfaces, sessionOf, checkpoints, contextView,
                    toolRegistry, pendingToolOps, completedToolOps, streams,
                    messageBus, uiEvents, runModeOf, engineIter,
                    responseTerminated, taskTerminated, tasks >>

SpawnSubAgent(parent, child, shared) ==
    /\ parent \in Agents /\ child \in Agents /\ child # parent
    /\ agents[parent].state \in {"IDLE","RUNNING"}
    /\ Cardinality({ t \in tasks : t.status = "RUNNING" }) < MaxConcurrentTasks
    /\ agents' = [agents EXCEPT
        ![child].state = "PENDING",
        ![child].phase = "ready",
        ![child].parent = parent,
        ![child].sharedContextWith = IF shared THEN parent ELSE NULL
       ]
    /\ sessionOf' = [sessionOf EXCEPT
        ![child] = IF shared THEN ActiveSession(parent)
                   ELSE CHOOSE s \in SessionIds : s # ActiveSession(parent)
       ]
    /\ runModeOf' = [runModeOf EXCEPT ![child] = runModeOf[parent]]
    /\ eventBus' = Append(eventBus,
        [ type    |-> "agent_state",
          payload |-> "spawn",
          agent   |-> child,
          session |-> sessionOf'[child]
        ])
    /\ UNCHANGED << coreReady, interfaces, messages, checkpoints, contextView,
                    toolRegistry, pendingToolOps, completedToolOps, streams,
                    messageBus, uiEvents, engineIter, responseTerminated,
                    taskTerminated, tasks >>

SendBusMessage(sender, recipient, kind, channel, txt) ==
    /\ sender \in Agents \cup {"human"}
    /\ recipient \in Agents \cup {"human", NULL}
    /\ kind \in {"message","action","status","event"}
    /\ channel \in Channels
    /\ messageBus' = Append(messageBus,
        [ sender    |-> sender,
          recipient |-> recipient,
          kind      |-> kind,
          channel   |-> channel,
          content   |-> txt
        ])
    /\ UNCHANGED << coreReady, interfaces, agents, sessionOf, messages, checkpoints,
                    contextView, toolRegistry, pendingToolOps, completedToolOps,
                    streams, eventBus, uiEvents, runModeOf, engineIter,
                    responseTerminated, taskTerminated, tasks >>

StartTask(a, objective) ==
    /\ a \in Agents
    /\ runModeOf[a] = "task"
    /\ tasks' = tasks \cup {
        [ owner |-> a, status |-> "RUNNING", objective |-> objective ]
       }
    /\ agents' = [agents EXCEPT ![a].state = "RUNNING", ![a].phase = "await_llm"]
    /\ UNCHANGED << coreReady, interfaces, sessionOf, messages, checkpoints,
                    contextView, toolRegistry, pendingToolOps, completedToolOps,
                    streams, eventBus, messageBus, uiEvents, runModeOf, engineIter,
                    responseTerminated, taskTerminated >>

FinishResponse(a) ==
    /\ a \in Agents
    /\ runModeOf[a] = "chat"
    /\ agents[a].state = "RUNNING"
    /\ responseTerminated' = [responseTerminated EXCEPT ![a] = TRUE]
    /\ agents' = [agents EXCEPT ![a].phase = "finished", ![a].state = "IDLE"]
    /\ eventBus' = Append(eventBus,
        [ type    |-> "progress",
          payload |-> "finish_response",
          agent   |-> a,
          session |-> ActiveSession(a)
        ])
    /\ UNCHANGED << coreReady, interfaces, sessionOf, messages, checkpoints,
                    contextView, toolRegistry, pendingToolOps, completedToolOps,
                    streams, messageBus, uiEvents, runModeOf, engineIter,
                    taskTerminated, tasks >>

FinishTask(a) ==
    /\ a \in Agents
    /\ runModeOf[a] = "task"
    /\ agents[a].state = "RUNNING"
    /\ taskTerminated' = [taskTerminated EXCEPT ![a] = TRUE]
    /\ agents' = [agents EXCEPT ![a].phase = "finished", ![a].state = "COMPLETED"]
    /\ tasks' = { [t EXCEPT !.status = "COMPLETED"] : t \in tasks /\ t.owner = a }
                \cup { t \in tasks : t.owner # a }
    /\ eventBus' = Append(eventBus,
        [ type    |-> "progress",
          payload |-> "finish_task",
          agent   |-> a,
          session |-> ActiveSession(a)
        ])
    /\ UNCHANGED << coreReady, interfaces, sessionOf, messages, checkpoints,
                    contextView, toolRegistry, pendingToolOps, completedToolOps,
                    streams, messageBus, uiEvents, runModeOf, engineIter,
                    responseTerminated >>

FailAgent(a) ==
    /\ a \in Agents
    /\ agents[a].state \in {"PENDING","RUNNING","PAUSED"}
    /\ agents' = [agents EXCEPT ![a].state = "FAILED", ![a].phase = "finished"]
    /\ eventBus' = Append(eventBus,
        [ type    |-> "agent_state",
          payload |-> "failed",
          agent   |-> a,
          session |-> ActiveSession(a)
        ])
    /\ UNCHANGED << coreReady, interfaces, sessionOf, messages, checkpoints,
                    contextView, toolRegistry, pendingToolOps, completedToolOps,
                    streams, messageBus, uiEvents, runModeOf, engineIter,
                    responseTerminated, taskTerminated, tasks >>

CancelAgent(a) ==
    /\ a \in Agents
    /\ agents[a].state \in {"PENDING","RUNNING","PAUSED"}
    /\ agents' = [agents EXCEPT ![a].state = "CANCELLED", ![a].phase = "finished"]
    /\ eventBus' = Append(eventBus,
        [ type    |-> "agent_state",
          payload |-> "cancelled",
          agent   |-> a,
          session |-> ActiveSession(a)
        ])
    /\ UNCHANGED << coreReady, interfaces, sessionOf, messages, checkpoints,
                    contextView, toolRegistry, pendingToolOps, completedToolOps,
                    streams, messageBus, uiEvents, runModeOf, engineIter,
                    responseTerminated, taskTerminated, tasks >>

(***************************************************************************)
(* Next-state relation                                                     *)
(***************************************************************************)

Next ==
    \/ \E i \in interfaces, a \in Agents, txt \in STRING :
          ReceiveUserInput(i, a, txt)
    \/ \E a \in Agents :
          InvokeLLM(a)
    \/ \E a \in Agents, chunk \in STRING :
          StreamChunk(a, chunk)
    \/ \E a \in Agents, txt \in STRING :
          FinalizeLLMMessage(a, txt)
    \/ \E a \in Agents, tool \in ToolNames, params \in STRING :
          ParseAndQueueToolAction(a, tool, params)
    \/ \E op \in pendingToolOps :
          ExecuteTool(op)
    \/ \E a \in Agents :
          TrimContextWindow(a)
    \/ \E a \in Agents, c \in CheckpointIds :
          CreateCheckpoint(a, c)
    \/ \E a \in Agents, c \in CheckpointIds :
          RestoreCheckpoint(a, c)
    \/ \E parent \in Agents, child \in Agents, shared \in BOOLEAN :
          SpawnSubAgent(parent, child, shared)
    \/ \E sender \in Agents \cup {"human"},
          recipient \in Agents \cup {"human", NULL},
          kind \in {"message","action","status","event"},
          channel \in Channels,
          txt \in STRING :
          SendBusMessage(sender, recipient, kind, channel, txt)
    \/ \E a \in Agents, objective \in STRING :
          StartTask(a, objective)
    \/ \E a \in Agents :
          FinishResponse(a)
    \/ \E a \in Agents :
          FinishTask(a)
    \/ \E a \in Agents :
          FailAgent(a)
    \/ \E a \in Agents :
          CancelAgent(a)

Spec ==
    Init /\ [][Next]_vars

(***************************************************************************)
(* Safety invariants                                                       *)
(***************************************************************************)

NoImplicitResponseExit ==
    \A a \in Agents :
        runModeOf[a] = "chat" /\ agents[a].phase = "finished"
        => responseTerminated[a]

NoImplicitTaskExit ==
    \A a \in Agents :
        runModeOf[a] = "task" /\ agents[a].state = "COMPLETED"
        => taskTerminated[a]

WorkspaceSafety ==
    \A op \in pendingToolOps \cup completedToolOps :
        WithinWorkspace(op.params)

SystemMessagesPreservedOnTrim ==
    \A a \in Agents :
        NeedsTrim(a)
        => \A m \in SeqToSet(messages[ActiveSession(a)]) :
              m.category = "SYSTEM" => m \in contextView[a]

ToolExecutionAuthorized ==
    \A op \in pendingToolOps \cup completedToolOps :
        op.tool \in toolRegistry /\ op.tool \in agents[op.agent].enabledTools

SharedContextSessionConsistency ==
    \A a \in Agents :
        agents[a].sharedContextWith # NULL
        => sessionOf[a] = sessionOf[agents[a].sharedContextWith]

CheckpointMatchesSession ==
    \A c \in CheckpointIds :
        checkpoints[c].session \in SessionIds

BoundedConcurrentTasks ==
    Cardinality({ t \in tasks : t.status = "RUNNING" }) <= MaxConcurrentTasks

Safety ==
    /\ TypeOK
    /\ NoImplicitResponseExit
    /\ NoImplicitTaskExit
    /\ WorkspaceSafety
    /\ ToolExecutionAuthorized
    /\ SharedContextSessionConsistency
    /\ CheckpointMatchesSession
    /\ BoundedConcurrentTasks

(***************************************************************************)
(* Liveness / progress                                                     *)
(***************************************************************************)

ToolCallEventuallyResolves ==
    \A op \in pendingToolOps :
        <> (\E done \in completedToolOps : done.id = op.id)

ChatEventuallySettles ==
    \A a \in Agents :
        runModeOf[a] = "chat" /\ agents[a].state = "RUNNING"
        ~> (responseTerminated[a] \/ engineIter[a] = MaxIterations
            \/ agents[a].state \in {"FAILED","CANCELLED"})

TaskEventuallySettles ==
    \A a \in Agents :
        runModeOf[a] = "task" /\ agents[a].state = "RUNNING"
        ~> (taskTerminated[a]
            \/ agents[a].state \in {"FAILED","CANCELLED"})

EventuallyStreamFinalizes ==
    \A a \in Agents :
        streams[a] = "streaming" ~> (streams[a] = "finalized"
                                     \/ agents[a].state \in {"FAILED","CANCELLED"})

Liveness ==
    /\ ToolCallEventuallyResolves
    /\ ChatEventuallySettles
    /\ TaskEventuallySettles
    /\ EventuallyStreamFinalizes

=============================================================================
```

## Notes

This spec is designed to mirror the major architecture claims in the current repo documentation:

- `PenguinCore` as coordinator across interfaces and subsystems
- `Engine`-driven iterative loop
- `ConversationManager` persistence and context trimming
- `ToolManager` / action execution lifecycle
- MessageBus/EventBus communication
- Multi-agent spawning, context sharing, and bounded concurrency
- Explicit `finish_response` / `finish_task` termination semantics

## Potential Follow-Ups

If you want a more formal next step, the best options are:

1. Convert this into a **bounded TLC-runnable model**.
2. Split it into smaller specs:
   - `PenguinConversation.tla`
   - `PenguinTools.tla`
   - `PenguinMultiAgent.tla`
3. Add a short `MC.cfg` sketch with tiny finite domains for model checking.
