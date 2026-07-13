import type { PenguinGoal } from "../../context/sync-bootstrap"

export type SessionGoalSummary = {
  status: string
  objective: string
  tokens: string
}

const GOAL_OBJECTIVE_PREVIEW_CHARS = 120

function objectivePreview(objective: string): string {
  const singleLine = objective.replace(/\s+/g, " ").trim()
  if (singleLine.length <= GOAL_OBJECTIVE_PREVIEW_CHARS) return singleLine
  return `${singleLine.slice(0, GOAL_OBJECTIVE_PREVIEW_CHARS - 1).trimEnd()}…`
}

export function summarizeSessionGoal(goal: PenguinGoal): SessionGoalSummary {
  const tokensUsed = goal.tokens_used.toLocaleString("en-US")
  const tokenBudget = goal.token_budget?.toLocaleString("en-US")

  return {
    status: goal.status.replaceAll("_", " "),
    objective: objectivePreview(goal.objective),
    tokens: tokenBudget ? `${tokensUsed} / ${tokenBudget} tokens` : `${tokensUsed} tokens used`,
  }
}
