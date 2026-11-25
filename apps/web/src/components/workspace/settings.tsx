"use client";
import { Info } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { authLabel, useWorkspace } from "./context";

const enabled = (on: boolean) => (on ? "Enabled" : "Not enabled in this environment");

export function SettingsView() {
  const { account } = useWorkspace();
  const github = account.auth_provider === "github";
  return (
    <>
      <PageHeader
        eyebrow="Account"
        title="Settings"
        description="Your account and what this environment offers."
      />
      <section className="panel" aria-labelledby="settings-account">
        <div className="panel-header">
          <h2 id="settings-account">Account</h2>
        </div>
        <div className="panel-body">
          <dl className="definition-list">
            <dt>Name</dt>
            <dd>{account.display_name}</dd>
            <dt>Email</dt>
            <dd>{account.email}</dd>
            <dt>Sign-in method</dt>
            <dd>{authLabel(account)}</dd>
          </dl>
        </div>
      </section>
      <section className="panel" aria-labelledby="settings-environment">
        <div className="panel-header">
          <h2 id="settings-environment">Environment</h2>
          <span className="env-badge">{account.environment}</span>
        </div>
        <div className="panel-body">
          <dl className="definition-list">
            <dt>Environment</dt>
            <dd>{account.environment}</dd>
            <dt>Repository analysis</dt>
            <dd>{enabled(account.analysis_enabled)}</dd>
            <dt>Narrated videos</dt>
            <dd>{enabled(account.video_enabled)}</dd>
            <dt>Synthetic fixtures</dt>
            <dd>{enabled(account.fixtures_enabled)}</dd>
          </dl>
        </div>
      </section>
      <div className="notice" data-tone="neutral">
        <Info size={16} aria-hidden="true" />
        <p>
          {github
            ? "You signed in with GitHub. RepoVox reads only your public GitHub profile to confirm your account, does not store your GitHub access token, and admits only accounts an administrator has approved."
            : "You are using a seeded development identity. Development identities exist only in development and test environments; they have no password and are not production accounts."}
        </p>
      </div>
    </>
  );
}
