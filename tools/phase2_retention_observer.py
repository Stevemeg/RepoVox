"""Read-only observation; guest administrators remain a trusted boundary."""

import hashlib
import json
import os
import stat
import time
from pathlib import Path


def process_snapshot(container):
    """Observe the exact inspected synthetic process without consuming its CPU quota."""
    if os.name != "posix" or not container["Name"].startswith("/synthetic-watchdog-"):
        raise ValueError("synthetic_process_required")
    cid, pid = container["Id"], container["State"]["Pid"]
    if not container["State"]["Running"] or pid <= 0:
        raise ValueError("watchdog_unavailable")
    proc = Path("/proc") / str(pid)
    if cid not in (proc / "cgroup").read_text():
        raise ValueError("process_container_binding")
    initial = (proc / "stat").read_text().rpartition(") ")[2].split()[19]
    fields = dict(
        line.split(":", 1) for line in (proc / "status").read_text().splitlines() if ":" in line
    )
    root = proc / "root"
    script = root / "opt/rv-retention/watchdog.py"
    info = script.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("script_type")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("heartbeat_duplicate_key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("heartbeat_nonfinite")

    try:
        heartbeat = json.loads(
            (root / "status/heartbeat.json").read_bytes(),
            object_pairs_hook=pairs,
            parse_constant=invalid,
        )
    except FileNotFoundError:
        heartbeat = None
    process = dict(
        cmdline=[s.decode() for s in (proc / "cmdline").read_bytes().split(b"\0") if s],
        uid=list(map(int, fields["Uid"].split())),
        gid=list(map(int, fields["Gid"].split())),
        groups=list(map(int, fields["Groups"].split())),
        state=fields["State"].split()[0],
        caps={k: fields[k].strip() for k in ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"]},
        no_new_privs=int(fields["NoNewPrivs"]),
        start_monotonic_ns=int(initial) * 1_000_000_000 // os.sysconf("SC_CLK_TCK"),
    )
    if (proc / "stat").read_text().rpartition(") ")[2].split()[19] != initial:
        raise ValueError("watchdog_process_changed")
    return dict(
        heartbeat=heartbeat,
        process=process,
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        script_owner=[info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)],
        monotonic_ns=time.monotonic_ns(),
    )


COLLECT = r"""
import hashlib,json,os,stat,time
from pathlib import Path
s=dict(line.split(':',1) for line in Path('/proc/1/status').read_text().splitlines() if ':' in line)
ticks=int(Path('/proc/1/stat').read_text().rpartition(') ')[2].split()[19])
path=Path('/opt/rv-retention/watchdog.py')
info=path.lstat()
if not stat.S_ISREG(info.st_mode):raise ValueError('script_type')
def strict_pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('heartbeat_duplicate_key')
        result[key]=value
    return result
def invalid_constant(value):raise ValueError('heartbeat_nonfinite')
try:
    heartbeat=json.loads(Path('/status/heartbeat.json').read_bytes(),object_pairs_hook=strict_pairs,parse_constant=invalid_constant)
except FileNotFoundError:
    heartbeat=None
process=dict(cmdline=[x.decode() for x in Path('/proc/1/cmdline').read_bytes().split(b'\0') if x],
    uid=list(map(int,s['Uid'].split())),gid=list(map(int,s['Gid'].split())),groups=list(map(int,s['Groups'].split())),
    state=s['State'].strip().split()[0],
    caps={k:s[k].strip() for k in ['CapInh','CapPrm','CapEff','CapBnd','CapAmb']},
    no_new_privs=int(s['NoNewPrivs']),start_monotonic_ns=ticks*1_000_000_000//os.sysconf('SC_CLK_TCK'))
print(json.dumps(dict(heartbeat=heartbeat,process=process,script_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    script_owner=[info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode)],monotonic_ns=time.monotonic_ns())))
"""
