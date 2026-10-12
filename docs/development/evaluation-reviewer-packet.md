# Independent human reviewer appointment packet

Version `reviewer-appointment-1.0`, 2026-10-12. Appointment: **PENDING OWNER APPOINTMENT**.
[Decision register](../delivery/phase2b-decisions.md) · [Handbook](evaluation-authoring.md) · [Checklist](evaluation-review-checklist.md) · [Rights](../ai/evaluation-rights.md).

Owner appoints a real human with Python and JS/TS source-reading skills, static import/
symbol/entrypoint/graph literacy, security/uncertainty awareness and ability to inspect
pinned original bytes and exact ranges. The reviewer must be distinct from the preparer
of each relevant label and must not have authored later training labels. Disclose
employment, financial interests, source authorship, label preparation and model work;
recuse affected labels or assign another qualified independent reviewer. Codex and
ChatGPT cannot occupy this human role. Reviewing data requires no Git commits.

The appointment records a private stable reviewer ID, actual-human confirmation,
skills/scope, conflicts and recusal plan, owner appointment evidence, approved rights
access and acceptance of confidentiality/retention restrictions. Do not publish personal
details, signatures or fabricated timestamps. Authenticate the individual and approvals
through the owner/custodian; a schema enum and an evidence hash cannot authenticate a
human. Technical validation by ChatGPT remains a separate gate.

Reviewer receives read-only scoped source and preparer annotations through the protected
review channel, without analyzer/model verdicts as an answer key. Review every family,
every claimed fact/edge and adversarial expectation, including negative citations,
scope completeness, documentation conflicts and unsupported behavior. Use blinded
base/candidate order only in later authorized scoring. Never run submitted code.

Workflow: independently inspect original source, check each row, write approve/dispute/
unresolved plus source-based reasoning, then compare with the preparer. Record every
disagreement and correction in immutable adjudication evidence. Unresolved decisions
block family approval. Owner resolves logistical disputes; substantive source disputes
need recorded reviewer agreement or a separately appointed qualified adjudicator, never
owner approval in place of independent technical review. Any corrected label creates a
new digest and needs re-review; prior receipts remain in lineage and become superseded.

Final approval is a private `gold-review-receipt-1.0` with complete claim/edge ID lists,
family annotation digest, preparer/reviewer IDs, explicit original-source review,
approval and zero unresolved disagreements. A `ReviewSeal` references the receipt hash;
the family review must reference that same hash. Human row decisions and adjudication
are retained alongside it. Custodian records authorized review access, date, scope and
authenticated approval evidence. The assistant may check these mechanically but never
issue the human decision.

Expected workload is unmeasured: 80 families, at least 600 technical claims, 120 edges,
100 adversarial variants across at least 20 held-out families, plus rights/provenance
and dispute checks. No elapsed hours are invented. Batch C first measures source/claim/
edge/variant review and adjudication time with a small approved batch, then budgets the
remaining families using observed complexity slices and uncertainty. Agree availability,
compensation if any, access window and review budget before Batch C; no payment or paid
infrastructure is authorized by this session.
