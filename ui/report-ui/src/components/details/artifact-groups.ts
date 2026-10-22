// Modified from original source; this is an original local extension.
export interface ArtifactFile {
  name: string;
  relativePath: string;
  key: string;
  url?: string;
  sizeBytes: number;
  executionId?: string;
  executionName?: string;
}

export interface ArtifactGroup {
  id: string;
  title: string;
  kind: "report" | "runner" | "server" | "crash" | "details" | "other";
  files: ArtifactFile[];
}

export function fileLabel(file: ArtifactFile): string {
  const name = file.relativePath.split("/").pop() || file.relativePath;
  if (/qdb_test_log_pid_.*\.json$/.test(name)) return "JSON log";
  if (/stderr|\.err\.txt$/.test(name)) return "stderr";
  if (/stdout|\.out\.txt$/.test(name)) return "stdout";
  if (name === "qdbd.log") return "Server log";
  const databaseLog = name.match(/(?:^|_)(LOG(?:\.old\.\d+)?)$/);
  if (databaseLog) return `RocksDB ${databaseLog[1]}`;
  if (file.relativePath.startsWith("test-metadata/"))
    return "Execution manifest";
  return name;
}

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B · empty";
  const units = ["B", "KB", "MB", "GB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), 3);
  return `${Number((bytes / 1024 ** exponent).toFixed(1))} ${units[exponent]}`;
}

export function groupArtifacts(files: ArtifactFile[]): ArtifactGroup[] {
  const groups = new Map<string, ArtifactGroup>();
  const owners = new Set(files.map((file) => file.executionId).filter(Boolean));
  for (const file of files) {
    const path = file.relativePath;
    let kind: ArtifactGroup["kind"] = "other";
    let title = "Other job artifacts";
    if (/crash|error_dump|\.dmp$/i.test(path)) {
      kind = "crash";
      title = "Crash diagnostics";
    } else if (/\.xml$/i.test(path)) {
      kind = "report";
      title = "Reports";
    } else if (path.startsWith("test-metadata/")) {
      kind = "details";
      title = "Execution details";
    } else if (/\.(?:zip|tar\.gz|tgz)$/i.test(path)) {
      kind = "other";
    } else if (
      /(?:^|\/)(?:insecure|secure|IPv4|IPv6)\//.test(path) ||
      /qdbd_log_/.test(path)
    ) {
      kind = "server";
      const security = /insecure/.test(path)
        ? "Insecure"
        : /secure/.test(path)
          ? "Secure"
          : /IPv6/.test(path)
            ? "IPv6"
            : "IPv4";
      const node = path.match(/\/(?:insecure|secure)\/log\/([^/]+)\//)?.[1];
      title = `${security}${node ? ` · Node ${node}` : " · Console"}`;
    } else if (
      file.executionId ||
      path.startsWith("test-results/") ||
      /qdb_test_log_pid_/.test(path)
    ) {
      kind = "runner";
      title = "Runner logs";
    }
    const owner = owners.size > 1 && file.executionId ? file.executionId : "";
    const id = [kind, title, owner].join(":");
    if (!groups.has(id))
      groups.set(id, {
        id,
        kind,
        title: owner ? `${file.executionName || owner} · ${title}` : title,
        files: [],
      });
    groups.get(id)!.files.push(file);
  }
  const order = ["report", "crash", "runner", "server", "details", "other"];
  return [...groups.values()].sort(
    (a, b) => order.indexOf(a.kind) - order.indexOf(b.kind),
  );
}
