"use client";
import { useId } from "react";
import { describeProvenance, scenes, type Provenance } from "@/lib/narration";
import type { NarrationView } from "@/lib/story-types";
import type { Video } from "@/lib/types";

/*
 * How the active video's narration was worded and voiced, from its recorded provenance only
 * (frontend handoff section 3, rule 5). There is deliberately no unconditional sentence: a
 * deterministic record says the template wording was used, a model record names the provider
 * and model with its scene counts, and a missing record says so.
 */

function Wording({ provenance }: { provenance: Provenance }) {
  const wording = provenance.wording;
  if (!wording) return <p>How this narration was worded was not recorded.</p>;
  if (wording.kind === "explainer")
    return (
      <p data-wording="explainer">
        Not worded by a language model: RepoVox never uses a model to word architecture
        explainers.
      </p>
    );
  if (wording.kind === "template")
    return (
      <p data-wording="template">
        Deterministic template narration (<code>{wording.refiner}</code>). No language model wrote
        or reworded it: {wording.scenesTotal > 0 ? `all ${scenes(wording.scenesTotal)}` : "every scene"}{" "}
        {wording.scenesTotal === 1 ? "uses" : "use"} RepoVox&apos;s template wording.
      </p>
    );
  const kept = wording.scenesTotal - wording.scenesRefined;
  return (
    <div data-wording="model">
      <p>
        A language model reworded this narration: model{" "}
        <code>{wording.model ?? "not recorded"}</code> through {wording.providerLabel} (provider{" "}
        <code>{wording.provider}</code>, refiner <code>{wording.refiner}</code>).
      </p>
      <p data-scenes-refined={wording.scenesRefined} data-scenes-total={wording.scenesTotal}>
        {wording.scenesRefined} of {scenes(wording.scenesTotal)} use the model&apos;s wording, each
        checked against its source citations.{" "}
        {kept > 0
          ? `The other ${scenes(kept)} kept the deterministic template wording${wording.scenesFallback !== kept ? ` (${wording.scenesFallback} recorded as fallback)` : ""}.`
          : "No scene kept the template wording."}
      </p>
      {wording.fallbackReason && (
        <p data-fallback-reason={wording.fallbackReason}>
          No model wording was used at all (reason <code>{wording.fallbackReason}</code>), so every
          scene kept the template wording.
        </p>
      )}
      {wording.rejections.length > 0 && (
        <div>
          <p>Model wording rejected by the grounding check, by scene:</p>
          <ul className="bullet-list" aria-label="Rejected scenes">
            {wording.rejections.map((entry) => (
              <li key={entry.scene} data-scene={entry.scene}>
                <code>{entry.scene}</code>:{" "}
                {entry.reasons.map((reason, index) => (
                  <span key={reason}>
                    {index > 0 && ", "}
                    <code>{reason}</code>
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </div>
      )}
      {wording.hosted ? (
        <p className="field-hint">
          This is a hosted third-party service that the operator configured. RepoVox sends it the
          verified narration blueprint (cited claim text), never repository files.
        </p>
      ) : (
        <p className="field-hint">Ollama is a self-hosted model server run by the operator.</p>
      )}
    </div>
  );
}

function Voice({ provenance }: { provenance: Provenance }) {
  const voice = provenance.voice;
  if (!voice) return <p>Which voice spoke was not recorded.</p>;
  return (
    <div data-voice={voice.provider ?? "unrecorded"}>
      <p>{voice.description}</p>
      {voice.recorded && (
        <p className="provenance-codes">
          Provider <code>{voice.provider ?? "not recorded"}</code> · engine{" "}
          <code>{voice.engine ?? "not recorded"}</code> · voice{" "}
          <code>{voice.voice ?? "not recorded"}</code>
        </p>
      )}
    </div>
  );
}

export function NarrationPanel({
  video,
  storyNarration,
}: {
  video: Video;
  /** The story API's narration record for the same video, used only as a fallback. */
  storyNarration?: NarrationView | null;
}) {
  const titleId = useId();
  const provenance = describeProvenance(video.category, video.metadata?.narration, storyNarration);
  return (
    <section className="provenance" aria-labelledby={titleId} data-recorded={provenance.recorded}>
      <h4 id={titleId}>Narration and voice</h4>
      {provenance.recorded ? (
        <dl className="definition-list">
          <dt>Wording</dt>
          <dd>
            <Wording provenance={provenance} />
          </dd>
          <dt>Voice</dt>
          <dd>
            <Voice provenance={provenance} />
          </dd>
        </dl>
      ) : (
        <p data-provenance="unrecorded">
          Narration provenance was not recorded for this video, so RepoVox does not say how it was
          worded or voiced.
        </p>
      )}
    </section>
  );
}
