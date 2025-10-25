/**
 * Chat session component with streaming message display
 * Handles user input and displays conversation history
 *
 * REFACTORED: Now uses context-based hooks instead of monolithic useChat
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { useConnection } from '../contexts/ConnectionContext';
import { useCommand } from '../contexts/CommandContext';
import { useWebSocket } from '../hooks/useWebSocket';
import { useMessageHistory } from '../hooks/useMessageHistory';
import { useStreaming } from '../hooks/useStreaming';
import { useToolExecution } from '../hooks/useToolExecution';
import { useProgress } from '../hooks/useProgress';
import { MessageList } from './MessageList';
import { ConnectionStatus } from './ConnectionStatus';
import { ToolExecutionList } from './ToolExecution';
import { ProgressIndicator } from './ProgressIndicator';
import { MultiLineInput } from './MultiLineInput';
import { SessionList } from './SessionList';
import { SessionPickerModal } from './SessionPickerModal';
import { ProjectList } from './ProjectList';
import { TaskList } from './TaskList';
import { SessionAPI } from '../../core/api/SessionAPI.js';
import { ProjectAPI } from '../../core/api/ProjectAPI.js';
import type { Session } from '../../core/types.js';
import type { Project, Task } from '../../core/api/ProjectAPI.js';
import type { RunModeStatus as RunStatus, TaskStreamMessage } from '../../core/api/RunAPI.js';
import { RunAPI } from '../../core/api/RunAPI.js';
import { RunModeStatus } from './RunModeStatus.js';
import { useTab } from '../contexts/TabContext.js';
import { ChatClient } from '../../core/connection/WebSocketClient.js';
import { getConfigPath, validateConfig, getConfigDiagnostics } from '../../config/loader.js';
import { exec } from 'child_process';
import { existsSync } from 'fs';
import { homedir } from 'os';

interface ChatSessionProps {
  conversationId?: string;
}

export function ChatSession({ conversationId: propConversationId }: ChatSessionProps) {
  const { exit } = useApp();
  const [inputKey, setInputKey] = useState(0);
  const [isExiting, setIsExiting] = useState(false);
  const [currentInput, setCurrentInput] = useState('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [showingSessionList, setShowingSessionList] = useState(false);
  const [showSessionPicker, setShowSessionPicker] = useState(false);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [showingProjectList, setShowingProjectList] = useState(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [showingTaskList, setShowingTaskList] = useState(false);
  const [runModeStatus, setRunModeStatus] = useState<RunStatus>({ status: 'idle' });
  const [showingRunMode, setShowingRunMode] = useState(false);
  const [runModeMessage, setRunModeMessage] = useState<string>('');
  const [runModeProgress, setRunModeProgress] = useState<number>(0);
  const reasoningRef = useRef(''); // Use ref instead of state to avoid re-renders
  const sessionAPI = useRef(new SessionAPI('http://localhost:8000'));
  const projectAPI = useRef(new ProjectAPI('http://localhost:8000'));
  const runAPI = useRef(new RunAPI('http://localhost:8000'));
  const runStreamWS = useRef<WebSocket | null>(null);
  const clientRef = useRef<any>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // Each ChatSession creates its own WebSocket client
  useEffect(() => {
    const client = new ChatClient({
      url: 'ws://localhost:8000/api/v1/chat/stream',
      conversationId: propConversationId,
      onConnect: () => {
        setIsConnected(true);
        setError(null);
      },
      onDisconnect: () => {
        setIsConnected(false);
      },
      onError: (err: Error) => {
        setError(err);
        setIsConnected(false);
      },
    });

    client.connect();
    clientRef.current = client;

    return () => {
      client.disconnect();
      clientRef.current = null;
    };
  }, [propConversationId]);

  const { parseInput, getSuggestions } = useCommand();

  const sendMessage = (message: string, options?: { image_path?: string }) => {
    if (clientRef.current && isConnected) {
      clientRef.current.sendMessage(message, options);
    }
  };
  const { messages, addUserMessage, addAssistantMessage, clearMessages } = useMessageHistory();
  const { activeTool, completedTools, clearTools, addActionResults } = useToolExecution();
  const { progress, updateProgress, resetProgress, completeProgress } = useProgress();

  const { streamingText, isStreaming, processToken, complete, reset } = useStreaming({
    onComplete: (finalText: string) => {
      // Add completed streaming message to history with reasoning if present
      if (finalText) {
        // console.error(`[ChatSession] onComplete - finalText length: ${finalText.length}, starts with: "${finalText.substring(0, 100)}"`);
        addAssistantMessage(finalText, reasoningRef.current || undefined);
        reasoningRef.current = ''; // Clear reasoning for next message
        reset(); // Clear streaming text immediately after adding to history
      }
    },
  });

  // Set up WebSocket event handlers
  useEffect(() => {
    const client = clientRef.current;
    if (!client) return;

    client.callbacks.onToken = (token: string) => {
      // console.log(`[ChatSession ${propConversationId}] Received token, length: ${token.length}`);
      processToken(token);
    };

    client.callbacks.onReasoning = (token: string) => {
      // console.log(`[ChatSession ${propConversationId}] Received reasoning token`);
      reasoningRef.current += token;
    };

    client.callbacks.onProgress = (iteration: number, maxIterations: number, message?: string) => {
      updateProgress(iteration, maxIterations, message);
    };

    client.callbacks.onComplete = (actionResults: any) => {
      completeProgress();
      if (actionResults && actionResults.length > 0) {
        // Map backend format to frontend ActionResult format
        const mappedResults = actionResults.map((ar: any) => ({
          action: ar.action_name || ar.action,
          result: ar.output || ar.result,
          status: ar.status,
          timestamp: ar.timestamp || Date.now(),
        }));
        addActionResults(mappedResults);
      }
      complete();
      setTimeout(() => resetProgress(), 1000);
    };
  }, [propConversationId, processToken, complete, addActionResults, updateProgress, completeProgress, resetProgress]);

  const { switchToDashboard, switchConversation } = useTab();

  // Handle global hotkeys
  useInput((input, key) => {
    // Dismiss project/task lists on any key
    if (showingProjectList || showingTaskList) {
      setShowingProjectList(false);
      setShowingTaskList(false);
      return;
    }

    // Ctrl+C and Ctrl+D to exit
    if (key.ctrl && (input === 'c' || input === 'd')) {
      if (!isExiting) {
        setIsExiting(true);
        exit();
      }
    }
    // Ctrl+P to switch to dashboard
    else if (key.ctrl && input === 'p') {
      switchToDashboard();
    }
    // Ctrl+O to open session picker
    else if (key.ctrl && input === 'o') {
      if (!showSessionPicker) {
        setIsLoadingSessions(true);
        setShowSessionPicker(true);
        sessionAPI.current
          .listSessions()
          .then((sessionList) => {
            setSessions(sessionList);
            setIsLoadingSessions(false);
          })
          .catch((err) => {
            // console.error('Failed to load sessions:', err);
            setIsLoadingSessions(false);
            setShowSessionPicker(false);
          });
      }
    }
  });

  const handleTextChange = useCallback((text: string) => {
    setCurrentInput(text);

    // Get autocomplete suggestions if text starts with /
    if (text.startsWith('/')) {
      const sugs = getSuggestions(text);
      setSuggestions(sugs);
    } else {
      setSuggestions([]);
    }
  }, [getSuggestions]);

  const handleCommand = useCallback((commandName: string, args: Record<string, any>) => {
    // Built-in command handlers
    switch (commandName) {
      case 'help':
      case 'h':
      case '?':
        // Show help as a system message
        addAssistantMessage(
          `# Penguin CLI Commands\n\nType \`/help\` to see this message again.\n\n## Available Commands:\n\n### 💬 Chat\n- \`/help\` (aliases: /h, /?) - Show this help\n- \`/clear\` (aliases: /cls, /reset) - Clear chat history\n- \`/chat list\` - List all conversations\n- \`/chat load <id>\` - Load a conversation\n- \`/chat delete <id>\` - Delete a conversation\n- \`/chat new\` - Start a new conversation\n\n### 🚀 Workflow\n- \`/init\` - Initialize project with AI assistance\n- \`/review\` - Review code changes and suggest improvements\n- \`/plan <feature>\` - Create implementation plan for a feature\n- \`/image <path> [message]\` - Attach image for vision analysis\n\n### ⚙️ Configuration\n- \`/setup\` - Run setup wizard (must exit chat first)\n- \`/config edit\` - Open config file in $EDITOR\n- \`/config check\` - Validate current configuration\n- \`/config debug\` - Show diagnostic information\n\n### 🔧 System\n- \`/quit\` (aliases: /exit, /q) - Exit the CLI\n\nMore commands available! See commands.yml for full list.`
        );
        break;

      case 'setup':
        // Show message that setup needs to be run outside of chat
        addUserMessage('/setup');
        addAssistantMessage(
          '⚠️ Setup wizard must be run outside of the interactive chat.\n\n' +
          'Please exit the chat (Ctrl+C) and run:\n\n' +
          '```\ncd penguin-cli && npm run setup\n```\n\n' +
          'This will launch the interactive configuration wizard.'
        );
        break;

      case 'config edit':
        addUserMessage('/config edit');
        {
          const configPath = getConfigPath();

          addAssistantMessage(`Opening config file in external editor...\n\nFile: \`${configPath}\``);

          // Build command based on platform
          let command: string;
          if (process.platform === 'darwin') {
            // macOS: Use 'open -t' to open in default text editor
            command = `open -t "${configPath}"`;
          } else if (process.platform === 'win32') {
            // Windows
            command = `start "" "${configPath}"`;
          } else {
            // Linux
            command = `xdg-open "${configPath}"`;
          }

          // Execute command
          exec(command, (error, stdout, stderr) => {
            if (error) {
              addAssistantMessage(`❌ Failed to open editor: ${error.message}\n\n${stderr}\n\nYou can manually edit: \`${configPath}\``);
            } else {
              addAssistantMessage('✅ Config file opened in external editor.\n\n_Save and close the editor, then reload this CLI to apply changes._');
            }
          });
        }
        break;

      case 'config check':
        addUserMessage('/config check');
        {
          validateConfig().then(result => {
            if (result.valid) {
              let message = '✅ Configuration is valid!\n\n';
              if (result.warnings.length > 0) {
                message += '⚠️  Warnings:\n';
                result.warnings.forEach(warn => {
                  message += `  - ${warn}\n`;
                });
              }
              addAssistantMessage(message);
            } else {
              let message = '❌ Configuration has errors:\n\n';
              result.errors.forEach(err => {
                message += `  - ${err}\n`;
              });
              if (result.warnings.length > 0) {
                message += '\n⚠️  Warnings:\n';
                result.warnings.forEach(warn => {
                  message += `  - ${warn}\n`;
                });
              }
              message += '\nRun `/config edit` to fix these issues or `/setup` to reconfigure.';
              addAssistantMessage(message);
            }
          }).catch(error => {
            addAssistantMessage(`❌ Failed to validate config: ${error}`);
          });
        }
        break;

      case 'config debug':
        addUserMessage('/config debug');
        {
          getConfigDiagnostics().then(diagnostics => {
            addAssistantMessage(diagnostics);
          }).catch(error => {
            addAssistantMessage(`❌ Failed to get diagnostics: ${error}`);
          });
        }
        break;

      case 'image':
      case 'img':
        {
          // Get the raw path - might have quotes
          let imagePath = args.path || '';

          // Strip surrounding quotes if present
          imagePath = imagePath.replace(/^['"]|['"]$/g, '');

          // Get everything after the path as the message
          const message = args.message || 'What do you see in this image?';

          addUserMessage(`/image ${imagePath} ${message}`);

          if (!imagePath) {
            addAssistantMessage('❌ Please provide an image path: `/image <path> [optional message]`');
            break;
          }

          // Expand ~ to home directory
          if (imagePath.startsWith('~')) {
            imagePath = imagePath.replace('~', require('os').homedir());
          }

          // Check if file exists
          if (!existsSync(imagePath)) {
            addAssistantMessage(`❌ Image file not found: \`${imagePath}\`\n\nMake sure the path is correct and the file exists.`);
            break;
          }

          // Send message with image path to backend
          addAssistantMessage(`📎 Sending image: \`${imagePath}\`\n\n_Analyzing image with vision model..._`);
          clearTools();
          sendMessage(message, { image_path: imagePath });
        }
        break;

      case 'clear':
      case 'cls':
      case 'reset':
        // Clear all messages and tool executions
        clearMessages();
        clearTools();
        resetProgress();
        break;

      case 'quit':
      case 'exit':
      case 'q':
        // Exit the application
        if (!isExiting) {
          setIsExiting(true);
          exit();
        }
        break;

      // Session management commands - use REST API
      case 'chat list':
        addUserMessage('/chat list');
        sessionAPI.current.listSessions()
          .then(sessionList => {
            setSessions(sessionList);
            setShowingSessionList(true);
            // Also show as formatted message
            if (sessionList.length === 0) {
              addAssistantMessage('No conversations found.');
            } else {
              const formatted = `📋 Found ${sessionList.length} conversation(s):\n\n` +
                sessionList.slice(0, 10).map(s =>
                  `• ${s.id.slice(0, 8)}: ${s.title || 'Untitled'} (${s.message_count || 0} messages)`
                ).join('\n');
              addAssistantMessage(formatted);
            }
          })
          .catch(err => {
            addAssistantMessage(`Error listing sessions: ${err.message}`);
          });
        break;

      case 'chat load':
        if (args.session_id) {
          addUserMessage(`/chat load ${args.session_id}`);
          clearMessages();
          clearTools();
          resetProgress();
          switchConversation(args.session_id);
          addAssistantMessage(`✓ Switched to session: ${args.session_id.slice(0, 8)}`);
        } else {
          addAssistantMessage('Error: Missing session ID. Usage: `/chat load <session_id>`');
        }
        break;

      case 'chat delete':
        if (args.session_id) {
          addUserMessage(`/chat delete ${args.session_id}`);
          sessionAPI.current.deleteSession(args.session_id)
            .then(success => {
              if (success) {
                addAssistantMessage(`✓ Deleted session: ${args.session_id.slice(0, 8)}`);
                // Refresh the session list if showing
                if (showingSessionList) {
                  sessionAPI.current.listSessions().then(setSessions);
                }
              } else {
                addAssistantMessage(`Error: Session ${args.session_id} not found.`);
              }
            })
            .catch(err => {
              addAssistantMessage(`Error deleting session: ${err.message}`);
            });
        } else {
          addAssistantMessage('Error: Missing session ID. Usage: `/chat delete <session_id>`');
        }
        break;

      case 'chat new':
        addUserMessage('/chat new');
        sessionAPI.current.createSession()
          .then(newSessionId => {
            clearMessages();
            clearTools();
            resetProgress();
            switchConversation(newSessionId);
            addAssistantMessage(`✓ Created and switched to new session: ${newSessionId.slice(0, 8)}`);
          })
          .catch((err: any) => {
            addAssistantMessage(`Error creating session: ${err.message}`);
          });
        break;

      // Workflow prompt commands - send structured prompts to backend
      case 'init':
        if (isConnected) {
          const initPrompt = `🚀 **Project Initialization**\n\nPlease help me initialize this project:\n\n1. Analyze the current project structure and codebase\n2. Identify the main technologies, frameworks, and patterns used\n3. Suggest improvements to architecture, organization, or setup\n4. Recommend next steps for development\n5. Identify any potential issues or missing components\n\nWorkspace: ${process.cwd()}`;
          addUserMessage('/init');
          sendMessage(initPrompt);
          clearTools();
        }
        break;

      case 'review':
        if (isConnected) {
          const reviewPrompt = `🔍 **Code Review Request**\n\nPlease review recent changes in this project:\n\n1. Analyze code quality, patterns, and best practices\n2. Check for potential bugs, security issues, or performance problems\n3. Suggest improvements to readability and maintainability\n4. Verify test coverage and documentation\n5. Provide specific, actionable feedback\n\nWorkspace: ${process.cwd()}\n\n*Tip: Use \`git diff\` or provide specific files to review.*`;
          addUserMessage('/review');
          sendMessage(reviewPrompt);
          clearTools();
        }
        break;

      case 'plan':
        if (isConnected) {
          const feature = args.feature || 'the requested feature';
          const planPrompt = `📋 **Implementation Plan**\n\nCreate a detailed implementation plan for: **${feature}**\n\n1. Break down the feature into concrete tasks\n2. Identify dependencies and prerequisites\n3. Suggest file structure and code organization\n4. List potential challenges and solutions\n5. Estimate complexity and provide implementation order\n6. Include testing strategy\n\nWorkspace: ${process.cwd()}`;
          addUserMessage(`/plan ${feature}`);
          sendMessage(planPrompt);
          clearTools();
        }
        break;

      // Project management commands
      case 'project create':
        addUserMessage(`/project create ${args.name}`);
        if (!args.name) {
          addAssistantMessage('❌ Project name is required. Usage: `/project create <name> [description]`');
          break;
        }
        projectAPI.current.createProject(args.name, args.description)
          .then(project => {
            addAssistantMessage(`✅ Created project: **${project.name}**\n\n${project.description ? `_${project.description}_\n\n` : ''}Project ID: \`${project.id}\``);
          })
          .catch((err: any) => {
            addAssistantMessage(`❌ Failed to create project: ${err.message}`);
          });
        break;

      case 'project list':
        addUserMessage('/project list');
        projectAPI.current.listProjects()
          .then(projectList => {
            setProjects(projectList);
            setShowingProjectList(true);
          })
          .catch((err: any) => {
            addAssistantMessage(`❌ ${err.message}`);
          });
        break;

      case 'task create':
        addUserMessage(`/task create ${args.name}`);
        if (!args.name) {
          addAssistantMessage('❌ Task name and project required. Usage: `/task create <name> --project <project_id> [description]`');
          break;
        }
        if (!args.project) {
          // If no project specified, try to get the first project
          projectAPI.current.listProjects()
            .then(projects => {
              if (projects.length === 0) {
                addAssistantMessage('❌ No projects found. Create a project first with `/project create <name>`');
              } else {
                const firstProject = projects[0];
                return projectAPI.current.createTask(args.name, firstProject.id, args.description)
                  .then(task => {
                    addAssistantMessage(`✅ Created task: **${task.title}**\n\nProject: ${firstProject.name}\n${task.description ? `Description: _${task.description}_\n\n` : ''}Task ID: \`${task.id}\`\nStatus: ${task.status}`);
                  });
              }
            })
            .catch((err: any) => {
              addAssistantMessage(`❌ Failed to create task: ${err.message}`);
            });
        } else {
          projectAPI.current.createTask(args.name, args.project, args.description)
            .then(task => {
              addAssistantMessage(`✅ Created task: **${task.title}**\n\n${task.description ? `_${task.description}_\n\n` : ''}Task ID: \`${task.id}\`\nStatus: ${task.status}`);
            })
            .catch((err: any) => {
              addAssistantMessage(`❌ Failed to create task: ${err.message}`);
            });
        }
        break;

      case 'task list':
        addUserMessage('/task list');
        projectAPI.current.listTasks()
          .then(taskList => {
            setTasks(taskList);
            setShowingTaskList(true);
          })
          .catch((err: any) => {
            addAssistantMessage(`❌ ${err.message}`);
          });
        break;

      // RunMode autonomous execution commands
      case 'run continuous':
      case 'run 247':
        addUserMessage(commandName === 'run 247' ? '/run 247' : '/run continuous');
        {
          const taskName = args.task || undefined;
          const description = args.description || undefined;

          addAssistantMessage(`🚀 Starting continuous autonomous execution...\n\n${taskName ? `Task: ${taskName}` : 'Running next available task'}`);

          // Connect to WebSocket stream and execute task
          if (!runStreamWS.current) {
            setRunModeStatus({ status: 'running', current_task: taskName });
            setShowingRunMode(true);

            runStreamWS.current = runAPI.current.connectStreamAndExecute(
              taskName || 'Autonomous Task',
              description,
              true, // continuous mode
              propConversationId,
                  (message: TaskStreamMessage) => {
                    console.error('[RunMode] Received event:', message.type, message);

                    // Handle stream messages
                    switch (message.type) {
                      case 'task_started':
                        setRunModeMessage(`Started: ${message.task_name}`);
                        setRunModeProgress(0);
                        addAssistantMessage(`▶ Task started: **${message.task_name}**`);
                        break;
                      case 'task_progress':
                        setRunModeMessage(message.content || '');
                        setRunModeProgress(message.progress || 0);
                        break;
                      case 'task_completed_eventbus':
                      case 'task_completed':
                        setRunModeMessage(`Completed`);
                        setRunModeProgress(100);
                        addAssistantMessage(`✅ Task completed!`);
                        break;
                      case 'task_failed':
                        setRunModeMessage(`Failed: ${message.error}`);
                        addAssistantMessage(`❌ Task failed: ${message.error}`);
                        break;
                      case 'message':
                        // Display message content from assistant, tool, or system
                        const content = (message as any).data?.content || (message as any).content;
                        const role = (message as any).data?.role || (message as any).role || 'system';
                        const category = (message as any).data?.category || (message as any).category || 'SYSTEM';

                        console.error(`[RunMode] Processing message: role=${role}, category=${category}, contentLength=${content?.length}`);

                        if (content) {
                          // Main assistant responses (DIALOG category)
                          if (role === 'assistant' && category === 'DIALOG') {
                            console.error('[RunMode] Displaying assistant DIALOG message');
                            addAssistantMessage(content);
                          }
                          // Tool outputs and system messages - show dimmed
                          else if (category === 'SYSTEM_OUTPUT' || category === 'SYSTEM') {
                            console.error('[RunMode] Displaying system/tool message (dimmed)');
                            addAssistantMessage(`_${content}_`);
                          } else {
                            console.error(`[RunMode] Unhandled message type: role=${role}, category=${category}`);
                          }
                        }
                        break;
                      case 'error':
                        addAssistantMessage(`❌ Error: ${message.error}`);
                        break;
                      case 'shutdown_completed':
                      case 'run_mode_ended':
                        setShowingRunMode(false);
                        setRunModeStatus({ status: 'idle' });
                        break;
                    }
                  },
                  (error) => {
                    addAssistantMessage(`❌ Stream error: ${error.message}`);
                  },
                  () => {
                    // Stream closed
                    setShowingRunMode(false);
                    runStreamWS.current = null;
                }
              );
          } else {
            addAssistantMessage('⚠️ RunMode is already running. Use `/run stop` first.');
          }
        }
        break;

      case 'run task':
        addUserMessage(`/run task ${args.name}`);
        {
          const taskName = args.name;
          const description = args.description || undefined;

          if (!taskName) {
            addAssistantMessage('❌ Task name is required. Usage: `/run task <name> [description]`');
            break;
          }

          addAssistantMessage(`🚀 Starting task: **${taskName}**`);
          setShowingRunMode(true);
          setRunModeStatus({ status: 'running', current_task: taskName });

          // Connect to stream and execute task
          if (!runStreamWS.current) {
            runStreamWS.current = runAPI.current.connectStreamAndExecute(
              taskName,
              description,
              false, // not continuous
              propConversationId,
              (message: TaskStreamMessage) => {
                switch (message.type) {
                  case 'task_started':
                    setRunModeMessage(`Started: ${message.task_name}`);
                    break;
                  case 'task_progress':
                    setRunModeMessage(message.content || '');
                    setRunModeProgress(message.progress || 0);
                    break;
                  case 'task_completed':
                    setRunModeMessage(`Completed`);
                    setRunModeProgress(100);
                    addAssistantMessage(`✅ Task completed!\n\n${message.result ? JSON.stringify(message.result, null, 2) : ''}`);
                    setShowingRunMode(false);
                    setRunModeStatus({ status: 'idle' });
                    break;
                  case 'task_failed':
                    addAssistantMessage(`❌ Task failed: ${message.error}`);
                    setShowingRunMode(false);
                    setRunModeStatus({ status: 'idle' });
                    break;
                  case 'message':
                    if (message.content) {
                      addAssistantMessage(message.content);
                    }
                    break;
                }
              },
              (error) => {
                addAssistantMessage(`❌ Stream error: ${error.message}`);
                setShowingRunMode(false);
                setRunModeStatus({ status: 'idle' });
              },
              () => {
                // Stream closed
                setShowingRunMode(false);
                setRunModeStatus({ status: 'idle' });
                runStreamWS.current = null;
              }
            );
          } else {
            addAssistantMessage('⚠️ A task is already running. Use `/run stop` first.');
          }
        }
        break;

      case 'run stop':
        addUserMessage('/run stop');
        addAssistantMessage('⏸ Stopping autonomous execution...');
        runAPI.current.stop()
          .then(() => {
            setRunModeStatus({ status: 'stopped' });
            setShowingRunMode(false);
            addAssistantMessage('✅ Execution stopped');

            // Close WebSocket stream
            if (runStreamWS.current) {
              runStreamWS.current.close();
              runStreamWS.current = null;
            }
          })
          .catch((err: any) => {
            addAssistantMessage(`❌ Failed to stop: ${err.message}`);
          });
        break;

      default:
        // Unknown command
        addAssistantMessage(`Unknown command: /${commandName}. Type \`/help\` for available commands.`);
    }
  }, [addAssistantMessage, addUserMessage, clearMessages, clearTools, resetProgress, exit, isExiting, isConnected, sendMessage]);

  const handleSubmit = useCallback((value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;

    // Reset suggestions
    setSuggestions([]);
    setCurrentInput('');

    // Auto-detect image file paths (when dragged into terminal or typed)
    const imageExtensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg'];

    // Check for multimodal input: text + image path on separate lines
    const lines = trimmed.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    let imagePath: string | null = null;
    let messageText: string | null = null;

    // Look for image paths in any line
    for (const line of lines) {
      const cleanedLine = line.replace(/^['"]|['"]$/g, '');
      const lowerLine = cleanedLine.toLowerCase();
      const isImage = imageExtensions.some(ext => lowerLine.endsWith(ext)) &&
                     (cleanedLine.startsWith('/') || cleanedLine.startsWith('~') || cleanedLine.startsWith('.'));

      if (isImage) {
        // Expand ~ to home directory
        let expandedPath = cleanedLine.startsWith('~')
          ? cleanedLine.replace('~', homedir())
          : cleanedLine;

        // Check if file exists
        if (existsSync(expandedPath)) {
          imagePath = expandedPath;
        }
      } else {
        // This line is text
        messageText = messageText ? `${messageText}\n${line}` : line;
      }
    }

    // Handle multimodal message (text + image)
    if (imagePath && messageText) {
      console.error('[ChatSession] Multimodal message detected:', { imagePath, messageText });
      addUserMessage(`${messageText}\n\n📎 ${imagePath}`);
      clearTools();
      sendMessage(messageText, { image_path: imagePath });
      setInputKey((prev) => prev + 1);
      return;
    }

    // Handle image-only message
    if (imagePath && !messageText) {
      console.error('[ChatSession] Auto-detected image file:', imagePath);
      addUserMessage(`📎 ${imagePath}`);
      addAssistantMessage(`📎 Attached image: \`${imagePath}\`\n\n_What would you like to know about this image?_`);
      clearTools();
      sendMessage('What do you see in this image?', { image_path: imagePath });
      setInputKey((prev) => prev + 1);
      return;
    }

    // Check if this is a command (starts with /)
    if (trimmed.startsWith('/')) {
      const parsed = parseInput(trimmed);
      console.error(`[ChatSession] Parsed command: ${trimmed} -> ${parsed ? parsed.command.name : 'null'}`);
      if (parsed) {
        // Handle command
        console.error(`[ChatSession] Handling command: ${parsed.command.name} with args:`, parsed.args);
        handleCommand(parsed.command.name, parsed.args);
        setInputKey((prev) => prev + 1);
        return;
      } else {
        console.error(`[ChatSession] Command not recognized, falling through to send as message`);
      }
    }

    // Only allow sending regular messages if connected and not already streaming
    if (isConnected && !isStreaming) {
      addUserMessage(trimmed);
      clearTools(); // Clear previous tool executions
      sendMessage(trimmed);
      // Force input to remount and clear by changing its key
      setInputKey((prev) => prev + 1);
    }
  }, [isConnected, isStreaming, addUserMessage, sendMessage, clearTools, parseInput, handleCommand]);

  // Handle session selection from modal
  const handleSessionSelect = useCallback((session: Session) => {
    setShowSessionPicker(false);
    clearMessages();
    clearTools();
    resetProgress();
    switchConversation(session.id);
  }, [switchConversation, clearMessages, clearTools, resetProgress]);

  // Handle session deletion from modal
  const handleSessionDelete = useCallback((sessionId: string) => {
    sessionAPI.current
      .deleteSession(sessionId)
      .then(() => {
        // Refresh session list
        return sessionAPI.current.listSessions();
      })
      .then((sessionList) => {
        setSessions(sessionList);
      })
      .catch((err) => {
        // console.error('Failed to delete session:', err);
      });
  }, []);

  return (
    <Box flexDirection="column" gap={1}>
      {/* Main content */}
      {!showSessionPicker && (
        <>
          {/* Connection status */}
          <ConnectionStatus isConnected={isConnected} error={error} />

      {/* Message history */}
      <MessageList messages={messages} streamingText={streamingText} />

      {/* Progress indicator for multi-step execution */}
      {progress.isActive && progress.maxIterations > 1 && (
        <Box marginY={0}>
          <ProgressIndicator
            iteration={progress.iteration}
            maxIterations={progress.maxIterations}
            message={progress.message}
            isActive={progress.isActive}
          />
        </Box>
      )}

      {/* Tool execution display (inline during streaming) */}
      {(activeTool || completedTools.length > 0) && (
        <Box flexDirection="column" marginY={0}>
          <ToolExecutionList tools={[...completedTools, ...(activeTool ? [activeTool] : [])]} />
        </Box>
      )}

      {/* Input prompt - Multi-line with autocomplete */}
      <Box minHeight={8}>
        <MultiLineInput
          key={inputKey}
          placeholder={isStreaming ? "Waiting for response..." : "Type your message..."}
          isDisabled={!isConnected || isStreaming}
          onSubmit={handleSubmit}
          onTextChange={handleTextChange}
          suggestions={suggestions}
        />
      </Box>

          {/* Help text */}
          <Box marginTop={1}>
            <Text dimColor>
              {isStreaming
                ? 'Waiting for response... • Ctrl+C to exit'
                : 'Enter: Send • Ctrl+P: Dashboard • Ctrl+O: Sessions • Ctrl+C: Exit'}
            </Text>
          </Box>
        </>
      )}

      {/* RunMode Status Display */}
      {showingRunMode && !showSessionPicker && (
        <Box flexDirection="column" width="100%" paddingX={2}>
          <RunModeStatus
            status={runModeStatus}
            currentMessage={runModeMessage}
            progress={runModeProgress}
          />
        </Box>
      )}

      {/* Project List Modal */}
      {showingProjectList && !showSessionPicker && (
        <Box flexDirection="column" width="100%" paddingX={2}>
          <ProjectList projects={projects} />
          <Box marginTop={1}>
            <Text dimColor>Press any key to continue...</Text>
          </Box>
        </Box>
      )}

      {/* Task List Modal */}
      {showingTaskList && !showSessionPicker && !showingProjectList && (
        <Box flexDirection="column" width="100%" paddingX={2}>
          <TaskList tasks={tasks} />
          <Box marginTop={1}>
            <Text dimColor>Press any key to continue...</Text>
          </Box>
        </Box>
      )}

      {/* Session Picker Modal (full screen overlay) */}
      {showSessionPicker && (
        <Box flexDirection="column" width="100%" height="100%" justifyContent="center" alignItems="center">
          <SessionPickerModal
            sessions={sessions}
            currentSessionId={propConversationId}
            onSelect={handleSessionSelect}
            onDelete={handleSessionDelete}
            onClose={() => setShowSessionPicker(false)}
            isLoading={isLoadingSessions}
          />
        </Box>
      )}
    </Box>
  );
}
