import Link from "@docusaurus/Link";
import Head from "@docusaurus/Head";
import Layout from "@theme/Layout";
import {useState} from "react";

import styles from "./index.module.css";

const installCommand = "uv tool install penguin-ai";

const principles = [
  {
    number: "01",
    eyebrow: "Durable state",
    title: "Resume the state of the work, not just the chat.",
    description:
      "Sessions persist with checkpoints, rollback, branching, tool history, and file-backed context. Penguin can return to the same engineering state instead of reconstructing it from prose.",
    link: "/docs/usage/checkpointing",
  },
  {
    number: "02",
    eyebrow: "Execution truth",
    title: "A diff exists is not the same as the task is done.",
    description:
      "Run Mode preserves task phases, clarification requests, non-terminal outcomes, and review state so public surfaces do not flatten uncertainty into fake success.",
    link: "/docs/system/run-mode",
  },
  {
    number: "03",
    eyebrow: "Agents as tools",
    title: "Delegate a bounded job without losing the parent objective.",
    description:
      "Subagents can use isolated or shared context, scoped tool defaults, pause and resume controls, and explicit result reporting through Penguin's message layer.",
    link: "/docs/advanced/sub_agents",
  },
];

const workflow = [
  ["Objective", "Persist the goal and the task state before the loop runs."],
  ["Context", "Load project instructions and budget system, reference, dialog, and tool-output context separately."],
  ["Execution", "Read and edit files, run commands and tests, use the browser, or delegate bounded work."],
  ["Evidence", "Keep commands, test results, artifacts, failures, and acceptance checks attached to the task."],
  ["Outcome", "Finish truthfully: complete, waiting for input, blocked, paused, or ready for review."],
];

const evidence = [
  ["Implementation", "Changed files, relevant code paths, and task linkage"],
  ["Tests", "Targeted checks first, broader suites when the risk calls for them"],
  ["Usage", "Shell, API, browser, or recipe-based exercise of the real behavior"],
  ["Artifacts", "Logs, responses, screenshots, and generated files when they matter"],
  ["Lifecycle", "Task phase, clarification state, dependencies, and review truth"],
];

const surfaces = [
  {
    command: "penguin",
    name: "Terminal UI",
    description: "The full interactive coding workflow: streaming, tools, goals, and session navigation.",
  },
  {
    command: "penguin-cli",
    name: "Headless CLI",
    description: "Scriptable prompts, tasks, configuration, and automation for repeatable workflows.",
  },
  {
    command: "penguin-web",
    name: "Web runtime",
    description: "REST, WebSocket, and SSE access for the TUI and your own integrations.",
  },
  {
    command: "PenguinAgent()",
    name: "Python API",
    description: "Embed Penguin in applications while preserving the same runtime behavior.",
  },
];

