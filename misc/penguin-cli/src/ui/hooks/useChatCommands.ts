/**
 * Chat Commands Hook - Extracted command handling from ChatSession
 *
 * Handles all slash commands like /help, /models, /clear, /chat, /run, etc.
 * This extraction reduces ChatSession complexity significantly.
 */

import { useCallback, useRef } from 'react';
import { useApp } from 'ink';
import { SessionAPI } from '../../core/api/SessionAPI.js';
import { ProjectAPI } from '../../core/api/ProjectAPI.js';
import { RunAPI, type TaskStreamMessage } from '../../core/api/RunAPI.js';
import { ModelAPI } from '../../core/api/ModelAPI.js';
import { getConfigPath, validateConfig, getConfigDiagnostics } from '../../config/loader.js';
import { exec } from 'child_process';
import { existsSync } from 'fs';
import { logger } from '../../utils/logger.js';
import type { Session } from '../../core/types.js';
import type { Project, Task } from '../../core/api/ProjectAPI.js';

export interface CommandHandlerDeps {
  // Message functions
  addUserMessage: (text: string) => void;
  addAssistantMessage: (text: string) => void;
  clearMessages: () => void;

  // Tool/progress functions
  clearTools: () => void;
  clearToolEvents: () => void;
  resetProgress: () => void;

  // Connection state
  isConnected: boolean;
  sendMessage: (text: string, options?: { image_path?: string }) => void;

  // Session management
  conversationId?: string;
  switchConversation: (id: string) => void;

  // Modal state setters
  setShowModelSelector: (show: boolean) => void;
  setShowSettings: (show: boolean) => void;
  setShowSessionPicker: (show: boolean) => void;
  setIsLoadingSessions: (loading: boolean) => void;
  setSessions: (sessions: Session[]) => void;
  setProjects: (projects: Project[]) => void;
  setTasks: (tasks: Task[]) => void;
  setShowingProjectList: (show: boolean) => void;
  setShowingTaskList: (show: boolean) => void;
  setShowingSessionList: (show: boolean) => void;

  // RunMode state
  setRunModeStatus: (status: any) => void;
  setShowingRunMode: (show: boolean) => void;
  setRunModeMessage: (message: string) => void;
  setRunModeProgress: (progress: number) => void;
}

export interface UseChatCommandsReturn {
  handleCommand: (commandName: string, args: Record<string, any>) => void;
  sessionAPI: SessionAPI;
  projectAPI: ProjectAPI;
  runAPI: RunAPI;
  modelAPI: ModelAPI;
}

