#!/usr/bin/env node
/**
 * Prototype CLI to test Penguin Ink UI without backend
 *
 * Run: npm run dev:mock
 *
 * Features:
 * - 1: Simple assistant message
 * - 2: Message with reasoning
 * - 3: Message with code execution
 * - 4: Message with tool call/result
 * - 5: Streaming message simulation
 * - 6: Error message
 * - 7: Multi-step progress
 * - 8: Complex markdown (lists, code, tables)
 * - 9: Full conversation flow
 *
 * Type any message and press Enter to echo it back
 */

import React, { useState, useEffect, useCallback } from 'react';
import { render, Box, Text, useInput, useApp } from 'ink';
import { MessageList } from './ui/components/MessageList.js';
import { ConnectionStatus } from './ui/components/ConnectionStatus.js';
import { ToolExecutionList } from './ui/components/ToolExecution.js';
import { ProgressIndicator } from './ui/components/ProgressIndicator.js';
import { MultiLineInput } from './ui/components/MultiLineInput.js';
import type { Message, ToolCall, ActionResult } from './core/types.js';

interface MockCLIProps {}

function MockCLI({}: MockCLIProps) {
  const { exit } = useApp();
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingText, setStreamingText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [tools, setTools] = useState<ToolCall[]>([]);
  const [progress, setProgress] = useState({ iteration: 0, maxIterations: 0, isActive: false });
  const [inputKey, setInputKey] = useState(0);

  // Welcome message
  useEffect(() => {
    setMessages([{
      id: 'welcome',
      role: 'system',
      content: '🐧 Penguin CLI Prototype - Press 1-9 for demos, or type a message',
      timestamp: Date.now(),
    }]);
  }, []);

  // Handle Ctrl+C to exit
  useInput((input, key) => {
    if (key.ctrl && input === 'c') {
      exit();
    }

    // Demo shortcuts
    if (!isStreaming) {
      if (input === '1') addSimpleMessage();
      else if (input === '2') addReasoningMessage();
      else if (input === '3') addCodeExecutionMessage();
      else if (input === '4') addToolCallMessage();
      else if (input === '5') simulateStreaming();
      else if (input === '6') addErrorMessage();
      else if (input === '7') simulateProgress();
      else if (input === '8') addComplexMarkdown();
      else if (input === '9') simulateFullConversation();
    }
  });

  const addMessage = (content: string, role: 'user' | 'assistant' | 'system', reasoning?: string) => {
    setMessages(prev => [...prev, {
      id: `msg-${Date.now()}-${Math.random()}`,
      role,
      content,
      timestamp: Date.now(),
      reasoning,
    }]);
  };

  const handleUserInput = (text: string) => {
    if (!text.trim()) return;

    addMessage(text, 'user');
    setInputKey(prev => prev + 1);

    // Echo back with a slight delay
    setTimeout(() => {
      addMessage(`Echo: ${text}`, 'assistant');
    }, 500);
  };

  // Demo 1: Simple assistant message
  const addSimpleMessage = () => {
    addMessage(
      'This is a simple assistant message. It demonstrates basic text rendering in the CLI.',
      'assistant'
    );
  };

  // Demo 2: Message with reasoning
  const addReasoningMessage = () => {
    const reasoning = 'The user is asking about capabilities. I should provide a clear, organized overview of what I can do. I will structure this with headers and bullet points for readability.';
    const content = `## Penguin Capabilities

**Core Features:**
- Multi-language code development
- Strategic planning and architecture
- Real-time code execution
- Advanced search and analysis

I can help you build, debug, and optimize code across multiple languages and frameworks.`;

    addMessage(content, 'assistant', reasoning);
  };

  // Demo 3: Code execution with tool result
  const addCodeExecutionMessage = () => {
    const content = `I'll generate a random number for you:

\`\`\`python
# <execute>
import random

def generate_random():
    n = random.randint(1, 1_000_000)
    print(f"Generated: {n}")
    return n

result = generate_random()
# </execute>
\`\`\`

The function will generate a random number between 1 and 1,000,000.`;

    addMessage(content, 'assistant');

    // Simulate tool execution
    setTimeout(() => {
      const randomNum = Math.floor(Math.random() * 1000000) + 1;
      setTools([{
        id: 'exec-1',
        action: 'execute',
        status: 'completed',
        result: `Generated: ${randomNum}\n${randomNum}`,
        startTime: Date.now(),
        endTime: Date.now() + 250,
      }]);

      setTimeout(() => {
        addMessage(`Perfect! Generated random number: **${randomNum}**`, 'assistant');
        setTools([]);
      }, 1000);
    }, 500);
  };

  // Demo 4: Tool call with results
  const addToolCallMessage = () => {
    addMessage('Let me search the codebase for authentication logic...', 'assistant');

    setTimeout(() => {
      setTools([{
        id: 'search-1',
        action: 'workspace_search',
        status: 'running',
        startTime: Date.now(),
      }]);

      setTimeout(() => {
        setTools([{
          id: 'search-1',
          action: 'workspace_search',
          status: 'completed',
          result: `Found 5 files:
- src/auth/login.ts:42 - handleLogin()
- src/auth/token.ts:18 - refreshToken()
- src/auth/middleware.ts:31 - verifyAuth()
- src/services/auth.service.ts:89 - authenticate()
- tests/auth.test.ts:12 - test suite`,
          startTime: Date.now() - 1500,
          endTime: Date.now(),
        }]);

        setTimeout(() => {
          addMessage('Found authentication logic in **5 files**. The main token refresh logic is in `src/auth/token.ts`.', 'assistant');
          setTools([]);
        }, 1000);
      }, 1500);
    }, 500);
  };

  // Demo 5: Streaming simulation
  const simulateStreaming = () => {
    const fullText = `## Streaming Demo

This message is being **streamed** token by token to simulate real-time LLM output.

### Features:
- Progressive rendering
- Smooth user experience
- Real-time feedback

\`\`\`typescript
function streamTokens(text: string) {
  const tokens = text.split(' ');
  for (const token of tokens) {
    yield token + ' ';
  }
}
\`\`\`

Streaming provides a better user experience during long responses.`;

    const tokens = fullText.split(' ');
    let accumulated = '';
    let index = 0;

    setIsStreaming(true);
    setStreamingText('');

    const interval = setInterval(() => {
      if (index >= tokens.length) {
        clearInterval(interval);
        setIsStreaming(false);
        addMessage(fullText, 'assistant');
        setStreamingText('');
        return;
      }

      accumulated += tokens[index] + ' ';
      setStreamingText(accumulated);
      index++;
    }, 50);
  };

  // Demo 6: Error message
  const addErrorMessage = () => {
    addMessage(
      '❌ **Error**: Failed to execute command\n\n`FileNotFoundError: No such file or directory: /tmp/test.txt`\n\nPlease check the file path and try again.',
      'system'
    );
  };

  // Demo 7: Multi-step progress
  const simulateProgress = () => {
    addMessage('Starting multi-step task...', 'assistant');

    let step = 1;
    const maxSteps = 5;

    setProgress({ iteration: 1, maxIterations: maxSteps, isActive: true });

    const interval = setInterval(() => {
      if (step >= maxSteps) {
        clearInterval(interval);
        setProgress({ iteration: 0, maxIterations: 0, isActive: false });
        addMessage('✅ All steps completed successfully!', 'assistant');
        return;
      }

      step++;
      setProgress({ iteration: step, maxIterations: maxSteps, isActive: true });
    }, 1000);
  };

  // Demo 8: Complex markdown with tables
  const addComplexMarkdown = () => {
    const content = `## Complex Markdown Demo

### Markdown Tables

| Feature | Status | Priority | Notes |
|---------|:------:|----------|-------|
| Tables | ✅ Done | High | Full GFM support |
| Mermaid | 🔧 WIP | Medium | ASCII + Browser |
| Math | 📋 TODO | Low | LaTeX rendering |
| Code | ✅ Done | High | Syntax support |

### Headers and Formatting

This demonstrates **bold text**, \`inline code\`, and various markdown features.

### Lists

**Unordered:**
- First item
- Second item with **bold**
- Third item with \`code\`

**Nested:**
- Parent item
  - Child item 1
  - Child item 2

### Code Blocks

\`\`\`python
def fibonacci(n):
    """Calculate nth Fibonacci number."""
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)

# Generate first 10 numbers
for i in range(10):
    print(f"F({i}) = {fibonacci(i)}")
\`\`\`

\`\`\`typescript
interface User {
  id: string;
  name: string;
  email: string;
}

const getUser = async (id: string): Promise<User> => {
  const response = await fetch(\`/api/users/\${id}\`);
  return response.json();
};
\`\`\`

### Inline Elements

Here's some \`inline code\` and **bold text** mixed together.

### Paragraphs

This is a longer paragraph to demonstrate text wrapping and formatting. The CLI should handle this gracefully, maintaining readability even with longer content. Multiple sentences should flow naturally.

This is a second paragraph with some spacing between them.`;

    addMessage(content, 'assistant');
  };

  // Demo 9: Full conversation flow
  const simulateFullConversation = () => {
    const steps = [
      { delay: 0, action: () => addMessage('Help me implement a JWT refresh token system', 'user') },
      { delay: 1000, action: () => addMessage('I\'ll help you implement a JWT refresh token system. Let me analyze the requirements and create a solution.', 'assistant', 'The user wants JWT refresh tokens. I need to: 1) Explain the concept, 2) Show implementation, 3) Add security best practices.') },
      { delay: 2000, action: () => {
        const content = `## JWT Refresh Token Implementation

### Overview

A refresh token system allows long-lived authentication without exposing the main access token.

**Key components:**
- Short-lived access tokens (15 minutes)
- Long-lived refresh tokens (7 days)
- Secure token storage
- Token rotation on refresh

### Implementation

\`\`\`typescript
interface TokenPair {
  accessToken: string;
  refreshToken: string;
}

async function generateTokenPair(userId: string): Promise<TokenPair> {
  const accessToken = jwt.sign(
    { userId, type: 'access' },
    ACCESS_SECRET,
    { expiresIn: '15m' }
  );

  const refreshToken = jwt.sign(
    { userId, type: 'refresh' },
    REFRESH_SECRET,
    { expiresIn: '7d' }
  );

  return { accessToken, refreshToken };
}
\`\`\`

**Security best practices:**
- Store refresh tokens in httpOnly cookies
- Implement token rotation (issue new refresh token on use)
- Maintain a refresh token whitelist in Redis
- Log all token refresh attempts`;

        addMessage(content, 'assistant');
      }},
      { delay: 3500, action: () => addMessage('Can you show me the database schema for storing tokens?', 'user') },
      { delay: 4500, action: () => {
        const content = `### Database Schema

\`\`\`sql
CREATE TABLE refresh_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  token_hash VARCHAR(256) NOT NULL,
  device_info JSONB,
  created_at TIMESTAMP DEFAULT NOW(),
  expires_at TIMESTAMP NOT NULL,
  revoked_at TIMESTAMP,
  INDEX idx_user_tokens (user_id, expires_at),
  INDEX idx_token_hash (token_hash)
);
\`\`\`

**Important notes:**
- Never store raw tokens, only hashes
- Include device_info for security auditing
- Add indexes for fast lookups
- Implement automatic cleanup of expired tokens`;

        addMessage(content, 'assistant');
      }},
    ];

    steps.forEach(({ delay, action }) => {
      setTimeout(action, delay);
    });
  };

  return (
    <Box flexDirection="column" padding={1}>
      {/* Header */}
      <Box marginBottom={1}>
        <Text bold color="cyan">🐧 Penguin AI - Prototype CLI</Text>
      </Box>

      {/* Connection status (always connected in mock) */}
      <ConnectionStatus isConnected={true} error={null} />

      {/* Messages */}
      <Box flexDirection="column" flexGrow={1} marginY={1}>
        <MessageList messages={messages} streamingText={streamingText} />
      </Box>

      {/* Progress indicator */}
      {progress.isActive && (
        <Box marginY={1}>
          <ProgressIndicator
            iteration={progress.iteration}
            maxIterations={progress.maxIterations}
            isActive={progress.isActive}
          />
        </Box>
      )}

      {/* Tool execution */}
      {tools.length > 0 && (
        <Box marginY={1}>
          <ToolExecutionList tools={tools} />
        </Box>
      )}

      {/* Input - Multi-line */}
      <MultiLineInput
        key={inputKey}
        placeholder="Type a message or press 1-9 for demos..."
        isDisabled={isStreaming}
        onSubmit={handleUserInput}
      />

      {/* Help */}
      <Box marginTop={1}>
        <Text dimColor>
          Demos: 1=Simple 2=Reasoning 3=Code 4=Tool 5=Stream 6=Error 7=Progress 8=Markdown 9=Full • Ctrl+C to exit
        </Text>
      </Box>
    </Box>
  );
}

// Render the app
render(<MockCLI />);
