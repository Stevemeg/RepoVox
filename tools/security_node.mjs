// Inspect the actual process and effective trust store; never changes trust.
import { X509Certificate, createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import * as tls from "node:tls";

export const expectedVersion = "v24.22.1";
export const blockedRoots = new Set([
  "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",
  "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",
]);
const trustOverrides = [
  "NODE_EXTRA_CA_CERTS", "NODE_USE_SYSTEM_CA", "NODE_OPTIONS",
  "NODE_TLS_REJECT_UNAUTHORIZED", "SSL_CERT_FILE", "SSL_CERT_DIR",
];
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

export function certificateInventory(pems) {
  return pems.map((pem) => {
    const cert = new X509Certificate(pem);
    return { subject: cert.subject, sha256: sha256(cert.raw) };
  }).sort((a, b) => a.sha256.localeCompare(b.sha256));
}

export function validateInventory(report) {
  if (report.version !== expectedVersion) throw new Error("Unexpected Node version");
  if (Object.keys(report.trustOverrides).length || report.execArgv.length)
    throw new Error("Unapproved Node trust or startup override");
  for (const name of ["bundled", "effective"]) {
    if (!report[name].length) throw new Error("Empty CA inventory");
    if (report[name].some((cert) => blockedRoots.has(cert.sha256)))
      throw new Error("Blocked certificate authority");
  }
  const ids = (certs) => [...new Set(certs.map((c) => c.sha256))].sort();
  if (JSON.stringify(ids(report.bundled)) !== JSON.stringify(ids(report.effective)))
    throw new Error("Effective trust differs from bundled trust");
  return report;
}

export function inspectRuntime() {
  return validateInventory({
    version: process.version, platform: process.platform, arch: process.arch,
    executable: process.execPath, executableSha256: sha256(readFileSync(process.execPath)),
    versions: process.versions, execArgv: process.execArgv,
    trustOverrides: Object.fromEntries(trustOverrides.filter((key) => process.env[key] !== undefined)
      .map((key) => [key, "PRESENT (value withheld)"])),
    bundled: certificateInventory(tls.getCACertificates("bundled")),
    effective: certificateInventory(tls.getCACertificates("default")),
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  console.log(JSON.stringify(inspectRuntime(), null, 2));
}
