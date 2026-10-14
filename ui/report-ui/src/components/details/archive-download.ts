// Modified from original source; this is an original local extension.
import JSZip from "jszip";

const MEBIBYTE = 1024 * 1024;

// Mutable only so focused browser tests can exercise limits without large fixtures.
export const archiveDownloadLimits = {
  archiveBytes: 128 * MEBIBYTE,
  memberBytes: 64 * MEBIBYTE,
  memberCount: 10_000,
  fetchTimeoutMs: 60_000,
};

export interface ArchiveMember {
  url: string;
  member: string;
}

export function archiveMember(href: string): ArchiveMember | undefined {
  const marker = href.indexOf("#zip-member=");
  if (marker < 0) return undefined;
  try {
    const member = decodeURIComponent(href.slice(marker + 12));
    if (!member || member.includes("\\") || member.includes(":"))
      return undefined;
    if (member.startsWith("/") || member.split("/").includes(".."))
      return undefined;
    return { url: href.slice(0, marker), member };
  } catch {
    return undefined;
  }
}

// Retain only the two most recently used archives, including in-flight fetches.
const archives = new Map<string, Promise<JSZip>>();

function formatBytes(bytes: number): string {
  return bytes % MEBIBYTE === 0 ? `${bytes / MEBIBYTE} MiB` : `${bytes} B`;
}

function archiveLimitError(): Error {
  return new Error(
    `Archive download exceeds the ${formatBytes(archiveDownloadLimits.archiveBytes)} limit.`,
  );
}

async function cancelResponseBody(response: Response): Promise<void> {
  try {
    await response.body?.cancel();
  } catch {
    // The body may already be locked or aborted by fetch.
  }
}

function concatenateChunks(chunks: Uint8Array[], length: number): ArrayBuffer {
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes.buffer as ArrayBuffer;
}

async function readArchiveBody(response: Response): Promise<ArrayBuffer> {
  const body = response.body;
  if (!body) return new ArrayBuffer(0);

  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  let completed = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        completed = true;
        return concatenateChunks(chunks, length);
      }
      if (value.byteLength > archiveDownloadLimits.archiveBytes - length) {
        throw archiveLimitError();
      }
      chunks.push(value);
      length += value.byteLength;
    }
  } finally {
    if (!completed) {
      try {
        await reader.cancel();
      } catch {
        // A failed network stream may already have been cancelled by fetch.
      }
    }
    reader.releaseLock();
  }
}

async function fetchArchiveBytes(url: string): Promise<ArrayBuffer> {
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, archiveDownloadLimits.fetchTimeoutMs);

  try {
    const response = await fetch(url, {
      credentials: "include",
      signal: controller.signal,
    });
    if (!response.ok) {
      await cancelResponseBody(response);
      throw new Error(`Archive download failed (${response.status}).`);
    }
    const contentLength = Number(response.headers.get("content-length"));
    if (
      Number.isSafeInteger(contentLength) &&
      contentLength > archiveDownloadLimits.archiveBytes
    ) {
      await cancelResponseBody(response);
      throw archiveLimitError();
    }
    return await readArchiveBody(response);
  } catch (error) {
    if (timedOut) {
      throw new Error(
        `Archive download timed out after ${archiveDownloadLimits.fetchTimeoutMs} ms.`,
      );
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function loadArchive(url: string): Promise<JSZip> {
  let archive = archives.get(url);
  if (archive) {
    archives.delete(url);
    archives.set(url, archive);
    return archive;
  }
  archive = (async () => {
    const zip = await JSZip.loadAsync(await fetchArchiveBytes(url));
    if (Object.keys(zip.files).length > archiveDownloadLimits.memberCount) {
      throw new Error(
        `Archive contains more than ${archiveDownloadLimits.memberCount.toLocaleString("en-US")} members.`,
      );
    }
    return zip;
  })();
  archives.set(url, archive);
  if (archives.size > 2) archives.delete(archives.keys().next().value!);
  // A failed fetch must not poison subsequent retries or evict a newer request.
  void archive.catch(() => {
    if (archives.get(url) === archive) archives.delete(url);
  });
  return archive;
}

interface BoundedZipStream {
  on(event: "data", callback: (chunk: Uint8Array) => void): this;
  on(event: "error", callback: (error: Error) => void): this;
  on(event: "end", callback: () => void): this;
  pause(): this;
  resume(): this;
}

interface StreamableZipFile {
  internalStream(type: "uint8array"): BoundedZipStream;
}

function extractBoundedMember(file: JSZip.JSZipObject): Promise<ArrayBuffer> {
  const maximum = archiveDownloadLimits.memberBytes;
  return new Promise((resolve, reject) => {
    // JSZip's runtime public stream API is absent from its bundled type declaration.
    const stream = (file as unknown as StreamableZipFile).internalStream(
      "uint8array",
    );
    const chunks: Uint8Array[] = [];
    let length = 0;
    let finished = false;

    const fail = (error: Error) => {
      if (finished) return;
      finished = true;
      stream.pause();
      chunks.length = 0;
      reject(error);
    };

    stream
      .on("data", (chunk) => {
        if (finished) return;
        if (chunk.byteLength > maximum - length) {
          fail(
            new Error(
              `Requested file exceeds the ${formatBytes(maximum)} limit.`,
            ),
          );
          return;
        }
        chunks.push(chunk);
        length += chunk.byteLength;
      })
      .on("error", fail)
      .on("end", () => {
        if (finished) return;
        finished = true;
        resolve(concatenateChunks(chunks, length));
      });
    stream.resume();
  });
}

export async function extractMember(
  reference: ArchiveMember,
): Promise<ArrayBuffer> {
  const archive = await loadArchive(reference.url);
  const file = archive.file(reference.member);
  if (!file || file.dir)
    throw new Error("The requested file is missing from the archive.");
  return extractBoundedMember(file);
}

export async function downloadMember(reference: ArchiveMember): Promise<void> {
  const bytes = await extractMember(reference);
  const url = URL.createObjectURL(
    new Blob([bytes], { type: "application/octet-stream" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = reference.member.split("/").pop()!;
  document.body.append(link);
  link.click();
  link.remove();
  // Let the browser begin consuming the Blob before releasing it.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
