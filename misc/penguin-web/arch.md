March 22nd 2025AD 1005p Saturday

God bless us all!


1. chat with conversations on the left sidebar (like a typical chatgpt ai chat app layout)
2. project management dashboard
3. Document Manager, a simple text editor/file system (this can come later, would be last in priority) 
4. settings dashboard



penguin-web/
├── package.json
├── vite.config.js
├── index.html
├── public/
│   └── favicon.ico
└── src/
    ├── main.jsx
    ├── App.jsx
    ├── components/
    │   ├── chat/
    │   │   ├── ChatBox.jsx
    │   │   ├── MessageList.jsx
    │   │   ├── ConversationList.jsx
    │   │   └── ChatInterface.jsx
    │   ├── projects/
    │   │   ├── ProjectList.jsx
    │   │   ├── ProjectDetails.jsx
    │   │   ├── CreateProject.jsx
    │   │   └── ProjectDashboard.jsx
    │   ├── documents/
    │   │   ├── FileExplorer.jsx
    │   │   ├── TextEditor.jsx
    │   │   └── DocumentManager.jsx
    │   ├── settings/
    │   │   ├── ModelSettings.jsx
    │   │   ├── ApiSettings.jsx
    │   │   └── SettingsDashboard.jsx
    │   └── layout/
    │       ├── Sidebar.jsx
    │       ├── MainContent.jsx
    │       └── AppLayout.jsx
    ├── hooks/
    │   ├── useChat.js
    │   ├── useProjects.js
    │   ├── useDocuments.js
    │   └── useSettings.js
    ├── services/
    │   └── api.js
    ├── contexts/
    │   ├── ChatContext.jsx
    │   └── SettingsContext.jsx
    └── styles/
        └── index.css


## Core Technologies
- **Vite**: Fast, modern build tool with minimal configuration
  - Provides lightning-fast HMR (Hot Module Replacement)
  - Optimized production builds
  - Native ESM support for rapid development
  - Version: ^5.0.0

- **React**: UI library for component-based development
  - Efficient rendering with virtual DOM
  - Component-based architecture
  - Hooks for state and side effects
  - Version: ^18.2.0

- **TypeScript**: Typed JavaScript for improved developer experience
  - Static type checking
  - Enhanced IDE support and autocompletion
  - Better refactoring capabilities
  - Version: ^5.2.0

## UI & Styling
- **Tailwind CSS**: Utility-first CSS framework
  - Rapid UI development with utility classes
  - Consistent design system
  - JIT compiler for optimized production builds
  - Version: ^3.3.0

- **Headless UI**: Unstyled, accessible UI components
  - Works seamlessly with Tailwind
  - Keyboard navigation and screen reader support
  - Flexible styling options
  - Version: ^1.7.0

## State Management & Data Fetching
- **React Context API**: Built-in state management
  - Avoids prop drilling
  - Global state for themes, user preferences, etc.
  - Combined with useReducer for complex state logic

- **TanStack Query**: Data fetching library
  - Caching and automatic refetching
  - Loading/error states
  - Optimistic updates
  - Real-time data synchronization
  - Version: ^5.0.0

- **Axios**: HTTP client
  - Consistent API for requests
  - Request/response interceptors
  - Automatic JSON transformation
  - Version: ^1.6.0

## Routing & Navigation
- **React Router**: Client-side routing
  - Declarative routing with components
  - Nested routes for complex layouts
  - Route-based code splitting
  - Version: ^6.20.0

## Developer Tools
- **ESLint**: Code linting
  - Enforces code quality standards
  - Customizable rule sets
  - TypeScript integration
  - Version: ^8.54.0

- **Prettier**: Code formatting
  - Consistent code style
  - Integrates with ESLint
  - Automated formatting on save/commit
  - Version: ^3.1.0

- **Vitest**: Testing framework
  - Fast, Vite-native test runner
  - Compatible with Jest API
  - Component testing with React Testing Library
  - Version: ^1.0.0

## UI Components
- **Markdown Support**: react-markdown
  - Rendering markdown in chat messages
  - Code syntax highlighting
  - Version: ^9.0.0

- **react-syntax-highlighter**: Code highlighting
  - Syntax highlighting for code blocks
  - Multiple themes available
  - Version: ^15.5.0

## Deployment & Environment
- **Docker**: Development containerization
  - Consistent development environment
  - Easy onboarding for new developers
  - Production-ready container builds

- **Environment Variables**: Configuration management
  - API endpoints
  - Feature flags
  - Environment-specific settings

## Package Management
- **npm**: Dependency management
  - Lock file for consistent installs
  - Scripts for common tasks
  - Workspaces for monorepo (if needed)
