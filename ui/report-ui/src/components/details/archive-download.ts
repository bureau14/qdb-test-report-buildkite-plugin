import JSZip from "jszip";

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

function loadArchive(url: string): Promise<JSZip> {
  let archive = archives.get(url);
  if (archive) {
    archives.delete(url);
    archives.set(url, archive);
    return archive;
  }
  archive = (async () => {
    const response = await fetch(url, { credentials: "include" });
    if (!response.ok)
      throw new Error(`Archive download failed (${response.status}).`);
    return JSZip.loadAsync(await response.arrayBuffer());
  })();
  archives.set(url, archive);
  if (archives.size > 2) archives.delete(archives.keys().next().value!);
  // A failed fetch must not poison subsequent retries or evict a newer request.
  void archive.catch(() => {
    if (archives.get(url) === archive) archives.delete(url);
  });
  return archive;
}

export async function extractMember(
  reference: ArchiveMember,
): Promise<ArrayBuffer> {
  const archive = await loadArchive(reference.url);
  const file = archive.file(reference.member);
  if (!file || file.dir)
    throw new Error("The requested file is missing from the archive.");
  return file.async("arraybuffer");
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
