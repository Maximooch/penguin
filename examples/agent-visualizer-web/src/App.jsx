import React, { useState, useEffect, useCallback } from 'react'
import {
  Play, Pause, Square, CheckCircle, XCircle, Clock,
  ChevronRight, ChevronDown, MessageSquare, Cpu, Zap,
  Activity, Users, GitBranch, X, Send, Terminal
} from 'lucide-react'

// Agent states and their visual properties
const AGENT_STATES = {
  PENDING: { label: 'Pending', color: 'text-slate-400', bg: 'bg-slate-700', icon: Clock },
  RUNNING: { label: 'Running', color: 'text-green-400', bg: 'bg-green-900/50', icon: Play },
  PAUSED: { label: 'Paused', color: 'text-yellow-400', bg: 'bg-yellow-900/50', icon: Pause },
  COMPLETED: { label: 'Completed', color: 'text-emerald-400', bg: 'bg-emerald-900/30', icon: CheckCircle },
  FAILED: { label: 'Failed', color: 'text-red-400', bg: 'bg-red-900/30', icon: XCircle },
  CANCELLED: { label: 'Cancelled', color: 'text-slate-500', bg: 'bg-slate-800', icon: Square },
}

const ROLES = ['planner', 'implementer', 'reviewer', 'tester', 'analyzer', 'explorer', 'debugger', 'optimizer', 'documenter', 'refactor']
const TASKS = [
  'Analyzing codebase structure',
  'Implementing authentication flow',
  'Reviewing pull request #42',
  'Running integration tests',
  'Searching for API endpoints',
  'Refactoring database layer',
  'Debugging memory leak',
  'Optimizing query performance',
  'Generating API documentation',
  'Exploring dependency graph',
]

// Generate mock session messages
const generateSessionLog = (agentId, role) => {
  const messages = []
  const count = Math.floor(Math.random() * 8) + 3

  for (let i = 0; i < count; i++) {
    const isUser = i % 3 === 0
    const isSystem = i % 5 === 0 && !isUser

    if (isSystem) {
      messages.push({
        id: `${agentId}-msg-${i}`,
        type: 'system',
        content: `[Tool: ${['read_file', 'search_code', 'write_file', 'run_command'][Math.floor(Math.random() * 4)]}] Execution completed`,
        timestamp: Date.now() - (count - i) * 30000,
      })
    } else if (isUser) {
      messages.push({
        id: `${agentId}-msg-${i}`,
        type: 'user',
        content: `Delegated task: ${TASKS[Math.floor(Math.random() * TASKS.length)]}`,
        timestamp: Date.now() - (count - i) * 30000,
      })
    } else {
      messages.push({
        id: `${agentId}-msg-${i}`,
        type: 'assistant',
        content: getAssistantMessage(role),
        timestamp: Date.now() - (count - i) * 30000,
      })
    }
  }
  return messages
}

const getAssistantMessage = (role) => {
  const messages = {
    planner: "I'll break this down into 3 phases: analysis, implementation, and validation...",
    implementer: "Creating the new module with proper error handling and type safety...",
    reviewer: "Found 2 potential issues: missing null check on line 42, and unused import...",
    tester: "Running test suite... 23/25 tests passing. Investigating 2 failures...",
    analyzer: "Detected circular dependency between modules A and B. Suggesting refactor...",
    explorer: "Found 15 files matching pattern. Most relevant: src/core/engine.py...",
    debugger: "Stack trace indicates the error originates from async context switching...",
    optimizer: "Query can be optimized by adding index on user_id column...",
    documenter: "Generated API documentation for 12 endpoints with examples...",
    refactor: "Extracted common logic into shared utility. Reduced duplication by 40%...",
  }
  return messages[role] || "Processing task..."
}

