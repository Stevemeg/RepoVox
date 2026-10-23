import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { blockedRoots, certificateInventory, expectedVersion, validateInventory } from "./security_node.mjs";
import { rootCertificates } from "node:tls";

// Unit mutations are synthetic; the separate CLI always inspects the real process.
const fixture = () => ({ version: expectedVersion, trustOverrides: {}, execArgv: [],
  bundled: [{ sha256: "synthetic" }], effective: [{ sha256: "synthetic" }] });
test("valid policy and actual X509 decoding", () => {
  assert.equal(validateInventory(fixture()).version, expectedVersion);
  const actual = certificateInventory(rootCertificates);
  assert.ok(actual.length > 100);
  assert.ok(actual.every((cert) => /^[a-f0-9]{64}$/.test(cert.sha256)));
  assert.throws(() => certificateInventory(["not a certificate"]));
});
test("old executable rejected", () => {
  assert.throws(() => validateInventory({ ...fixture(), version: "v24.18.0" }), /version/);
});
for (const fingerprint of blockedRoots) {
  test(`blocked anchor ${fingerprint} rejected in either inventory`, () => {
    for (const field of ["bundled", "effective"]) {
      assert.throws(() => validateInventory({ ...fixture(), [field]: [{ sha256: fingerprint }] }), /Blocked/);
    }
  });
}
test("empty or added effective CA rejected", () => {
  assert.throws(() => validateInventory({ ...fixture(), bundled: [] }), /Empty/);
  assert.throws(() => validateInventory({ ...fixture(), effective: [{ sha256: "other" }] }), /differs/);
});
test("override and alternate startup flags rejected", () => {
  assert.throws(() => validateInventory({ ...fixture(), trustOverrides: { NODE_OPTIONS: "present" } }), /override/);
  assert.throws(() => validateInventory({ ...fixture(), execArgv: ["--use-openssl-ca"] }), /override/);
});
test("real CLI checks cannot silently accept injected environment", () => {
  const script = fileURLToPath(new URL("./security_node.mjs", import.meta.url));
  const valid = spawnSync(process.execPath, [script], { encoding: "utf8" });
  assert.equal(valid.status, 0, valid.stderr);
  const report = JSON.parse(valid.stdout);
  assert.equal(report.version, expectedVersion);
  assert.ok(report.bundled.every((cert) => !blockedRoots.has(cert.sha256)));
  for (const [name, value] of Object.entries({
    NODE_TLS_REJECT_UNAUTHORIZED: "0", NODE_USE_SYSTEM_CA: "0",
    SSL_CERT_FILE: "nonexistent.pem", SSL_CERT_DIR: "nonexistent",
    NODE_EXTRA_CA_CERTS: "nonexistent.pem", NODE_OPTIONS: "--use-system-ca",
  })) {
    const denied = spawnSync(process.execPath, [script], { encoding: "utf8", env: { ...process.env, [name]: value } });
    assert.notEqual(denied.status, 0);
    assert.match(denied.stderr, /Unapproved/);
  }
});
