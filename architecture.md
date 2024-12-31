# Penguin AI Assistant Architecture


main.py is the gateway to Penguin. Using core.py with various parameters that probabl shouldn't be above core.py such as system prompt, tool_manager (it does make sense to an extent, but it leads to asking questions about indexing workspace/conversations)



core.py is basically the central nervous system. It's the main class that orchestrates all the other systems.

It's 600 lines of code. Which feels like too much. At least for its capabilities. 200 lines of it are for task stuff which probably shouldn't be there. So it's more like 400, but then there's still plenty of room for improvement.

cognition is just the placeholder, is intended to be the brain in the future, with various things that are not yet implemented.

it then leads to api_client, which has its respective provider adapter classes, and a model config file. in terms of support its kind of a mess.

there's parser and tool usage. which is kind of duplicative. Typically you instantiate first in its own file (like perplexity), then again in tool_manager (kind of twice), then again in action_executor (parser). 

There is a thing in tool_manager, of all that json stuff, which could be helpful for function calling if I ever want to reimplement that in the future. I kind of dislike it, but I should be open to it. 

There then leads to conversation system. It used to be useless. Now you can list/load conversations, so I think it's more useful. Also think in terms of oop it is probably a good call to begin seperating it this early. 

various system files:
- conversation.py
- conversation_menu.py

- file_manager.py
- state.py
- session.py

- logging.py (isn't this more of a utils file?)

utils:

- diagnostics.py
- errors.py
- log_error.py

- logs.py

- parser.py
- notebook.py (more of an interactive shell)
- process_manager.py

- timing.py
- ui_constants.py

- path_utils.py (kind of redundant?) Apparently isn't even being used?

tools:

- tool_manager.py
- support.py (not in use, since code execution is handled by action_executor. though there's always the case of some tailored commmands so it doesn't repeat mistakes)

- perplexity_tool.py (search tool, is api and does cost money, but it's quicker than writing your own web scraper)


tools/memory

- workspace_search.py (used to search the workspace. hybrid approach of vector and text search)

tool for searching the workspace (is indexed at startup, so is it a tool entirely? or something more integrated?)

- memory_search.py (almost exactly like workspace_search, although used to search conversation logs instead of workspace)

Both are currently using chromadb, and ollama. chromadb caused a python dependency issue, so I'm not sure if it's being used long term.

I am thinking about a provider adapter system for other memory providers, so it's easier to switch in and out of.

I'm thinking of making the penguin memory requirements (or interface) pretty simple to use, and adapt it to the providers which should be done through a simple documentation search from cursor (long term Penguin)

as for memory:

there's context_window.py, which I'm not sure if it really works.

declarative_memory.py and summary_notes.py are kind of the same thing. Although summary_notes is only stored in sessions.

Seems to be an issue with summary notes are in workspace, but declarative_notes.yml is inside the penguin dir. 

I'm honestly thinking instead of summary notes, a summarization function as context window is being exceeded would be a better approach. 


------

## Core Components

### 1. Core Engine (core.py)
- `PenguinCore`: Central coordinator class that orchestrates all systems
  - Manages conversation flow
  - Delegates to specialized systems
  - Maintains state and control flow
  - Reference: `penguin/penguin/core.py` lines 1-14

### 2. LLM Integration
- `APIClient`: Handles LLM provider communication
  - Supports multiple models via LiteLLM
  - Manages API requests/responses
  - Handles provider-specific formatting
  - Reference: `penguin/penguin/llm/plain_english.md` lines 8-20

- `OpenAIAssistantManager`: Manages OpenAI's Assistants API
  - Creates and manages assistant instances
  - Handles thread management
  - Processes messages and runs
  - Reference: `penguin/penguin/llm/openai_assistant.py` lines 15-104

### 3. Cognition System
- `CognitionSystem`: Handles response generation and enhancement
  - Core response generation
  - Response enhancement modules
  - Action parsing/validation
  - Diagnostic tracking
  - Reference: `penguin/penguin/cognition/cognition.py` lines 1-13

### 4. Server Components
- `PenguinServer`: Flask-based API server
  - Rate limiting
  - Authentication
  - Session management
  - CORS configuration
  - Reference: `penguin/penguin/system/penguin_server.py` lines 1-38

- `FastAPI Server`: Alternative API implementation
  - WebSocket support
  - CORS middleware
  - Message processing
  - Reference: `penguin/server/api.py` lines 1-49

### 5. CLI Interface
- `PenguinCLI`: Command-line interface
  - User interaction handling
  - Command processing
  - Response formatting
  - Reference: `penguin/penguin/chat/cli.py` lines 1-24

### 6. Conversation Management
- `ConversationSystem`: Manages chat interactions
  - History management
  - Message formatting
  - System prompt handling
  - Reference: `penguin/copywriting/system/conversation.py` lines 1-39

### 7. Configuration
- Model settings
- API configurations
- Tool toggles
- Environment setup
- Reference: `penguin/config.yml` lines 12-44

## Supporting Systems

### 1. Memory System
- `SummaryNotes`: Persistent memory storage
  - Stores and retrieves summaries
  - Categorizes information
  - Manages timestamps
  - Reference: `penguin/penguin/memory/summary_notes.py` lines 1-50

### 2. Documentation
- Docusaurus-based documentation site
- API reference
- Usage guides
- Configuration instructions
- Reference: `penguin/docs/docs/intro.md` lines 1-52

### 3. Project Structure