export function useChatCommands(deps: CommandHandlerDeps): UseChatCommandsReturn {
  const { exit } = useApp();
  const isExitingRef = useRef(false);

  // API instances
  const sessionAPI = useRef(new SessionAPI('http://localhost:8000')).current;
  const projectAPI = useRef(new ProjectAPI('http://localhost:8000')).current;
  const runAPI = useRef(new RunAPI('http://localhost:8000')).current;
  const modelAPI = useRef(new ModelAPI('http://localhost:8000')).current;
  const runStreamWS = useRef<WebSocket | null>(null);

  const handleCommand = useCallback((commandName: string, args: Record<string, any>) => {
    const {
      addUserMessage,
      addAssistantMessage,
      clearMessages,
      clearTools,
      clearToolEvents,
      resetProgress,
      isConnected,
      sendMessage,
      conversationId,
      switchConversation,
      setShowModelSelector,
      setShowSettings,
      setShowSessionPicker,
      setIsLoadingSessions,
      setSessions,
      setProjects,
      setTasks,
      setShowingProjectList,
      setShowingTaskList,
      setShowingSessionList,
      setRunModeStatus,
      setShowingRunMode,
      setRunModeMessage,
      setRunModeProgress,
    } = deps;

    switch (commandName) {
      case 'help':
      case 'h':
      case '?':
        addAssistantMessage(
          `# Penguin CLI Commands\n\nType \`/help\` to see this message again.\n\n## Available Commands:\n\n### 💬 Chat\n- \`/help\` (aliases: /h, /?) - Show this help\n- \`/clear\` (aliases: /cls, /reset) - Clear chat history\n- \`/chat list\` - List all conversations\n- \`/chat load <id>\` - Load a conversation\n- \`/chat delete <id>\` - Delete a conversation\n- \`/chat new\` - Start a new conversation\n\n### 🚀 Workflow\n- \`/init\` - Initialize project with AI assistance\n- \`/review\` - Review code changes and suggest improvements\n- \`/plan <feature>\` - Create implementation plan for a feature\n- \`/image <path> [message]\` - Attach image for vision analysis\n\n### ⚙️ Configuration\n- \`/models\` - Select AI model\n- \`/model info\` - Show current model information\n- \`/setup\` - Run setup wizard (must exit chat first)\n- \`/config edit\` - Open config file in $EDITOR\n- \`/config check\` - Validate current configuration\n- \`/config debug\` - Show diagnostic information\n\n### 🔧 System\n- \`/quit\` (aliases: /exit, /q) - Exit the CLI\n\n### ⌨️ Hotkeys\n- \`Ctrl+S\` - Open Settings\n- \`Ctrl+P\` - Switch tabs\n- \`Ctrl+C\` - Exit\n\nMore commands available! See commands.yml for full list.`
        );
        break;

      case 'models':
        addUserMessage('/models');
        setShowModelSelector(true);
        break;

      case 'model':
        if (args.subcommand === 'info') {
          addUserMessage('/model info');
          modelAPI.getCurrentModel().then(currentModel => {
            const { loadConfig } = require('../../config/loader.js');
            loadConfig().then((config: any) => {
              let message = `# 🤖 Current Model Information\n\n`;
              message += `**Model**: ${currentModel.model}\n`;
              message += `**Provider**: ${currentModel.provider}\n`;

              if (config?.model?.context_window) {
                message += `**Context Window**: ${config.model.context_window.toLocaleString()} tokens\n`;
              }
              if (config?.model?.max_tokens) {
                message += `**Max Output**: ${config.model.max_tokens.toLocaleString()} tokens\n`;
              }

              const supportsReasoning =
                currentModel.model.toLowerCase().includes('gpt-5') ||
                currentModel.model.toLowerCase().includes('gpt5') ||
                currentModel.model.toLowerCase().includes('/o1') ||
                currentModel.model.toLowerCase().includes('/o3') ||
                (currentModel.model.toLowerCase().includes('gemini') &&
                 (currentModel.model.toLowerCase().includes('2.5') ||
                  currentModel.model.toLowerCase().includes('2-5')));

              if (supportsReasoning) {
                message += `\n## 🧠 Reasoning Support\n`;
                message += `This model supports advanced reasoning capabilities.\n`;
                if (config?.model?.reasoning_effort) {
                  message += `**Current Effort Level**: ${config.model.reasoning_effort}\n`;
                } else {
                  message += `**Current Effort Level**: medium (default)\n`;
                }
                message += `\n*Adjust reasoning effort in Settings (Ctrl+S)*`;
              }

              message += `\n\nUse \`/models\` to switch models or \`Ctrl+S\` for Settings.`;
              addAssistantMessage(message);
            }).catch((err: any) => {
              addAssistantMessage(`Error loading config: ${err.message}`);
            });
          }).catch(err => {
            addAssistantMessage(`Error getting model info: ${err.message}`);
          });
        } else {
          addUserMessage('/model');
          setShowModelSelector(true);
        }
        break;

      case 'setup':
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

          let command: string;
          if (process.platform === 'darwin') {
            command = `open -t "${configPath}"`;
          } else if (process.platform === 'win32') {
            command = `start "" "${configPath}"`;
          } else {
            command = `xdg-open "${configPath}"`;
          }

          exec(command, (error, _stdout, stderr) => {
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
        break;

      case 'config debug':
        addUserMessage('/config debug');
        getConfigDiagnostics().then(diagnostics => {
          addAssistantMessage(diagnostics);
        }).catch(error => {
          addAssistantMessage(`❌ Failed to get diagnostics: ${error}`);
        });
        break;

      case 'image':
      case 'img':
        {
          let imagePath = args.path || '';
          imagePath = imagePath.replace(/^['"]|['"]$/g, '');
          const message = args.message || 'What do you see in this image?';

          addUserMessage(`/image ${imagePath} ${message}`);

          if (!imagePath) {
            addAssistantMessage('❌ Please provide an image path: `/image <path> [optional message]`');
            break;
          }

          if (imagePath.startsWith('~')) {
            imagePath = imagePath.replace('~', require('os').homedir());
          }

          if (!existsSync(imagePath)) {
            addAssistantMessage(`❌ Image file not found: \`${imagePath}\`\n\nMake sure the path is correct and the file exists.`);
            break;
          }

          addAssistantMessage(`📎 Sending image: \`${imagePath}\`\n\n_Analyzing image with vision model..._`);
          clearTools();
          sendMessage(message, { image_path: imagePath });
        }
        break;

      case 'clear':
      case 'cls':
      case 'reset':
        clearMessages();
        clearTools();
        clearToolEvents();
        resetProgress();
        break;

      case 'quit':
      case 'exit':
      case 'q':
        if (!isExitingRef.current) {
          isExitingRef.current = true;
          exit();
        }
        break;

      case 'chat list':
        addUserMessage('/chat list');
        sessionAPI.listSessions()
          .then(sessionList => {
            setSessions(sessionList);
            setShowingSessionList(true);
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
          sessionAPI.deleteSession(args.session_id)
            .then(success => {
              if (success) {
                addAssistantMessage(`✓ Deleted session: ${args.session_id.slice(0, 8)}`);
                sessionAPI.listSessions().then(setSessions);
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
        sessionAPI.createSession()
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

      case 'project create':
        addUserMessage(`/project create ${args.name}`);
        if (!args.name) {
          addAssistantMessage('❌ Project name is required. Usage: `/project create <name> [description]`');
          break;
        }
        projectAPI.createProject(args.name, args.description)
          .then(project => {
            addAssistantMessage(`✅ Created project: **${project.name}**\n\n${project.description ? `_${project.description}_\n\n` : ''}Project ID: \`${project.id}\``);
          })
          .catch((err: any) => {
            addAssistantMessage(`❌ Failed to create project: ${err.message}`);
          });
        break;

      case 'project list':
        addUserMessage('/project list');
        projectAPI.listProjects()
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
          projectAPI.listProjects()
            .then(projects => {
              if (projects.length === 0) {
                addAssistantMessage('❌ No projects found. Create a project first with `/project create <name>`');
              } else {
                const firstProject = projects[0];
                return projectAPI.createTask(args.name, firstProject.id, args.description)
                  .then(task => {
                    addAssistantMessage(`✅ Created task: **${task.title}**\n\nProject: ${firstProject.name}\n${task.description ? `Description: _${task.description}_\n\n` : ''}Task ID: \`${task.id}\`\nStatus: ${task.status}`);
                  });
              }
            })
            .catch((err: any) => {
              addAssistantMessage(`❌ Failed to create task: ${err.message}`);
            });
        } else {
          projectAPI.createTask(args.name, args.project, args.description)
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
        projectAPI.listTasks()
          .then(taskList => {
            setTasks(taskList);
            setShowingTaskList(true);
          })
          .catch((err: any) => {
            addAssistantMessage(`❌ ${err.message}`);
          });
        break;

      case 'run continuous':
      case 'run 247':
        addUserMessage(commandName === 'run 247' ? '/run 247' : '/run continuous');
        {
          const taskName = args.task || undefined;
          const description = args.description || undefined;

          addAssistantMessage(`🚀 Starting continuous autonomous execution...\n\n${taskName ? `Task: ${taskName}` : 'Running next available task'}`);

          if (!runStreamWS.current) {
            setRunModeStatus({ status: 'running', current_task: taskName });
            setShowingRunMode(true);

            runStreamWS.current = runAPI.connectStreamAndExecute(
              taskName || 'Autonomous Task',
              description,
              true,
              conversationId,
              (message: TaskStreamMessage) => {
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
                    const content = (message as any).data?.content || (message as any).content;
                    const role = (message as any).data?.role || (message as any).role || 'system';
                    const category = (message as any).data?.category || (message as any).category || 'SYSTEM';

                    if (content) {
                      if (role === 'assistant' && category === 'DIALOG') {
                        addAssistantMessage(content);
                      } else if (category === 'SYSTEM_OUTPUT' || category === 'SYSTEM') {
                        addAssistantMessage(`_${content}_`);
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

          if (!runStreamWS.current) {
            runStreamWS.current = runAPI.connectStreamAndExecute(
              taskName,
              description,
              false,
              conversationId,
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
        runAPI.stop()
          .then(() => {
            setRunModeStatus({ status: 'stopped' });
            setShowingRunMode(false);
            addAssistantMessage('✅ Execution stopped');

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
        addAssistantMessage(`Unknown command: /${commandName}. Type \`/help\` for available commands.`);
    }
  }, [deps, exit]);

  return {
    handleCommand,
    sessionAPI,
    projectAPI,
    runAPI,
    modelAPI,
  };
}