// Create initial agents
const createAgents = (count = 24) => {
  const agents = {}

  // Parent agent
  agents['penguin-main'] = {
    id: 'penguin-main',
    role: 'orchestrator',
    parentId: null,
    state: 'RUNNING',
    progress: 0,
    task: 'Orchestrating sub-agents',
    tokensUsed: 12500,
    tokensLimit: 200000,
    sharesContext: false,
    startTime: Date.now() - 120000,
    children: [],
    messagesSent: 15,
    messagesReceived: 8,
    sessionLog: [],
  }

  // Sub-agents
  for (let i = 0; i < count; i++) {
    const id = `worker-${String(i).padStart(2, '0')}`
    const role = ROLES[Math.floor(Math.random() * ROLES.length)]
    const state = ['PENDING', 'PENDING', 'RUNNING', 'RUNNING', 'RUNNING', 'PAUSED', 'COMPLETED'][Math.floor(Math.random() * 7)]

    agents[id] = {
      id,
      role,
      parentId: 'penguin-main',
      state,
      progress: state === 'COMPLETED' ? 100 : state === 'RUNNING' ? Math.random() * 80 : 0,
      task: TASKS[Math.floor(Math.random() * TASKS.length)],
      tokensUsed: Math.floor(Math.random() * 30000),
      tokensLimit: 50000 + Math.floor(Math.random() * 30000),
      sharesContext: Math.random() < 0.4,
      startTime: state !== 'PENDING' ? Date.now() - Math.floor(Math.random() * 180000) : null,
      children: [],
      messagesSent: Math.floor(Math.random() * 10),
      messagesReceived: Math.floor(Math.random() * 8),
      sessionLog: generateSessionLog(id, role),
    }
    agents['penguin-main'].children.push(id)
  }

  return agents
}

