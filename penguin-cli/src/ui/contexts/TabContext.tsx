/**
 * Tab Context
 *
 * Manages active tab state and switching between different views
 */

import React, { createContext, useContext, useState, ReactNode } from 'react';

export type TabType = 'chat' | 'sessions' | 'tasks' | 'agents';

export interface Tab {
  id: string;
  type: TabType;
  title: string;
  conversationId?: string; // For chat tabs
}

interface TabContextValue {
  tabs: Tab[];
  activeTabId: string;
  activeTab: Tab | undefined;
  switchTab: (tabId: string) => void;
  nextTab: () => void;
  prevTab: () => void;
  addTab: (tab: Tab) => void;
  closeTab: (tabId: string) => void;
}

const TabContext = createContext<TabContextValue | null>(null);

interface TabProviderProps {
  children: ReactNode;
  initialConversationId?: string;
}

export function TabProvider({ children, initialConversationId }: TabProviderProps) {
  // Initialize with default tabs
  const [tabs, setTabs] = useState<Tab[]>([
    {
      id: 'chat-1',
      type: 'chat',
      title: 'Chat',
      conversationId: initialConversationId,
    },
    {
      id: 'sessions',
      type: 'sessions',
      title: 'Sessions',
    },
  ]);

  const [activeTabId, setActiveTabId] = useState('chat-1');

  const activeTab = tabs.find((t) => t.id === activeTabId);

  const switchTab = (tabId: string) => {
    if (tabs.find((t) => t.id === tabId)) {
      setActiveTabId(tabId);
    }
  };

  const nextTab = () => {
    const currentIndex = tabs.findIndex((t) => t.id === activeTabId);
    const nextIndex = (currentIndex + 1) % tabs.length;
    setActiveTabId(tabs[nextIndex].id);
  };

  const prevTab = () => {
    const currentIndex = tabs.findIndex((t) => t.id === activeTabId);
    const prevIndex = currentIndex === 0 ? tabs.length - 1 : currentIndex - 1;
    setActiveTabId(tabs[prevIndex].id);
  };

  const addTab = (tab: Tab) => {
    setTabs((prev) => [...prev, tab]);
    setActiveTabId(tab.id);
  };

  const closeTab = (tabId: string) => {
    // Don't allow closing the last tab
    if (tabs.length === 1) return;

    setTabs((prev) => {
      const filtered = prev.filter((t) => t.id !== tabId);

      // If closing active tab, switch to previous tab
      if (activeTabId === tabId && filtered.length > 0) {
        const currentIndex = prev.findIndex((t) => t.id === tabId);
        const newIndex = currentIndex > 0 ? currentIndex - 1 : 0;
        setActiveTabId(filtered[newIndex].id);
      }

      return filtered;
    });
  };

  return (
    <TabContext.Provider
      value={{
        tabs,
        activeTabId,
        activeTab,
        switchTab,
        nextTab,
        prevTab,
        addTab,
        closeTab,
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
