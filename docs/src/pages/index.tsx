import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';

import styles from './index.module.css';

const installCommand = 'uv tool install penguin-ai';
const launchCommand = 'penguin';

const whyPenguin = [
  'Purpose-built for software engineering workflows, with coding tools, sessions, and subagents.',
  'Stateful runtime: sessions, checkpoints, tool history, and replayable transcripts.',
  'Context Window Manager: long sessions stay coherent through category-aware token budgeting, truncation, and replay, preserving recency and message-category priorities across long-running sessions.',
  'Multi-agent orchestration: planner/implementer/QA patterns, subagents, and scoped delegation.',
  'Multiple surfaces: TUI, CLI, web API, and Python client on the same backend.',
  'OpenCode-compatible TUI path: Penguin web/core now powers an OpenCode-style terminal UX.',
];

const whatYouGet = [
  'Coding workflow tools: file reads/writes/diffs, shell commands, test execution, search, code analysis, and background process management.',
  'Context Window Manager: category-based token budgets, multimodal truncation, and live usage reporting to keep histories within model limits. This supports theoretically infinite sessions.',
  'Persistent memory and file-backed context: declarative notes, summary notes, context artifacts, docs cache, and daily journal continuity.',
  'Multi-agent execution: isolated or shared-context subagents, delegation, planner/implementer/QA patterns, and background task execution.',
  'Browser and research support: web search plus browser automation for documentation, web workflows, and UI testing.',
  'Session durability: checkpoints, rollback, branching, transcript replay, and long-running task continuity.',
  'Project and task orchestration backed by SQLite, including todo tracking and Run Mode.',
  'Native and gateway model support across OpenAI, Anthropic, and OpenRouter by default, with LiteLLM available as an optional extra.',
];

const interfaces = [
  ['penguin / ptui', 'Terminal-first coding workflow with streaming, tools, and session navigation.'],
  ['penguin-cli', 'Scriptable CLI interface for prompts, tasks, config, and automation.'],
  ['penguin-web', 'REST + WebSocket/SSE backend for the TUI and custom integrations.'],
  ['Python API', 'PenguinAgent, PenguinClient, and PenguinAPI for embedding Penguin in code.'],
];

const quickStart = [
  ['Recommended install', 'uv tool install penguin-ai'],
  ['Alternative install', 'pip install penguin-ai'],
  ['Set a model key', 'export OPENROUTER_API_KEY="your_api_key"'],
  ['Launch Penguin', 'penguin'],
];

function CopyButton({value}: {value: string}) {
  return (
    <button
      className={styles.copyButton}
      type="button"
      onClick={() => navigator.clipboard?.writeText(value)}>
      Copy
    </button>
  );
}

function CommandLine({command}: {command: string}) {
  return (
    <div className={styles.commandLine}>
      <span>$</span>
      <code>{command}</code>
      <CopyButton value={command} />
    </div>
  );
}

function HomepageHeader() {
  return (
    <header className={styles.heroShell}>
      <div className={styles.heroGrid}>
        <section className={styles.heroCopy}>
          <div className={styles.statusBadge}>
            <span className={styles.statusDot} />
            Open-source coding agent built on a scalable cognitive architecture runtime
          </div>
          <h1 className={styles.heroTitle}>Penguin</h1>
          <p className={styles.heroSubtitle}>
            Penguin is designed for long-running, tool-using, multi-agent software
            workflows: from interactive coding in the TUI to persistent sessions,
            subagent delegation, and API-driven automation. It combines a
            coding-focused agent runtime with durable state, workspace-aware tools,
            and multiple interfaces on top of the same core.
          </p>
          <div className={styles.heroActions}>
            <Link className={styles.primaryAction} to="/docs/intro">
              Read the docs
            </Link>
            <Link
              className={styles.secondaryAction}
              to="https://github.com/maximooch/penguin">
              View GitHub
            </Link>
          </div>
          <div className={styles.commandStack} aria-label="Install commands">
            <CommandLine command={installCommand} />
            <CommandLine command={launchCommand} />
          </div>
        </section>

        <aside className={styles.terminalCard} aria-label="Penguin runtime preview">
          <div className={styles.terminalChrome}>
            <span />
            <span />
            <span />
            <p>penguin://session/runtime</p>
          </div>
          <div className={styles.penguinMark} aria-hidden="true">
            🐧
          </div>
          {/* Reserved for a Penguin TUI screenshot.
          <div className={styles.terminalRows}>
            <p><span>runtime</span> scalable cognitive architecture</p>
            <p><span>state</span> sessions · checkpoints · replay</p>
            <p><span>tools</span> files · shell · tests · browser · web</p>
            <p><span>agents</span> subagents · delegation · orchestration</p>
          </div>
          */}
        </aside>
      </div>
    </header>
  );
}

