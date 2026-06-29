import { Flag } from "../flag/flag"

export function createServerAuthorizationHeader(input?: { username?: string; password?: string }): string | undefined {
  const password = input?.password ?? Flag.OPENCODE_SERVER_PASSWORD
  if (!password) return undefined
  const username = input?.username ?? Flag.OPENCODE_SERVER_USERNAME ?? "opencode"
  return `Basic ${btoa(`${username}:${password}`)}`
}

export function createServerFetchRequest(
  input: RequestInfo | URL,
  init?: RequestInit,
  authorization = createServerAuthorizationHeader(),
): Request {
  const request = new Request(input, init)
  if (!authorization) return request
  if (request.headers.has("Authorization")) return request

  const headers = new Headers(request.headers)
  headers.set("Authorization", authorization)
  return new Request(request, { headers })
}
