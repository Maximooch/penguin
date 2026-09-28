const config = {
  title: 'Penguin',
  tagline: 'A coding agent built to stay with the work.',
  url: 'https://penguin-rho.vercel.app',
  baseUrl: '/',
  onBrokenLinks: 'throw',
  favicon: 'img/favicon.ico',
  organizationName: 'maximooch',
  projectName: 'penguin',

  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
    mermaid: true,
  },

  themes: ['@docusaurus/theme-mermaid'],

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: require.resolve('./sidebars.js'),
          editUrl: 'https://github.com/maximooch/penguin/tree/main/docs/',
        },
        theme: {
          customCss: require.resolve('./src/css/custom.css'),
        },
      },
    ],
  ],

  themeConfig: {
    colorMode: {
      defaultMode: 'light',
      disableSwitch: false,
      respectPrefersColorScheme: true,
    },
    image: 'img/penguin-social-card-v2.png',
    metadata: [
      {
        name: 'description',
        content:
          'Penguin is an open-source, Python-first coding-agent runtime that keeps task state, context, checkpoints, tool history, and verification evidence connected across sessions and agents.',
      },
    ],
    mermaid: {
      theme: {light: 'neutral', dark: 'forest'},
    },
    navbar: {
      title: 'Penguin',
      logo: {
        alt: 'Penguin',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'doc',
          docId: 'intro',
          position: 'left',
          label: 'Docs',
        },
        {
          to: '/docs/getting_started',
          label: 'Quickstart',
          position: 'left',
        },
        {
          to: '/docs/usage/basic_usage',
          label: 'Guides',
          position: 'left',
        },
        {
          to: '/docs/api_reference/api_server',
          label: 'API',
          position: 'left',
        },
        {
          href: 'https://github.com/maximooch/penguin',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {
              label: 'Getting Started',
              to: '/docs/getting_started',
            },
            {
              label: 'Configuration',
              to: '/docs/configuration',
            },
            {
              label: 'CLI Commands',
              to: '/docs/usage/cli_commands',
            },
          ],
        },
        {
          title: 'Build with Penguin',
          items: [
            {
              label: 'Python API',
              to: '/docs/usage/python_api_reference',
            },
            {
              label: 'Web Runtime',
              to: '/docs/usage/web_interface',
            },
            {
              label: 'Custom Tools',
              to: '/docs/advanced/custom_tools',
            },
          ],
        },
        {
          title: 'Project',
          items: [
            {
              label: 'GitHub',
              href: 'https://github.com/maximooch/penguin',
            },
            {
              label: 'Contributing',
              href: 'https://github.com/maximooch/penguin/blob/main/CONTRIBUTING.md',
            },
            {
              label: 'License',
              href: 'https://github.com/maximooch/penguin/blob/main/LICENSE',
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Maximus Putnam. Built with Docusaurus.`,
    },
  },
};

module.exports = config;