function WhyPenguin() {
  return (
    <section className={styles.sectionBlock}>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionKicker}>Why Penguin</span>
        <h2>Purpose-built for software engineering workflows.</h2>
        <p>
          Penguin carries the README promise onto the homepage: coding tools,
          sessions, subagents, long-session context management, and one backend
          across every interface.
        </p>
      </div>
      <div className={styles.pillarGrid}>
        {whyPenguin.map((item, index) => (
          <article className={styles.pillarCard} key={item}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <p>{item}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function InterfaceSection() {
  return (
    <section className={styles.splitSection}>
      <div>
        <span className={styles.sectionKicker}>Interfaces</span>
        <h2>Same runtime. Multiple surfaces.</h2>
        <p>
          Penguin exposes the same runtime through several surfaces: terminal UI,
          scriptable CLI, web/API backend, and Python embedding.
        </p>
      </div>
      <div className={styles.surfaceList}>
        {interfaces.map(([label, description]) => (
          <article className={styles.surfaceRow} key={label}>
            <strong>{label}</strong>
            <p>{description}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function WhatYouGet() {
  return (
    <section className={styles.capabilitySection}>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionKicker}>What You Get</span>
        <h2>Coding workflow tools, durable state, and orchestration.</h2>
      </div>
      <div className={styles.capabilityGrid}>
        {whatYouGet.map((capability) => (
          <div className={styles.capabilityItem} key={capability}>
            {capability}
          </div>
        ))}
      </div>
    </section>
  );
}

function QuickStart() {
  return (
    <section className={styles.sectionBlock}>
      <div className={styles.workflowPanel}>
        <div className={styles.workflowIntro}>
          <span className={styles.sectionKicker}>Quick Start</span>
          <h2>Install Penguin, set a model key, and launch.</h2>
          <p>
            The README recommends uv for faster installs, simpler Python environment
            management, and this repo&apos;s safer dependency workflow. Plain pip still works.
          </p>
        </div>
        <div className={styles.installSteps}>
          {quickStart.map(([label, command]) => (
            <article className={styles.installStep} key={label}>
              <strong>{label}</strong>
              <CommandLine command={command} />
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function FinalCta() {
  return (
    <section className={styles.finalCta}>
      <h2>Open-source coding agent. Scalable runtime. Real workflows.</h2>
      <p>
        Start in the TUI, automate through the CLI, serve it over the web/API, or
        embed Penguin in Python. The point is continuity: durable state,
        workspace-aware tools, and multiple interfaces on the same core.
      </p>
      <div className={styles.heroActions}>
        <Link className={styles.primaryAction} to="/docs/getting_started">
          Start building
        </Link>
        <Link className={styles.secondaryAction} to="/docs/intro">
          Read the docs
        </Link>
      </div>
    </section>
  );
}

export default function Home(): JSX.Element {
  return (
    <Layout>
      <div className={styles.pageShell}>
        <HomepageHeader />
        <main className={styles.mainContent}>
          <WhyPenguin />
          <InterfaceSection />
          <WhatYouGet />
          <QuickStart />
          <FinalCta />
        </main>
      </div>
    </Layout>
  );
}