function CopyButton({value}: {value: string}) {
  const [copied, setCopied] = useState(false);

  async function copyCommand() {
    await navigator.clipboard?.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  return (
    <button
      aria-label={`Copy ${value}`}
      className={styles.copyButton}
      onClick={copyCommand}
      type="button">
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function CommandLine({command = installCommand}: {command?: string}) {
  return (
    <div className={styles.commandLine}>
      <span aria-hidden="true">$</span>
      <code>{command}</code>
      <CopyButton value={command} />
    </div>
  );
}

function ProductPreview() {
  return (
    <figure className={styles.productPreview}>
      <div className={styles.previewBar}>
        <div className={styles.windowControls} aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <span className={styles.previewLabel}>penguin / active session</span>
        <span className={styles.previewStatus}>local</span>
      </div>
      <div className={styles.previewImageShell}>
        <img
          alt="Penguin terminal session showing an active goal, agent response, context usage, and modified files"
          className={styles.previewImage}
          loading="eager"
          src="/img/penguin-tui-session.png"
        />
      </div>
      <figcaption>
        Goal, context budget, modified files, and execution state remain visible in one session.
      </figcaption>
    </figure>
  );
}

function Hero() {
  return (
    <header className={styles.hero}>
      <div className={styles.heroGlow} />
      <div className={styles.heroInner}>
        <div className={styles.heroCopy}>
          <div className={styles.statusBadge}>
            <span className={styles.statusDot} />
            Open source · Python-first · stateful by design
          </div>
          <h1>From objective to evidence.</h1>
          <p className={styles.heroLead}>
            Penguin is a coding-agent runtime for long-running engineering tasks. It
            keeps task state, context, checkpoints, tool history, and verification
            evidence connected across sessions and agents.
          </p>
          <div className={styles.heroActions}>
            <a className={styles.primaryAction} href="#install">
              Install Penguin
              <span aria-hidden="true">↘</span>
            </a>
            <Link className={styles.secondaryAction} to="/docs/system/core-runtime">
              How the runtime works
              <span aria-hidden="true">→</span>
            </Link>
          </div>
          <div className={styles.heroCommand}>
            <CommandLine />
            <p>
              Then run <code>penguin</code>. First launch creates a workspace and walks
              through optional model setup.
            </p>
          </div>
        </div>
        <ProductPreview />
      </div>
      <div className={styles.heroProof} aria-label="Penguin runtime characteristics">
        <span>Sessions survive restarts</span>
        <span>Checkpoints branch and roll back</span>
        <span>Task state stays explicit</span>
        <span>TUI · CLI · REST/SSE · Python</span>
      </div>
    </header>
  );
}

function WhyPenguin() {
  return (
    <section className={styles.section} id="why-penguin">
      <div className={styles.sectionIntro}>
        <span className={styles.eyebrow}>What Penguin preserves</span>
        <h2>Software work is a state machine, not a chat transcript.</h2>
        <p>
          The objective, context, actions, clarifications, checkpoints, and evidence
          should remain inspectable after the model stops talking. Penguin makes that
          runtime state the product.
        </p>
      </div>
      <div className={styles.principleGrid}>
        {principles.map((principle) => (
          <article className={styles.principleCard} key={principle.number}>
            <div className={styles.principleMeta}>
              <span>{principle.number}</span>
              <span>{principle.eyebrow}</span>
            </div>
            <h3>{principle.title}</h3>
            <p>{principle.description}</p>
            <Link to={principle.link}>
              Learn more <span aria-hidden="true">→</span>
            </Link>
          </article>
        ))}
      </div>
    </section>
  );
}

function Evidence() {
  return (
    <section className={styles.evidenceSection}>
      <div className={styles.evidenceIntro}>
        <span className={styles.eyebrow}>Evidence-backed completion</span>
        <h2>Confidence is not a completion signal.</h2>
        <p>
          Penguin&apos;s reliability bar is explicit: implementation, tests, realistic
          usage, artifacts, and lifecycle state should agree before the work is handed
          back.
        </p>
        <Link className={styles.inlineLink} to="/docs/system/orchestration">
          Read about orchestration <span aria-hidden="true">→</span>
        </Link>
      </div>
      <div className={styles.evidenceLedger} aria-label="Completion evidence">
        <div className={styles.ledgerHeader}>
          <span>Evidence class</span>
          <span>What Penguin keeps attached</span>
        </div>
        {evidence.map(([name, description]) => (
          <div className={styles.ledgerRow} key={name}>
            <strong>{name}</strong>
            <p>{description}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function Workflow() {
  return (
    <section className={styles.workflowSection}>
      <div className={styles.workflowIntro}>
        <span className={styles.eyebrow}>The runtime loop</span>
        <h2>A loop that can explain why it stopped.</h2>
        <p>
          The Engine reasons and uses tools; Run Mode owns the task lifecycle; the
          conversation and event layers preserve what every surface needs to resume,
          supervise, and review the run.
        </p>
        <Link className={styles.inlineLink} to="/docs/usage/basic_usage">
          See the terminal workflow <span aria-hidden="true">→</span>
        </Link>
      </div>
      <ol className={styles.workflowSteps}>
        {workflow.map(([title, description], index) => (
          <li key={title}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div>
              <strong>{title}</strong>
              <p>{description}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Surfaces() {
  return (
    <section className={styles.section}>
      <div className={styles.sectionIntro}>
        <span className={styles.eyebrow}>One runtime, four ways in</span>
        <h2>The interface changes. The execution state does not.</h2>
        <p>
          Work interactively, automate from a script, connect over HTTP and streaming
          events, or embed Penguin in Python. Each surface sits over the same runtime
          services and durable state.
        </p>
      </div>
      <div className={styles.surfaceGrid}>
        {surfaces.map((surface) => (
          <article className={styles.surfaceCard} key={surface.command}>
            <code>{surface.command}</code>
            <h3>{surface.name}</h3>
            <p>{surface.description}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function QuickStart() {
  return (
    <section className={styles.installSection} id="install">
      <div className={styles.installCopy}>
        <span className={styles.eyebrow}>Quickstart</span>
        <h2>Install the runtime. Start a session.</h2>
        <p>
          First-run onboarding creates Penguin&apos;s workspace, verifies it is writable,
          and can connect OpenAI, Anthropic, OpenRouter, or local Ollama. Model setup
          can be skipped and resumed later.
        </p>
        <Link className={styles.inlineLink} to="/docs/getting_started">
          Full installation guide <span aria-hidden="true">→</span>
        </Link>
      </div>
      <div className={styles.installPanel}>
        <div className={styles.installStep}>
          <span>01</span>
          <div>
            <strong>Install</strong>
            <CommandLine />
          </div>
        </div>
        <div className={styles.installStep}>
          <span>02</span>
          <div>
            <strong>Launch</strong>
            <CommandLine command="penguin" />
          </div>
        </div>
        <p className={styles.installNote}>
          Python 3.9+ · macOS, Linux, and Windows · local Ollama models supported
        </p>
      </div>
    </section>
  );
}

function FinalCta() {
  return (
    <section className={styles.finalCta}>
      <span className={styles.eyebrow}>For work that survives the prompt</span>
      <h2>Resume it. Inspect it. Verify it.</h2>
      <p>
        Penguin is under active development and available under AGPL-3.0. Start in the
        terminal, then use the same runtime through the CLI, web API, or Python.
      </p>
      <div className={styles.heroActions}>
        <a className={styles.primaryAction} href="#install">
          Install Penguin <span aria-hidden="true">↗</span>
        </a>
        <Link className={styles.secondaryAction} to="/docs/intro">
          Explore the docs <span aria-hidden="true">→</span>
        </Link>
      </div>
    </section>
  );
}

export default function Home(): JSX.Element {
  return (
    <Layout>
      <Head>
        <title>Penguin — From objective to evidence</title>
        <meta
          content="Penguin is an open-source, Python-first coding-agent runtime that keeps task state, context, checkpoints, tool history, and verification evidence connected across sessions and agents."
          name="description"
        />
      </Head>
      <div className={styles.pageShell}>
        <Hero />
        <main className={styles.mainContent}>
          <WhyPenguin />
          <Evidence />
          <Workflow />
          <Surfaces />
          <QuickStart />
          <FinalCta />
        </main>
      </div>
    </Layout>
  );
}