// Header Component
const Header = ({ agents, startTime }) => {
  const states = Object.values(agents).reduce((acc, a) => {
    acc[a.state] = (acc[a.state] || 0) + 1
    return acc
  }, {})

  const totalTokens = Object.values(agents).reduce((sum, a) => sum + a.tokensUsed, 0)
  const elapsed = Math.floor((Date.now() - startTime) / 1000)
  const minutes = Math.floor(elapsed / 60)
  const seconds = elapsed % 60

  return (
    <div className="bg-slate-900/80 border-b border-slate-800 px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl">🐧</span>
          <h1 className="text-lg font-bold text-cyan-400">PENGUIN MULTI-AGENT SYSTEM</h1>
        </div>

        <div className="flex items-center gap-6 text-sm">
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse-dot"></span>
              <span className="text-green-400">{states.RUNNING || 0} running</span>
            </span>
            <span className="flex items-center gap-1.5 text-slate-400">
              <Clock size={14} />
              {states.PENDING || 0} pending
            </span>
            <span className="flex items-center gap-1.5 text-yellow-400">
              <Pause size={14} />
              {states.PAUSED || 0} paused
            </span>
            <span className="flex items-center gap-1.5 text-emerald-400">
              <CheckCircle size={14} />
              {states.COMPLETED || 0} done
            </span>
            <span className="flex items-center gap-1.5 text-red-400">
              <XCircle size={14} />
              {states.FAILED || 0} failed
            </span>
          </div>

          <div className="border-l border-slate-700 pl-6 flex items-center gap-4">
            <span className="text-blue-400">
              ⏱ {String(minutes).padStart(2, '0')}:{String(seconds).padStart(2, '0')}
            </span>
            <span className="text-purple-400">
              🎫 {totalTokens.toLocaleString()} tokens
            </span>
            <span className="text-slate-500">
              {Object.keys(agents).length} agents
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

// Agent Tree Item
const AgentTreeItem = ({ agent, isSelected, onSelect, isExpanded, onToggle, children }) => {
  const StateIcon = AGENT_STATES[agent.state].icon
  const stateStyle = AGENT_STATES[agent.state]

  return (
    <div>
      <div
        onClick={() => onSelect(agent.id)}
        className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer transition-colors ${
          isSelected ? 'bg-cyan-900/40 border border-cyan-700' : 'hover:bg-slate-800'
        }`}
      >
        {agent.children?.length > 0 && (
          <button
            onClick={(e) => { e.stopPropagation(); onToggle() }}
            className="p-0.5 hover:bg-slate-700 rounded"
          >
            {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        )}
        <StateIcon size={14} className={stateStyle.color} />
        <span className={`text-sm ${isSelected ? 'text-cyan-300' : 'text-slate-300'}`}>
          {agent.id}
        </span>
        <span className="text-xs text-slate-500">{agent.role}</span>
        {agent.sharesContext && (
          <span className="text-xs text-purple-400" title="Shares context">⟷</span>
        )}
      </div>
      {isExpanded && children && (
        <div className="ml-4 border-l border-slate-800 pl-2">
          {children}
        </div>
      )}
    </div>
  )
}

// Agent Tree Panel
const AgentTree = ({ agents, selectedAgentId, onSelectAgent }) => {
  const [expandedNodes, setExpandedNodes] = useState(new Set(['penguin-main']))
  const parent = agents['penguin-main']

  const toggleNode = (id) => {
    setExpandedNodes(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  // Group children by state
  const groupedChildren = parent.children.reduce((acc, childId) => {
    const child = agents[childId]
    if (!acc[child.state]) acc[child.state] = []
    acc[child.state].push(child)
    return acc
  }, {})

  const stateOrder = ['RUNNING', 'PENDING', 'PAUSED', 'COMPLETED', 'FAILED', 'CANCELLED']

  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-3 h-full overflow-auto">
      <div className="text-sm font-semibold text-slate-400 mb-3 flex items-center gap-2">
        <GitBranch size={14} />
        Agent Hierarchy
      </div>

      <AgentTreeItem
        agent={parent}
        isSelected={selectedAgentId === parent.id}
        onSelect={onSelectAgent}
        isExpanded={expandedNodes.has(parent.id)}
        onToggle={() => toggleNode(parent.id)}
      >
        {stateOrder.map(state => {
          const children = groupedChildren[state]
          if (!children?.length) return null

          return (
            <div key={state} className="mb-2">
              <div className={`text-xs font-medium mb-1 ${AGENT_STATES[state].color}`}>
                {AGENT_STATES[state].label} ({children.length})
              </div>
              {children.slice(0, 8).map(child => (
                <AgentTreeItem
                  key={child.id}
                  agent={child}
                  isSelected={selectedAgentId === child.id}
                  onSelect={onSelectAgent}
                />
              ))}
              {children.length > 8 && (
                <div className="text-xs text-slate-500 pl-6">
                  ... +{children.length - 8} more
                </div>
              )}
            </div>
          )
        })}
      </AgentTreeItem>
    </div>
  )
}

// Progress Bar
const ProgressBar = ({ value, className = '' }) => {
  const filled = Math.floor(value / 5)
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div className="flex-1 h-2 bg-slate-800 rounded overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-cyan-500 to-green-500 transition-all duration-300"
          style={{ width: `${value}%` }}
        />
      </div>
      <span className={`text-xs w-12 text-right ${value > 50 ? 'text-green-400' : 'text-yellow-400'}`}>
        {value.toFixed(1)}%
      </span>
    </div>
  )
}

// Running Agents Table
const RunningAgentsTable = ({ agents, selectedAgentId, onSelectAgent }) => {
  const running = Object.values(agents)
    .filter(a => a.state === 'RUNNING' && a.id !== 'penguin-main')
    .sort((a, b) => a.id.localeCompare(b.id))

  return (
    <div className="bg-slate-900/50 border border-green-900/50 rounded-lg overflow-hidden">
      <div className="px-4 py-2 border-b border-slate-800 flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse-dot"></span>
        <span className="text-sm font-semibold text-green-400">Running Agents ({running.length})</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500 border-b border-slate-800">
              <th className="px-4 py-2 font-medium">Agent</th>
              <th className="px-4 py-2 font-medium">Role</th>
              <th className="px-4 py-2 font-medium">Task</th>
              <th className="px-4 py-2 font-medium w-48">Progress</th>
              <th className="px-4 py-2 font-medium text-right">Tokens</th>
              <th className="px-4 py-2 font-medium text-right">Time</th>
              <th className="px-4 py-2 font-medium text-center">Ctx</th>
              <th className="px-4 py-2 font-medium text-right">Msg</th>
            </tr>
          </thead>
          <tbody>
            {running.slice(0, 12).map(agent => {
              const elapsed = agent.startTime ? Math.floor((Date.now() - agent.startTime) / 1000) : 0
              const tokenPct = agent.tokensUsed / agent.tokensLimit * 100

              return (
                <tr
                  key={agent.id}
                  onClick={() => onSelectAgent(agent.id)}
                  className={`border-b border-slate-800/50 cursor-pointer transition-colors ${
                    selectedAgentId === agent.id ? 'bg-cyan-900/30' : 'hover:bg-slate-800/50'
                  }`}
                >
                  <td className="px-4 py-2 text-cyan-400">{agent.id}</td>
                  <td className="px-4 py-2 text-slate-400">{agent.role}</td>
                  <td className="px-4 py-2 text-slate-300 truncate max-w-[200px]">{agent.task}</td>
                  <td className="px-4 py-2">
                    <ProgressBar value={agent.progress} />
                  </td>
                  <td className={`px-4 py-2 text-right ${
                    tokenPct < 60 ? 'text-green-400' : tokenPct < 80 ? 'text-yellow-400' : 'text-red-400'
                  }`}>
                    {agent.tokensUsed.toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-400">
                    {elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`}
                  </td>
                  <td className="px-4 py-2 text-center">
                    {agent.sharesContext ? (
                      <span className="text-purple-400">⟷</span>
                    ) : (
                      <span className="text-slate-600">○</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-400">
                    {agent.messagesSent + agent.messagesReceived}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {running.length > 12 && (
          <div className="px-4 py-2 text-sm text-slate-500">
            ... +{running.length - 12} more running
          </div>
        )}
      </div>
    </div>
  )
}

// Agent Detail Panel
const AgentDetailPanel = ({ agent, onClose }) => {
  if (!agent) return null

  const StateIcon = AGENT_STATES[agent.state].icon
  const stateStyle = AGENT_STATES[agent.state]
  const elapsed = agent.startTime ? Math.floor((Date.now() - agent.startTime) / 1000) : 0

  return (
    <div className="bg-slate-900 border-l border-slate-800 h-full flex flex-col animate-slide-in">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <StateIcon size={18} className={stateStyle.color} />
          <div>
            <h3 className="font-semibold text-cyan-400">{agent.id}</h3>
            <span className="text-xs text-slate-500">{agent.role}</span>
          </div>
        </div>
        <button onClick={onClose} className="p-1 hover:bg-slate-800 rounded">
          <X size={18} className="text-slate-400" />
        </button>
      </div>

      {/* Stats */}
      <div className="px-4 py-3 border-b border-slate-800 grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-slate-500 text-xs">Status</div>
          <div className={stateStyle.color}>{stateStyle.label}</div>
        </div>
        <div>
          <div className="text-slate-500 text-xs">Progress</div>
          <div className="text-slate-300">{agent.progress.toFixed(1)}%</div>
        </div>
        <div>
          <div className="text-slate-500 text-xs">Tokens</div>
          <div className="text-purple-400">
            {agent.tokensUsed.toLocaleString()} / {agent.tokensLimit.toLocaleString()}
          </div>
        </div>
        <div>
          <div className="text-slate-500 text-xs">Elapsed</div>
          <div className="text-blue-400">
            {elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`}
          </div>
        </div>
        <div className="col-span-2">
          <div className="text-slate-500 text-xs">Current Task</div>
          <div className="text-slate-300">{agent.task}</div>
        </div>
        <div>
          <div className="text-slate-500 text-xs">Context</div>
          <div className={agent.sharesContext ? 'text-purple-400' : 'text-slate-500'}>
            {agent.sharesContext ? '⟷ Shared with parent' : '○ Isolated'}
          </div>
        </div>
        <div>
          <div className="text-slate-500 text-xs">Messages</div>
          <div className="text-slate-300">
            ↑{agent.messagesSent} ↓{agent.messagesReceived}
          </div>
        </div>
      </div>

      {/* Session Log */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-4 py-2 border-b border-slate-800 flex items-center gap-2">
          <Terminal size={14} className="text-slate-400" />
          <span className="text-sm font-medium text-slate-400">Session Log</span>
        </div>
        <div className="flex-1 overflow-auto p-3 space-y-3">
          {agent.sessionLog.map(msg => (
            <div key={msg.id} className={`rounded-lg p-3 text-sm ${
              msg.type === 'user' ? 'bg-blue-900/30 border border-blue-800/50' :
              msg.type === 'system' ? 'bg-slate-800/50 border border-slate-700/50' :
              'bg-slate-800 border border-slate-700'
            }`}>
              <div className="flex items-center justify-between mb-1">
                <span className={`text-xs font-medium ${
                  msg.type === 'user' ? 'text-blue-400' :
                  msg.type === 'system' ? 'text-yellow-400' :
                  'text-cyan-400'
                }`}>
                  {msg.type === 'user' ? 'Parent Agent' :
                   msg.type === 'system' ? 'System' :
                   agent.id}
                </span>
                <span className="text-xs text-slate-600">
                  {new Date(msg.timestamp).toLocaleTimeString()}
                </span>
              </div>
              <div className={msg.type === 'system' ? 'text-yellow-200/80 font-mono text-xs' : 'text-slate-300'}>
                {msg.content}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// Activity Feed
const ActivityFeed = ({ agents }) => {
  const [activities, setActivities] = useState([])

  useEffect(() => {
    const interval = setInterval(() => {
      const running = Object.values(agents).filter(a => a.state === 'RUNNING')
      if (running.length === 0) return

      const agent = running[Math.floor(Math.random() * running.length)]
      const types = ['executing', 'tool', 'message', 'progress']
      const type = types[Math.floor(Math.random() * types.length)]

      const newActivity = {
        id: Date.now(),
        agentId: agent.id,
        type,
        message: type === 'executing' ? `executing: ${agent.task.slice(0, 30)}...` :
                 type === 'tool' ? `called tool: ${['read_file', 'search', 'write_file'][Math.floor(Math.random() * 3)]}` :
                 type === 'message' ? 'sent message to parent' :
                 `progress: ${agent.progress.toFixed(0)}%`,
        timestamp: Date.now(),
      }

      setActivities(prev => [newActivity, ...prev.slice(0, 9)])
    }, 800)

    return () => clearInterval(interval)
  }, [agents])

  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-3 h-full overflow-hidden">
      <div className="text-sm font-semibold text-slate-400 mb-2 flex items-center gap-2">
        <Activity size={14} />
        Recent Activity
      </div>
      <div className="space-y-1 text-xs overflow-auto h-[calc(100%-28px)]">
        {activities.map(activity => (
          <div key={activity.id} className="flex items-center gap-2 text-slate-400">
            <span className={`w-1.5 h-1.5 rounded-full ${
              activity.type === 'executing' ? 'bg-green-400' :
              activity.type === 'tool' ? 'bg-yellow-400' :
              activity.type === 'message' ? 'bg-blue-400' :
              'bg-purple-400'
            }`}></span>
            <span className="text-cyan-400">{activity.agentId}</span>
            <span className="truncate">{activity.message}</span>
          </div>
        ))}
        {activities.length === 0 && (
          <div className="text-slate-600 italic">No recent activity</div>
        )}
      </div>
    </div>
  )
}

// Stats Panel
const StatsPanel = ({ agents }) => {
  const agentList = Object.values(agents)
  const running = agentList.filter(a => a.state === 'RUNNING')
  const totalMessages = agentList.reduce((sum, a) => sum + a.messagesSent, 0)
  const sharedCtx = agentList.filter(a => a.sharesContext).length
  const avgProgress = running.length > 0
    ? running.reduce((sum, a) => sum + a.progress, 0) / running.length
    : 0

  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-3 h-full">
      <div className="text-sm font-semibold text-slate-400 mb-3 flex items-center gap-2">
        <Zap size={14} />
        Statistics
      </div>
      <div className="space-y-3 text-sm">
        <div className="flex justify-between">
          <span className="text-slate-500">Total Messages</span>
          <span className="text-cyan-400">{totalMessages}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">Shared Context</span>
          <span className="text-purple-400">{sharedCtx} agents</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">Avg Progress</span>
          <span className="text-yellow-400">{avgProgress.toFixed(1)}%</span>
        </div>
        <div className="flex justify-between">
          <span className="text-slate-500">Concurrency</span>
          <span className="text-green-400">{running.length} / 10</span>
        </div>
      </div>
    </div>
  )
}

// Main App
export default function App() {
  const [agents, setAgents] = useState(() => createAgents(24))
  const [selectedAgentId, setSelectedAgentId] = useState(null)
  const [startTime] = useState(Date.now())

  // Simulate agent updates
  useEffect(() => {
    const interval = setInterval(() => {
      setAgents(prev => {
        const next = { ...prev }

        Object.values(next).forEach(agent => {
          if (agent.id === 'penguin-main') {
            agent.tokensUsed = Math.min(agent.tokensUsed + Math.floor(Math.random() * 200), agent.tokensLimit)
            return
          }

          if (agent.state === 'PENDING' && Math.random() < 0.08) {
            agent.state = 'RUNNING'
            agent.startTime = Date.now()
            agent.progress = 0
          } else if (agent.state === 'RUNNING') {
            agent.progress = Math.min(agent.progress + Math.random() * 2, 100)
            agent.tokensUsed = Math.min(agent.tokensUsed + Math.floor(Math.random() * 500), agent.tokensLimit)

            if (Math.random() < 0.02) agent.state = 'PAUSED'
            if (agent.progress >= 100) {
              agent.state = Math.random() < 0.9 ? 'COMPLETED' : 'FAILED'
            }
          } else if (agent.state === 'PAUSED' && Math.random() < 0.05) {
            agent.state = 'RUNNING'
          } else if ((agent.state === 'COMPLETED' || agent.state === 'FAILED') && Math.random() < 0.03) {
            agent.state = 'PENDING'
            agent.progress = 0
            agent.task = TASKS[Math.floor(Math.random() * TASKS.length)]
            agent.tokensUsed = 0
            agent.startTime = null
            agent.sessionLog = generateSessionLog(agent.id, agent.role)
          }
        })

        return next
      })
    }, 150)

    return () => clearInterval(interval)
  }, [])

  const selectedAgent = selectedAgentId ? agents[selectedAgentId] : null

  return (
    <div className="h-screen flex flex-col">
      <Header agents={agents} startTime={startTime} />

      <div className="flex-1 flex overflow-hidden">
        {/* Main Content */}
        <div className={`flex-1 flex flex-col p-4 gap-4 overflow-hidden transition-all ${
          selectedAgent ? 'pr-0' : ''
        }`}>
          <div className="flex gap-4 flex-1 min-h-0">
            {/* Left: Tree */}
            <div className="w-72 flex-shrink-0">
              <AgentTree
                agents={agents}
                selectedAgentId={selectedAgentId}
                onSelectAgent={setSelectedAgentId}
              />
            </div>

            {/* Right: Running table */}
            <div className="flex-1 overflow-hidden">
              <RunningAgentsTable
                agents={agents}
                selectedAgentId={selectedAgentId}
                onSelectAgent={setSelectedAgentId}
              />
            </div>
          </div>

          {/* Footer */}
          <div className="flex gap-4 h-40 flex-shrink-0">
            <div className="flex-1">
              <ActivityFeed agents={agents} />
            </div>
            <div className="w-64">
              <StatsPanel agents={agents} />
            </div>
          </div>
        </div>

        {/* Agent Detail Sidebar */}
        {selectedAgent && (
          <div className="w-96 flex-shrink-0">
            <AgentDetailPanel
              agent={selectedAgent}
              onClose={() => setSelectedAgentId(null)}
            />
          </div>
        )}
      </div>
    </div>
  )
}
