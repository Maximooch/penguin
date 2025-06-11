import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

/**
 * Creating a sidebar enables you to:
 - create an ordered group of docs
 - render a sidebar for each doc of that group
 - provide next/previous navigation

 The sidebars can be generated from the filesystem, or explicitly defined here.

 Create as many sidebars as you want.
 */
const sidebars: SidebarsConfig = {
  // By default, Docusaurus generates a sidebar from the docs folder structure
  tutorialSidebar: [
    'intro',
    'getting_started',
    'configuration',
    {
      type: 'category',
      label: 'System',
      items: [
        'system/context-window',
        'system/conversation-manager',
        'system/memory-system',
        'system/run-mode',
        'system/state-management',
      ],
    },
    {
      type: 'category',
      label: 'Usage Guide',
      items: [
        'usage/basic_usage',
        'usage/automode',
        'usage/task_management',
        'usage/checkpointing',
        'usage/project_management',
        'usage/api_usage',
      ],
    },
    {
      type: 'category',
      label: 'Advanced Topics',
      items: [
        'advanced/custom_tools',
        'advanced/error_handling',
        'advanced/diagnostics',
        'advanced/pydoll_browser_tools',
        'advanced/future_considerations',
        'advanced/roadmap',
      ],
    },
    {
      type: 'category',
      label: 'API Reference',
      items: [
        'api_reference/core',
        'api_reference/engine',
        'api_reference/chat_manager',
        'api_reference/tool_manager',
        'api_reference/parser',
        'api_reference/api_client',
        'api_reference/model_config',
        'api_reference/provider_adapters',
        'api_reference/api_server',
        'api_reference/webui',
      ],
    },
  ],
};

export default sidebars;
