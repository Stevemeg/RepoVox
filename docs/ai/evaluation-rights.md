# Evaluation rights approval procedure

Version `evaluation-rights-1.0`, 2026-10-12. [Catalog](evaluation-candidate-catalog.md) · [Evaluation plan](evaluation-plan.md) · [Protected retention](../development/evaluation-storage.md) · [Decisions](../delivery/phase2b-decisions.md).

Candidate metadata, rights review, owner approval, prepared gold, human review and
freeze eligibility are separate states. A license badge alone changes none of them.
The implementation assistant may inspect/hash evidence and record uncertainties;
the owner must approve the actual scope and obligations. Obtain legal advice where
the rights decision needs it; no legal clearance is claimed by this tooling.

1. Pin the exact repository SHA and intended source scope. Inspect root license,
   file headers, bundled/vendor dependencies, copied examples, submodules, generated
   files, notices and derivative/template ancestry. Preserve original text bytes and
   SHA-256 in the custodian provenance store. Rejected/ambiguous sources stay out.
2. Record evaluation-use basis: owner's actual rights declaration, explicit written
   permission from the rights holder, or individually reviewed license permission.
   Account ownership does not establish rights to every file. Cover source acquisition,
   private annotations, adversarial modifications, reviewer access and final evaluation.
   Customer/private code, personal data and secrets require exclusion; this prompt
   does not authorize their inclusion. Neither evaluation split is training data.
3. Record notice/attribution, modification labeling, permitted redistribution,
   reviewer confidentiality, storage jurisdiction, retention days and withdrawal
   process. Do not publish sources or gold simply because redistribution is permitted.
   Source-specific restrictions prevail over the proposed maximum retention.
4. Rights reviewer writes a scoped decision, uncertainties and checked file inventory.
   Store its hash as `rights_review_sha256`. Owner separately approves/rejects in an
   immutable evidence record (`owner_approval_sha256`). The permission evidence is
   separately hashed; `reviewer_access=permitted` is required for admission.
5. Resolve forks/revisions/copied templates to one family. Original copyright and
   third-party attribution remain in private notices; sole RepoVox Git contribution
   does not erase upstream attribution. Pin reviewer access acceptance and retention
   authorization before handing over source or labels.

MIT and BSD root notices in the shortlist warrant further scoped review, not blanket
admission. Datasette's Apache root license requires checking applicable NOTICE and
modification notices. No candidate has completed the above procedure. The catalog's
`permission_evidence_sha256`, rights-review and owner-approval fields therefore remain
null. Missing permission or reviewer access is mechanically rejected at preparation
validation and freeze. Evidence hashes establish bytes, not a rights holder's authority;
the custodian must authenticate the decisions and preserve the private audit trail.

On rights withdrawal, mark the family and every derivative/version/report invalid;
use the existing withdrawal contract. Remove live source/gold and expire backups under
the approved restriction, retain minimal suppression hashes, and create a separately
reviewed replacement version. Never shrink a denominator or recycle withdrawn labels
into training. Physical deletion and restored-backup suppression must be demonstrated.
