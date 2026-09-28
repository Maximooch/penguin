import { describe, expect, test } from "bun:test"
import { readdirSync } from "node:fs"
import { createRequire } from "node:module"
import { join, resolve } from "node:path"
import { pathToFileURL } from "node:url"
import { z } from "zod"

type ProviderUtils = typeof import("@ai-sdk/provider-utils")

const limit = 64 * 1024 * 1024
const require = createRequire(import.meta.url)
const store = resolve(import.meta.dir, "../../../../node_modules/.bun")
const variants = readdirSync(store, { withFileTypes: true })
  .filter((entry) => entry.isDirectory() && entry.name.startsWith("@ai-sdk+provider-utils@3.0.32+"))
  .map((entry) => {
    const root = join(store, entry.name, "node_modules/@ai-sdk/provider-utils")
    return {
      entries: [
        {
          format: "CJS",
          load: async () => require(join(root, "dist/index.js")) as ProviderUtils,
        },
        {
          format: "ESM",
          load: async () => (await import(pathToFileURL(join(root, "dist/index.mjs")).href)) as ProviderUtils,
        },
      ],
      name: entry.name,
      root,
    }
  })

describe("provider-utils JSON response limit", () => {
  test("discovers every installed peer variant", () => {
    expect(variants.length).toBeGreaterThan(0)
  })

  for (const variant of variants) {
    for (const entry of variant.entries) {
      test(`${variant.name} ${entry.format} rejects an oversized Content-Length before reading the body`, async () => {
        const providerUtils = await entry.load()
        const state = { cancelled: false }
        const response = new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(new TextEncoder().encode("{}"))
            },
            cancel() {
              state.cancelled = true
            },
          }),
          {
            headers: {
              "content-length": String(limit + 1),
            },
          },
        )
        const handler = providerUtils.createJsonResponseHandler(z.object({}))

        expect(readdirSync(variant.root).some((file) => file.startsWith(".bun-tag-"))).toBe(true)
        await expect(
          handler({
            url: "https://example.test/oversized",
            requestBodyValues: {},
            response,
          }),
        ).rejects.toThrow(`exceeded maximum size of ${limit} bytes`)
        expect(state.cancelled).toBe(true)
      })

      test(`${variant.name} ${entry.format} cancels a chunked response when its streamed body crosses the limit`, async () => {
        const providerUtils = await entry.load()
        const state = { cancelled: false, chunks: 0 }
        const chunk = new Uint8Array(1024 * 1024)
        const response = new Response(
          new ReadableStream<Uint8Array>({
            pull(controller) {
              state.chunks += 1
              controller.enqueue(chunk)
            },
            cancel() {
              state.cancelled = true
            },
          }),
          {
            status: 500,
            statusText: "Internal Server Error",
          },
        )
        const handler = providerUtils.createJsonErrorResponseHandler({
          errorSchema: z.object({ error: z.string() }),
          errorToMessage: (error) => error.error,
        })

        await expect(
          handler({
            url: "https://example.test/chunked",
            requestBodyValues: {},
            response,
          }),
        ).rejects.toThrow(`exceeded maximum size of ${limit} bytes`)
        expect(state.chunks).toBe(65)
        expect(state.cancelled).toBe(true)
      })
    }
  }
})
