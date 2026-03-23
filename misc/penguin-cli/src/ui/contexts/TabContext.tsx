/**
 * Tab Context
 *
 * Manages active tab state and switching between different views
 */

import React, { createContext, useContext, useState, ReactNode } from 'react';

export type TabType = 'chat' | 'dashboard' | 'agents';

export interface Tab {
  id: string;
  type: TabType;
  title: string;
}

interface TabContextValue {
  tabs: Tab[];
  activeTabId: string;
  activeTab: Tab | undefined;
  switchTab: (tabId: string) => void;
  switchToDashboard: () => void;
  switchToChat: () => void;
  switchToAgents: () => void;
  currentConversationId: string | undefined;
  switchConversation: (conversationId: string) => void;
}

const TabContext = createContext<TabContextValue | null>(null);

interface TabProviderProps {
  children: ReactNode;
  initialConversationId?: string;
}

export function TabProvider({ children, initialConversationId }: TabProviderProps) {
  // Three-tab system: Dashboard, Chat, and Agents
  const [tabs] = useState<Tab[]>([
    {
      id: 'dashboard',
      type: 'dashboard',
      title: 'Dashboard',
    },
    {
      id: 'chat',
      type: 'chat',
      title: 'Chat',
    },
    {
      id: 'agents',
      type: 'agents',
      title: 'Agents',
    },
  ]);

  const [activeTabId, setActiveTabId] = useState('chat');
  const [conversationId, setConversationId] = useState(initialConversationId);

  const activeTab = tabs.find((t) => t.id === activeTabId);

  const switchTab = (tabId: string) => {
    if (tabs.find((t) => t.id === tabId)) {
      setActiveTabId(tabId);
    }
  };

  const switchToDashboard = () => {
    setActiveTabId('dashboard');
  };

  const switchToChat = () => {
    setActiveTabId('chat');
  };

  const switchToAgents = () => {
    setActiveTabId('agents');
  };

  const switchConversation = (newConversationId: string) => {
    setConversationId(newConversationId);
    setActiveTabId('chat'); // Switch to chat tab when loading a conversation
  };

  return (
    <TabContext.Provider
      value={{
        tabs,
        activeTabId,
        activeTab,
        switchTab,
        switchToDashboard,
        switchToChat,
        switchToAgents,
        currentConversationId: conversationId,
        switchConversation,
      }}
    >
      {children}
    </TabContext.Provider>
  );
}

export function useTab(): TabContextValue {
  const context = useContext(TabContext);
  if (!context) {
    throw new Error('useTab must be used within TabProvider');
  }
  return context;
}
