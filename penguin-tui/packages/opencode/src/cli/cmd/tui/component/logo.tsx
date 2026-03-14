import { useTerminalDimensions } from "@opentui/solid"
import { RGBA, TextAttributes } from "@opentui/core"
import { For, createMemo, type JSX } from "solid-js"
import { useTheme, tint } from "@tui/context/theme"
import { logo, marks } from "@/cli/logo"

type Segment = {
  text: string
  fg: RGBA
}

const SHADOW_MARKER = new RegExp(`[${marks}]`)
const MIN_PENGUIN_WORDMARK_WIDTH = 88
const PENGUIN_WORDMARK_FG = RGBA.fromHex("#f5f7fb")

function renderSegments(segments: Segment[]): JSX.Element[] {
  return segments.map((segment) => (
    <text fg={segment.fg} selectable={false}>
      {segment.text}
    </text>
  ))
}

export function Logo() {
  const { theme } = useTheme()

  const renderLine = (line: string, fg: RGBA, bold: boolean): JSX.Element[] => {
    const shadow = tint(theme.background, fg, 0.25)
    const attrs = bold ? TextAttributes.BOLD : undefined
    const elements: JSX.Element[] = []
    let i = 0

    while (i < line.length) {
      const rest = line.slice(i)
      const markerIndex = rest.search(SHADOW_MARKER)

      if (markerIndex === -1) {
        elements.push(
          <text fg={fg} attributes={attrs} selectable={false}>
            {rest}
          </text>,
        )
        break
      }

      if (markerIndex > 0) {
        elements.push(
          <text fg={fg} attributes={attrs} selectable={false}>
            {rest.slice(0, markerIndex)}
          </text>,
        )
      }

      const marker = rest[markerIndex]
      switch (marker) {
        case "_":
          elements.push(
            <text fg={fg} bg={shadow} attributes={attrs} selectable={false}>
              {" "}
            </text>,
          )
          break
        case "^":
          elements.push(
            <text fg={fg} bg={shadow} attributes={attrs} selectable={false}>
              ▀
            </text>,
          )
          break
        case "~":
          elements.push(
            <text fg={shadow} attributes={attrs} selectable={false}>
              ▀
            </text>,
          )
          break
      }

      i += markerIndex + 1
    }

    return elements
  }

  return (
    <box>
      <For each={logo.left}>
        {(line, index) => (
          <box flexDirection="row" gap={1}>
            <box flexDirection="row">{renderLine(line, theme.textMuted, false)}</box>
            <box flexDirection="row">{renderLine(logo.right[index()], theme.text, true)}</box>
          </box>
        )}
      </For>
    </box>
  )
}

function PenguinWordmark() {
  const dimensions = useTerminalDimensions()
  const compact = createMemo(() => dimensions().width < 120 || dimensions().width < MIN_PENGUIN_WORDMARK_WIDTH)

  const lines = createMemo(() => {
    // TODO: Make the Penguin wordmark palette theme-aware after Penguin mode theming stabilizes.
    if (compact()) {
      return [
        [{ text: "██████╗ ███████╗███╗   ██╗ ██████╗ ██╗   ██╗██╗███╗   ██╗", fg: PENGUIN_WORDMARK_FG }],
        [{ text: "██╔══██╗██╔════╝████╗  ██║██╔════╝ ██║   ██║██║████╗  ██║", fg: PENGUIN_WORDMARK_FG }],
        [{ text: "██████╔╝█████╗  ██╔██╗ ██║██║  ███╗██║   ██║██║██╔██╗ ██║", fg: PENGUIN_WORDMARK_FG }],
        [{ text: "██╔═══╝ ██╔══╝  ██║╚██╗██║██║   ██║██║   ██║██║██║╚██╗██║", fg: PENGUIN_WORDMARK_FG }],
        [{ text: "██║     ███████╗██║ ╚████║╚██████╔╝╚██████╔╝██║██║ ╚████║", fg: PENGUIN_WORDMARK_FG }],
        [{ text: "╚═╝     ╚══════╝╚═╝  ╚═══╝ ╚═════╝  ╚═════╝ ╚═╝╚═╝  ╚═══╝", fg: PENGUIN_WORDMARK_FG }],
      ]
    }

    return [
      [{ text: "ooooooooo.                                                 o8o", fg: PENGUIN_WORDMARK_FG }],
      [{ text: "`888   `Y88.                                               `\"'", fg: PENGUIN_WORDMARK_FG }],
      [{ text: " 888   .d88'  .ooooo.  ooo. .oo.    .oooooooo oooo  oooo  oooo  ooo. .oo.", fg: PENGUIN_WORDMARK_FG }],
      [{ text: " 888ooo88P'  d88' `88b `888P\"Y88b  888' `88b  `888  `888  `888  `888P\"Y88b", fg: PENGUIN_WORDMARK_FG }],
      [{ text: " 888         888ooo888  888   888  888   888   888   888   888   888   888", fg: PENGUIN_WORDMARK_FG }],
      [{ text: " 888         888    .o  888   888  `88bod8P'   888   888   888   888   888", fg: PENGUIN_WORDMARK_FG }],
      [{ text: "o888o        `Y8bod8P' o888o o888o `8oooooo.   `V88V\"V8P' o888o o888o o888o", fg: PENGUIN_WORDMARK_FG }],
      [{ text: "                                   d\"     YD", fg: PENGUIN_WORDMARK_FG }],
      [{ text: "                                   \"Y88888P'", fg: PENGUIN_WORDMARK_FG }],
    ]
  })

  return (
    <box>
      <For each={lines()}>{(line) => <box flexDirection="row">{renderSegments(line)}</box>}</For>
    </box>
  )
}

export function PenguinLogo() {
  return (
    <box alignItems="center">
      <PenguinWordmark />
    </box>
  )
}
