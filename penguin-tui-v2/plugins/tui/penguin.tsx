import type { Plugin } from "@opencode-ai/plugin/tui"

function PenguinCommands(context: Plugin.Context) {
  context.keymap.layer(() => ({
    mode: "global",
    commands: [
      {
        id: "penguin.status",
        title: "Penguin status",
        description: "Show the active Penguin project and session count",
        group: "Penguin",
        palette: true,
        slash: { name: "penguin" },
        run() {
          const directory = context.location?.directory
          const sessions = context.data.session.list().length
          const project = directory
            ? context.ui.format.path(directory)
            : "project unavailable"
          context.ui.toast.show({
            title: "Penguin",
            message: `${project} · ${sessions} session${sessions === 1 ? "" : "s"}`,
            variant: "success",
          })
        },
      },
    ],
  }))
  return null
}

export default {
  id: "penguin.product",
  setup(context: Plugin.Context) {
    context.ui.slot("app", () => PenguinCommands(context))
  },
}
