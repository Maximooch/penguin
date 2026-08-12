const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const test = require("node:test");

function box(size, name, payloadLength = Math.max(0, size - 8)) {
  const value = Buffer.alloc(8 + payloadLength);
  value.writeUInt32BE(size, 0);
  value.write(name, 4, 4, "ascii");
  return value;
}

function createIcnsFixture() {
  const value = Buffer.alloc(16);
  value.write("icns", 0, 4, "ascii");
  value.writeUInt32BE(value.length, 4);
  value.write("ic07", 8, 4, "ascii");
  value.writeUInt32BE(0, 12);
  return value;
}

function createHeifFixture() {
  const ftyp = box(16, "ftyp", 8);
  ftyp.write("heic", 8, 4, "ascii");
  const meta = box(12, "meta", 4);
  const iprp = box(8, "iprp");
  const ipco = box(32, "ipco", 24);
  ipco.write("ispe", 12, 4, "ascii");
  ipco.writeUInt32BE(1, 20);
  ipco.writeUInt32BE(1, 24);
  return Buffer.concat([ftyp, meta, iprp, ipco]);
}

function createJxlFixture() {
  const signature = box(8, "JXL ");
  const ftyp = box(12, "ftyp", 4);
  ftyp.write("jxl ", 8, 4, "ascii");
  const partialStream = box(0, "jxlp");
  return Buffer.concat([signature, ftyp, partialStream]);
}

const fixtures = [
  createIcnsFixture(),
  createHeifFixture(),
  createJxlFixture(),
].map((value) => value.toString("base64"));

const fixtureSource = JSON.stringify(fixtures);
const projectDirectory = path.resolve(__dirname, "..");

function assertChildTerminates(arguments_) {
  const result = spawnSync(process.execPath, arguments_, {
    cwd: projectDirectory,
    encoding: "utf8",
    timeout: 5_000,
  });
  const diagnostic = [result.error, result.stderr, result.stdout]
    .filter(Boolean)
    .join("\n");
  assert.equal(result.error, undefined, diagnostic);
  assert.equal(result.status, 0, diagnostic);
}

test("patched CommonJS buffer entrypoint terminates for zero-sized boxes", () => {
  assertChildTerminates([
    "-e",
    `
      const { imageSize } = require("image-size");
      const fixtures = ${fixtureSource};
      for (const fixture of fixtures) {
        try { imageSize(Buffer.from(fixture, "base64")); } catch {}
      }
    `,
  ]);
});

test("patched ESM buffer entrypoint terminates for zero-sized boxes", () => {
  assertChildTerminates([
    "--input-type=module",
    "-e",
    `
      import { imageSize } from "image-size";
      const fixtures = ${fixtureSource};
      for (const fixture of fixtures) {
        try { imageSize(Buffer.from(fixture, "base64")); } catch {}
      }
    `,
  ]);
});

test("patched CommonJS file entrypoint terminates for zero-sized boxes", () => {
  assertChildTerminates([
    "-e",
    `
      const fs = require("node:fs");
      const os = require("node:os");
      const path = require("node:path");
      const { imageSizeFromFile } = require("image-size/fromFile");
      const fixtures = ${fixtureSource};
      const directory = fs.mkdtempSync(path.join(os.tmpdir(), "image-size-test-"));
      (async () => {
        try {
          for (const [index, fixture] of fixtures.entries()) {
            const filename = path.join(directory, String(index));
            fs.writeFileSync(filename, Buffer.from(fixture, "base64"));
            try { await imageSizeFromFile(filename); } catch {}
          }
        } finally {
          fs.rmSync(directory, { recursive: true, force: true });
        }
      })().catch((error) => { console.error(error); process.exitCode = 1; });
    `,
  ]);
});

test("patched ESM file entrypoint terminates for zero-sized boxes", () => {
  assertChildTerminates([
    "--input-type=module",
    "-e",
    `
      import fs from "node:fs";
      import os from "node:os";
      import path from "node:path";
      import { imageSizeFromFile } from "image-size/fromFile";
      const fixtures = ${fixtureSource};
      const directory = fs.mkdtempSync(path.join(os.tmpdir(), "image-size-test-"));
      try {
        for (const [index, fixture] of fixtures.entries()) {
          const filename = path.join(directory, String(index));
          fs.writeFileSync(filename, Buffer.from(fixture, "base64"));
          try { await imageSizeFromFile(filename); } catch {}
        }
      } finally {
        fs.rmSync(directory, { recursive: true, force: true });
      }
    `,
  ]);
});
