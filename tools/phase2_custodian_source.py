"""Read-only source view of already registered custody bytes. No scratch or exports.

The unchanged v2 validators use a small Path read interface. This adapter maps each
approved original path to its existing content-addressed custody file. It supplies
real filesystem metadata and reads through Lifecycle authorization/integrity checks;
it never invents stat results, bypasses source hashing, or writes reconstructed files.
"""

import io
import resource

from repovox.evaluation.v2 import Scope, decode

from tools.phase2_custodian_lifecycle import digest, identity, require


def protect_memory():
    identity()
    # Protected RAM must not be exported into an unmanaged process core file.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


class CustodySource:
    def __init__(self, lifecycle, token, scope_body, scope_sha256):
        protect_memory()
        self.life, self.token = lifecycle, token
        self.scope = decode(scope_body, scope_sha256, Scope)
        require(self.scope.tenant_id == lifecycle.plan["tenant"], "source_tenant_binding")
        self.tenant = self.scope.tenant_id
        require(
            lifecycle.read(token, self.tenant + "-" + scope_sha256) == scope_body,
            "registered_scope_required",
        )
        self.files = {file.path: file for file in self.scope.files}

    def __truediv__(self, path):
        require(isinstance(path, str) and path in self.files, "source_path_outside_scope")
        return _CustodyFile(self, self.files[path])

    def is_symlink(self):
        return self.life.data.is_symlink()

    def resolve(self):
        return self.life.data.resolve()


class _CustodyFile:
    def __init__(self, source, file):
        self.source, self.file = source, file
        self.name = source.tenant + "-" + file.file_sha256
        self.path = source.life.data / self.name

    @property
    def parents(self):
        return self.path.parents

    def is_symlink(self):
        return self.path.is_symlink()

    def resolve(self):
        return self.path.resolve()

    def _read(self):
        body = self.source.life.read(self.source.token, self.name)
        require(
            len(body) == self.file.size and digest(body) == self.file.file_sha256,
            "registered_source_hash_mismatch",
        )
        return body

    def stat(self):
        self._read()  # Actual current authority, owner/mode/link/hash and inventory.
        return self.path.lstat()  # Real metadata, never a fabricated regular-file stat.

    def open(self, mode):
        require(mode == "rb", "custody_source_read_only")
        # Lifecycle closes its checked descriptor. The validator sees identical
        # original bytes in RAM; no fd-backed export, directory or temporary file.
        return io.BufferedReader(io.BytesIO(self._read()))
