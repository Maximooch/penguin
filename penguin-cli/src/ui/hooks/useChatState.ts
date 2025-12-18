/**
 * Chat State Hook - Consolidated state management for ChatSession
 *
 * Uses hybrid approach:
 * - useReducer for UI state (modals, pagination, flags)
 * - Simple useState for data (sessions, projects, tasks)
 *
 * Replaces 20+ useState hooks with organized state management.
 */

import { useReducer, useState, useCallback, useMemo } from 'react';
import type { Session } from '../../core/types.js';
import type { Project, Task } from '../../core/api/ProjectAPI.js';

// ============================================================================
// Types
// ============================================================================

export type ActiveModal =
  | 'sessions'
  | 'model'
  | 'settings'
  | 'projects'
  | 'tasks'
  | null;

export interface UIState {
  // Modal state - only one can be open at a time
  activeModal: ActiveModal;
  isLoadingModal: boolean;

  // Input state
  inputKey: number; // Used to force input remount/clear
  suggestions: string[];

  // Timeline state
  timelinePageOffset: number;
  showReasoning: boolean;

  // App state
  isExiting: boolean;
}

export type UIAction =
  | { type: 'OPEN_MODAL'; modal: ActiveModal }
  | { type: 'CLOSE_MODAL' }
  | { type: 'SET_LOADING_MODAL'; loading: boolean }
  | { type: 'SET_SUGGESTIONS'; suggestions: string[] }
  | { type: 'CLEAR_INPUT' }
  | { type: 'SET_TIMELINE_OFFSET'; offset: number }
  | { type: 'TOGGLE_REASONING' }
  | { type: 'SET_EXITING'; exiting: boolean }
  | { type: 'RESET_UI' };

// ============================================================================
// Reducer
// ============================================================================

const initialUIState: UIState = {
  activeModal: null,
  isLoadingModal: false,
  inputKey: 0,
  suggestions: [],
  timelinePageOffset: 0,
  showReasoning: false,
  isExiting: false,
};

function uiReducer(state: UIState, action: UIAction): UIState {
  switch (action.type) {
    case 'OPEN_MODAL':
      return {
        ...state,
        activeModal: action.modal,
        isLoadingModal: false,
      };

    case 'CLOSE_MODAL':
      return {
        ...state,
        activeModal: null,
        isLoadingModal: false,
      };

    case 'SET_LOADING_MODAL':
      return {
        ...state,
        isLoadingModal: action.loading,
      };

    case 'SET_SUGGESTIONS':
      return {
        ...state,
        suggestions: action.suggestions,
      };

    case 'CLEAR_INPUT':
      return {
        ...state,
        inputKey: state.inputKey + 1,
        suggestions: [],
      };

    case 'SET_TIMELINE_OFFSET':
      return {
        ...state,
        timelinePageOffset: action.offset,
      };

    case 'TOGGLE_REASONING':
      return {
        ...state,
        showReasoning: !state.showReasoning,
      };

    case 'SET_EXITING':
      return {
        ...state,
        isExiting: action.exiting,
      };

    case 'RESET_UI':
      return {
        ...initialUIState,
        inputKey: state.inputKey + 1, // Preserve input key increment
      };

    default:
      return state;
  }
}

// ============================================================================
// Hook
// ============================================================================

export interface UseChatStateReturn {
  // UI State (from reducer)
  ui: UIState;

  // Data State (simple useState)
  sessions: Session[];
  projects: Project[];
  tasks: Task[];

  // UI Actions
  openModal: (modal: ActiveModal) => void;
  closeModal: () => void;
  setLoadingModal: (loading: boolean) => void;
  setSuggestions: (suggestions: string[]) => void;
  clearInput: () => void;
  setTimelineOffset: (offset: number) => void;
  adjustTimelineOffset: (delta: number, max: number) => void;
  toggleReasoning: () => void;
  setExiting: (exiting: boolean) => void;
  resetUI: () => void;

  // Data Actions
  setSessions: (sessions: Session[]) => void;
  setProjects: (projects: Project[]) => void;
  setTasks: (tasks: Task[]) => void;

  // Convenience getters for backwards compatibility
  showSessionPicker: boolean;
  showModelSelector: boolean;
  showSettings: boolean;
  showingProjectList: boolean;
  showingTaskList: boolean;
  isLoadingSessions: boolean;
  inputKey: number;
  suggestions: string[];
  timelinePageOffset: number;
  showReasoning: boolean;
  isExiting: boolean;
}

export function useChatState(): UseChatStateReturn {
  // UI state via reducer
  const [ui, dispatch] = useReducer(uiReducer, initialUIState);

  // Data state via simple useState
  const [sessions, setSessions] = useState<Session[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);

  // UI Actions
  const openModal = useCallback((modal: ActiveModal) => {
    dispatch({ type: 'OPEN_MODAL', modal });
  }, []);

  const closeModal = useCallback(() => {
    dispatch({ type: 'CLOSE_MODAL' });
  }, []);

  const setLoadingModal = useCallback((loading: boolean) => {
    dispatch({ type: 'SET_LOADING_MODAL', loading });
  }, []);

  const setSuggestions = useCallback((suggestions: string[]) => {
    dispatch({ type: 'SET_SUGGESTIONS', suggestions });
  }, []);

  const clearInput = useCallback(() => {
    dispatch({ type: 'CLEAR_INPUT' });
  }, []);

  const setTimelineOffset = useCallback((offset: number) => {
    dispatch({ type: 'SET_TIMELINE_OFFSET', offset });
  }, []);

  const adjustTimelineOffset = useCallback((delta: number, max: number) => {
    dispatch({
      type: 'SET_TIMELINE_OFFSET',
      offset: Math.max(0, Math.min(ui.timelinePageOffset + delta, max)),
    });
  }, [ui.timelinePageOffset]);

  const toggleReasoning = useCallback(() => {
    dispatch({ type: 'TOGGLE_REASONING' });
  }, []);

  const setExiting = useCallback((exiting: boolean) => {
    dispatch({ type: 'SET_EXITING', exiting });
  }, []);

  const resetUI = useCallback(() => {
    dispatch({ type: 'RESET_UI' });
  }, []);

  // Convenience getters for backwards compatibility with existing code
  const derivedState = useMemo(() => ({
    showSessionPicker: ui.activeModal === 'sessions',
    showModelSelector: ui.activeModal === 'model',
    showSettings: ui.activeModal === 'settings',
    showingProjectList: ui.activeModal === 'projects',
    showingTaskList: ui.activeModal === 'tasks',
    isLoadingSessions: ui.isLoadingModal && ui.activeModal === 'sessions',
  }), [ui.activeModal, ui.isLoadingModal]);

  return {
    // UI State
    ui,

    // Data State
    sessions,
    projects,
    tasks,

    // UI Actions
    openModal,
    closeModal,
    setLoadingModal,
    setSuggestions,
    clearInput,
    setTimelineOffset,
    adjustTimelineOffset,
    toggleReasoning,
    setExiting,
    resetUI,

    // Data Actions
    setSessions,
    setProjects,
    setTasks,

    // Convenience getters
    ...derivedState,
    inputKey: ui.inputKey,
    suggestions: ui.suggestions,
    timelinePageOffset: ui.timelinePageOffset,
    showReasoning: ui.showReasoning,
    isExiting: ui.isExiting,
  };
}
