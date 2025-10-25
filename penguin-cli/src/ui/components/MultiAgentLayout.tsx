import React, { useState, useCallback } from 'react';
import { Box, Text, useInput } from 'ink';
import { AgentRoster } from './AgentRoster.js';
import { ChannelList } from './ChannelList.js';
import { MessageThread } from './MessageThread.js';
import { ChannelInputBar } from './ChannelInputBar.js';
import { useAgents } from '../hooks/useAgents.js';
import { useMessageBus } from '../hooks/useMessageBus.js';
import { useTab } from '../contexts/TabContext.js';
import { AgentProfile, ProtocolMessage } from '../../core/api/AgentAPI.js';

export interface MultiAgentLayoutProps {
  onExit?: () => void;
}

export function MultiAgentLayout({ onExit }: MultiAgentLayoutProps) {
  const [selectedChannel, setSelectedChannel] = useState<string>('#general');
  const [selectedAgent, setSelectedAgent] = useState<string | undefined>();

  const { switchToChat, tabs, activeTabId, switchTab } = useTab();

  // Agent management
  const {
    agents,
    loading: agentsLoading,
    error: agentsError,
  } = useAgents({
    pollInterval: 3000,
    autoRefresh: true,
  });

  // MessageBus connection
  const {
    connected,
    messages,
    error: messageBusError,
    sendMessage,
  } = useMessageBus({
    channel: selectedChannel,
    includeBus: true,
    autoConnect: true,
  });

  // Extract unique channels from messages
  const channels = React.useMemo(() => {
    const channelSet = new Set<string>(['#general', '#team', '#engineering']);
    messages.forEach((msg) => {
      if (msg.channel) {
        channelSet.add(msg.channel);
      }
    });
    return Array.from(channelSet).map((ch) => ({
      id: ch,
      name: ch,
      unreadCount: 0, // TODO: Implement unread tracking
    }));
  }, [messages]);

  // Handle channel selection
  const handleChannelSelect = useCallback((channelId: string) => {
    setSelectedChannel(channelId);
  }, []);

  // Handle agent selection
  const handleAgentSelect = useCallback((agentId: string) => {
    setSelectedAgent(agentId);
  }, []);

  // Handle message send
  const handleSendMessage = useCallback(
    async (content: string) => {
      // Parse @mentions to extract recipient
      const mentionMatch = content.match(/@(\w+)/);
      const recipient = mentionMatch ? mentionMatch[1] : 'default';

      await sendMessage(recipient, content, {
        channel: selectedChannel,
        message_type: 'chat',
      });
    },
    [sendMessage, selectedChannel]
  );

  // Handle slash commands
  const handleCommand = useCallback(
    async (command: string, args: string[]) => {
      // TODO: Implement slash commands
      // /agent spawn <id> - Spawn new agent
      // /broadcast <message> - Broadcast to all agents
      // /delegate <agent> <task> - Delegate task
      console.log(`Command: /${command}`, args);
    },
    []
  );

  // Handle keyboard shortcuts
  useInput((input, key) => {
    // Esc to return to chat
    if (key.escape) {
      switchToChat();
    }
    // Ctrl+P to cycle through tabs
    else if (key.ctrl && input === 'p') {
      const currentIndex = tabs.findIndex(t => t.id === activeTabId);
      const nextIndex = (currentIndex + 1) % tabs.length;
      switchTab(tabs[nextIndex].id);
    }
  });

  return (
    <Box flexDirection="column" height="100%">
      {/* Header */}
      <Box borderStyle="single" borderColor="cyan" paddingX={1}>
        <Text bold color="cyan">
          Penguin CLI - Multi-Agent Mode
        </Text>
        <Box flexGrow={1} />
        <Text dimColor>Ctrl+P: Switch tabs • Esc: Chat</Text>
      </Box>

      {/* Development Notice */}
      <Box borderStyle="round" borderColor="yellow" paddingX={1} marginY={1}>
        <Text color="yellow" bold>
          ⚠️  Under Development
        </Text>
        <Box marginLeft={2} flexDirection="column">
          <Text dimColor>
            Multi-agent UI is complete, but agent auto-response is not yet implemented.
          </Text>
          <Text dimColor>
            Messages are sent successfully but agents won't respond until backend support is added.
          </Text>
          <Text dimColor>
            Use the Chat tab for interactive conversations. Track progress in context/penguin_todo_multi_agents.md
          </Text>
        </Box>
      </Box>

      {/* Main Content */}
      <Box flexGrow={1} borderStyle="single">
        {/* Left Sidebar: Agents & Channels */}
        <Box flexDirection="column" width={20} borderStyle="single" borderColor="gray">
          <AgentRoster
            agents={agents}
            selectedAgentId={selectedAgent}
            onSelect={handleAgentSelect}
            maxHeight={10}
          />

          <Box marginTop={1}>
            <ChannelList
              channels={channels}
              selectedChannelId={selectedChannel}
              onSelect={handleChannelSelect}
              maxHeight={8}
            />
          </Box>
        </Box>

        {/* Right Content: Messages */}
        <Box flexDirection="column" flexGrow={1}>
          {/* Channel Header */}
          <Box paddingX={1} borderStyle="single" borderColor="gray">
            <Text bold color="cyan">
              Channel: {selectedChannel}
            </Text>
            <Box flexGrow={1} />
            {connected ? (
              <Text color="green">● Connected</Text>
            ) : (
              <Text color="red">○ Disconnected</Text>
            )}
          </Box>

          {/* Message Thread */}
          <Box flexGrow={1}>
            <MessageThread
              messages={messages}
              currentChannel={selectedChannel}
              showChannelFilter={false}
            />
          </Box>
        </Box>
      </Box>

      {/* Status Bar */}
      <Box borderStyle="single" borderColor="gray" paddingX={1}>
        <Text dimColor>
          {agents.length} agents | {messages.length} messages | Channel: {selectedChannel}
        </Text>
        <Box flexGrow={1} />
        {agentsError && <Text color="red">Error: {agentsError.message}</Text>}
        {messageBusError && <Text color="red">WS Error: {messageBusError.message}</Text>}
        {agentsLoading && <Text dimColor>Loading agents...</Text>}
      </Box>

      {/* Input Area */}
      <ChannelInputBar
        agents={agents}
        currentChannel={selectedChannel}
        onSendMessage={handleSendMessage}
        onCommand={handleCommand}
      />
    </Box>
  );
}
