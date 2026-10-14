import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import JSZip from "jszip";
import {
  archiveMember,
  archiveDownloadLimits,
  extractMember,
  downloadMember,
} from "../src/components/details/archive-download.ts";

async function fixture() {
  const zip = new JSZip();
  zip.file("nested/тест #1.xml", "<testsuites>example</testsuites>", {
    compression: "DEFLATE",
  });
  zip.file("logs/server.tar.gz", new Uint8Array([0, 255, 17, 200]), {
    compression: "STORE",
  });
  return zip.generateAsync({ type: "arraybuffer" });
}

function useTinyLimits(t, values) {
  const original = { ...archiveDownloadLimits };
  Object.assign(archiveDownloadLimits, values);
  t.after(() => Object.assign(archiveDownloadLimits, original));
}

async function zipWithFiles(files) {
  const zip = new JSZip();
  for (const [name, contents] of Object.entries(files)) {
    zip.file(name, contents, { compression: "STORE", createFolders: false });
  }
  return zip.generateAsync({ type: "arraybuffer" });
}

test("vendored archive download sources retain attribution and ZIP fallback contracts", async () => {
  const [logic, component] = await Promise.all([
    readFile(
      new URL("../src/components/details/archive-download.ts", import.meta.url),
      "utf8",
    ),
    readFile(
      new URL("../src/components/details/ArchiveDownload.vue", import.meta.url),
      "utf8",
    ),
  ]);
  assert.match(logic, /^\/\/ Modified from original source/m);
  assert.match(component, /^<!-- Modified from original source/m);
  assert.match(component, /catch \(reason\)/);
  assert.match(component, /Download ZIP/);
});

test("rejects an archive whose Content-Length exceeds the configured byte limit", async (t) => {
  useTinyLimits(t, { archiveBytes: 8 });
  let cancelled = false;
  const body = new ReadableStream({
    cancel() {
      cancelled = true;
    },
  });
  t.mock.method(
    globalThis,
    "fetch",
    async () => new Response(body, { headers: { "Content-Length": "9" } }),
  );

  await assert.rejects(
    extractMember({
      url: "https://example.com/header-too-large.zip",
      member: "anything.xml",
    }),
    /archive.*8 B/i,
  );
  assert.equal(cancelled, true);
});

test("stops a streamed archive without Content-Length when it exceeds the byte limit", async (t) => {
  useTinyLimits(t, { archiveBytes: 8 });
  let cancelled = false;
  const body = new ReadableStream({
    pull(controller) {
      controller.enqueue(new Uint8Array([1, 2, 3, 4, 5]));
    },
    cancel() {
      cancelled = true;
    },
  });
  t.mock.method(globalThis, "fetch", async () => new Response(body));

  await assert.rejects(
    extractMember({
      url: "https://example.com/stream-too-large.zip",
      member: "anything.xml",
    }),
    /archive.*8 B/i,
  );
  assert.equal(cancelled, true);
});

test("rejects archives with too many members before extracting a member", async (t) => {
  useTinyLimits(t, { memberCount: 2 });
  const bytes = await zipWithFiles({ "a.xml": "a", "b.xml": "b", "c.xml": "c" });
  t.mock.method(globalThis, "fetch", async () => new Response(bytes));

  await assert.rejects(
    extractMember({
      url: "https://example.com/too-many-members.zip",
      member: "a.xml",
    }),
    /more than 2 members/i,
  );
});

test("stops member decompression when the selected member exceeds the byte limit", async (t) => {
  useTinyLimits(t, { memberBytes: 8 });
  const bytes = await zipWithFiles({ "large.xml": "0123456789" });
  t.mock.method(globalThis, "fetch", async () => new Response(bytes));

  await assert.rejects(
    extractMember({
      url: "https://example.com/member-too-large.zip",
      member: "large.xml",
    }),
    /requested file.*8 B/i,
  );
});

test("timed out archive downloads abort and can be retried", async (t) => {
  useTinyLimits(t, { fetchTimeoutMs: 10 });
  const bytes = await fixture();
  let attempts = 0;
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    if (++attempts === 1) {
      return new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    }
    return new Response(bytes);
  });
  const reference = {
    url: "https://example.com/timed-out.zip",
    member: "logs/server.tar.gz",
  };

  await assert.rejects(extractMember(reference), /timed out after 10 ms/i);
  assert.deepEqual(
    new Uint8Array(await extractMember(reference)),
    new Uint8Array([0, 255, 17, 200]),
  );
  assert.equal(attempts, 2);
});

