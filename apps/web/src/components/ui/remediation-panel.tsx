import { useId } from "react";
import { LifeBuoy } from "lucide-react";
import { remediationFor, type RemediationContext } from "@/lib/remediation";

/**
 * What a person can do next about a stopped job or a refused request. Renders nothing for
 * codes without guidance. Everything shown comes from `lib/remediation.ts` and the fixed
 * code; no repository detail is passed in, so none can be shown.
 *
 * `compact` omits the explanation, for use under a `ProblemNotice` that already said what
 * happened.
 */
export function RemediationPanel({
  code,
  context = "job",
  compact = false,
}: {
  code: string | null | undefined;
  context?: RemediationContext;
  compact?: boolean;
}) {
  const titleId = useId();
  const guidance = remediationFor(code, context);
  if (!guidance) return null;
  return (
    <section className="remediation" aria-labelledby={titleId} data-code={guidance.code}>
      <div className="remediation-header">
        <LifeBuoy size={18} aria-hidden="true" />
        <h3 id={titleId}>{guidance.title}</h3>
      </div>
      {!compact && <p>{guidance.explanation}</p>}
      {guidance.withheld && (
        <p className="remediation-withheld">
          <strong>Not shown on purpose. </strong>
          {guidance.withheld}
        </p>
      )}
      <div>
        <h4 className="remediation-subtitle">What you can do</h4>
        <ol className="remediation-steps">
          {guidance.steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </div>
      {guidance.policy && (
        <details className="disclosure remediation-policy" open={!compact}>
          <summary>{guidance.policy.heading}</summary>
          <ul className="bullet-list">
            {guidance.policy.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </details>
      )}
      {guidance.retry && <p className="field-hint">{guidance.retry}</p>}
    </section>
  );
}
