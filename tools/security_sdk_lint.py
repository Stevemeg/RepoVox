"""Run trusted cfn-lint under an irreversible Python socket-audit refusal.

This is a static-tool restriction, not a sandbox for hostile native/Python code.
Installing dependencies happens in a separate process with normal verified TLS.
"""

import importlib.metadata
import sys

from security_sdk_check import approved_trust, refuse_network

if __name__ == "__main__":
    sys.addaudithook(refuse_network)
    approved_trust()
    # Use the installed distribution's exact console entry point, not shell/code input.
    entries = importlib.metadata.distribution("cfn-lint").entry_points
    entry = next(x for x in entries if x.group == "console_scripts" and x.name == "cfn-lint")
    raise SystemExit(entry.load()())