test("archive references preserve encoded paths and reject malformed or unsafe members", () => {
  assert.deepEqual(
    archiveMember(
      "https://example.com/junit.zip#zip-member=nested%2F%D1%82%D0%B5%D1%81%D1%82%20%231.xml",
    ),
    {
      url: "https://example.com/junit.zip",
      member: "nested/тест #1.xml",
    },
  );
  for (const value of [
    "file.xml",
    "zip#zip-member=%ZZ",
    "zip#zip-member=",
    "zip#zip-member=..%2Fx",
    "zip#zip-member=%2Fx",
    "zip#zip-member=C%3A%2Fx",
    "zip#zip-member=a%5Cx",
  ]) {
    assert.equal(archiveMember(value), undefined);
  }
});

test("concurrent XML and binary downloads share one fetch and preserve exact bytes", async (t) => {
  const bytes = await fixture();
  const fetch = t.mock.method(globalThis, "fetch", async (_url, options) => {
    assert.equal(options.credentials, "include");
    return new Response(bytes);
  });
  const url = "https://example.com/concurrent.zip";
  const [xml, binary] = await Promise.all([
    extractMember({ url, member: "nested/тест #1.xml" }),
    extractMember({ url, member: "logs/server.tar.gz" }),
  ]);
  assert.equal(
    new TextDecoder().decode(xml),
    "<testsuites>example</testsuites>",
  );
  assert.deepEqual(new Uint8Array(binary), new Uint8Array([0, 255, 17, 200]));
  await extractMember({ url, member: "logs/server.tar.gz" });
  assert.equal(fetch.mock.callCount(), 1);
});

for (const failure of ["http", "network", "corrupt"]) {
  test(`failed ${failure} archive requests can be retried`, async (t) => {
    const bytes = await fixture();
    let attempts = 0;
    t.mock.method(globalThis, "fetch", async () => {
      if (++attempts === 1) {
        if (failure === "http") return new Response("denied", { status: 403 });
        if (failure === "network") throw new TypeError("Failed to fetch");
        return new Response("<html>sign in</html>");
      }
      return new Response(bytes);
    });
    const reference = {
      url: `https://example.com/${failure}.zip`,
      member: "logs/server.tar.gz",
    };
    await assert.rejects(extractMember(reference));
    assert.deepEqual(
      new Uint8Array(await extractMember(reference)),
      new Uint8Array([0, 255, 17, 200]),
    );
    assert.equal(attempts, 2);
  });
}

test("a missing member fails without discarding a valid cached archive", async (t) => {
  const bytes = await fixture();
  const fetch = t.mock.method(
    globalThis,
    "fetch",
    async () => new Response(bytes),
  );
  const url = "https://example.com/missing.zip";
  await assert.rejects(
    extractMember({ url, member: "missing.xml" }),
    /missing from the archive/,
  );
  await extractMember({ url, member: "logs/server.tar.gz" });
  assert.equal(fetch.mock.callCount(), 1);
});

test("archive cache retains only the two most recently used ZIPs", async (t) => {
  const bytes = await fixture();
  const fetched = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    fetched.push(url);
    return new Response(bytes);
  });
  for (const name of ["a", "b", "a", "c", "a", "b"]) {
    await extractMember({
      url: `https://example.com/cache-${name}.zip`,
      member: "logs/server.tar.gz",
    });
  }
  assert.deepEqual(
    fetched.map((url) => url.match(/cache-(\w)/)[1]),
    ["a", "b", "c", "b"],
  );
});

test("member download saves its original basename and releases the Blob URL", async (t) => {
  const bytes = await fixture();
  t.mock.method(globalThis, "fetch", async () => new Response(bytes));
  let blob;
  t.mock.method(URL, "createObjectURL", (value) => {
    blob = value;
    return "blob:download";
  });
  const revoke = t.mock.method(URL, "revokeObjectURL", () => {});
  const link = { click: t.mock.fn(), remove: t.mock.fn() };
  globalThis.document = {
    createElement: () => link,
    body: { append: t.mock.fn() },
  };
  t.after(() => {
    delete globalThis.document;
  });
  let cleanup;
  t.mock.method(globalThis, "setTimeout", (callback) => {
    cleanup = callback;
  });
  await downloadMember({
    url: "https://example.com/download.zip",
    member: "logs/server.tar.gz",
  });
  assert.equal(link.download, "server.tar.gz");
  assert.equal(link.href, "blob:download");
  assert.equal(link.click.mock.callCount(), 1);
  assert.equal(link.remove.mock.callCount(), 1);
  assert.deepEqual(
    new Uint8Array(await blob.arrayBuffer()),
    new Uint8Array([0, 255, 17, 200]),
  );
  cleanup();
  assert.equal(revoke.mock.calls[0].arguments[0], "blob:download");
});
