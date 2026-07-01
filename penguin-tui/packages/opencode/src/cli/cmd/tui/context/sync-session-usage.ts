export function createPenguinSessionUsageUrl(baseUrl: string | URL, sessionID: string) {
  return new URL(`/api/v1/sessions/${encodeURIComponent(sessionID)}/token-usage`, baseUrl)
}
