# ADR-009: SeaweedFS for local S3 storage

Status: implemented for Phase 1, pending independent validation · Date: 2026-10-12

The approved architecture requires private S3-compatible development storage, with AWS S3 remaining a later production design. The Phase 1 instruction explicitly permits MinIO or another suitable implementation. Pulling the specified MinIO and client images failed. [MinIO upstream](https://github.com/minio/minio) is archived and documents source-only distribution. Rebuilding an archived server adds maintenance burden to the local foundation.

Use the upstream SeaweedFS image pinned to 4.17 as one local all-in-one process, with a private Docker volume and an S3 credential configuration. [Upstream S3 credentials](https://github.com/seaweedfs/seaweedfs/wiki/S3-Credentials) describes bucket-scoped identities. Separate bootstrap and runtime credentials; no anonymous identity; no storage ports exposed to the host. Python retains the S3 abstraction. Tenant checks precede object reads/deletes; a checksum and UUID identify immutable fixture objects.

Alternatives: locally build archived MinIO; introduce a larger Ceph installation; use mocks without real S3 integration coverage. SeaweedFS keeps the authorized local environment small. Test conditional writes, checksum verification, anonymous rejection and cleanup against the actual service before review. Future AWS IAM, object version deletion, signed delivery and production storage security remain later gates. Local runtime credentials can access the development bucket; they are not per-tenant IAM credentials. Revisit if compatibility tests fail.

This changes a local development implementation choice, not the approved production architecture, model strategy or fourteen-stage contract. [Phase 1 orchestration](../development/orchestration.md) and [development setup](../development/local.md) describe its boundaries.
