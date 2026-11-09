# -*- coding: utf-8 -*-
"""Unpack a job (injob/in/**.bin are XOR 0xA7) into the work dir and run one of its commands there.

    python runner/stage.py part  injob /tmp/w     runs job.json "cmd"   (env SHARD, SHARDS, WORKERS, FARM)
    python runner/stage.py merge injob /tmp/w     runs job.json "merge" (if any) after the parts are in /tmp/w/out

Whatever the command leaves in /tmp/w/out is the result.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

T = bytes(i ^ 0xA7 for i in range(256))
mode, src, work = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
cfg = json.loads((src / 'job.json').read_text(encoding='utf-8'))
t0 = time.time()
n = 0
for f in (src / 'in').rglob('*'):
    if f.is_file():
        rel = f.relative_to(src / 'in').as_posix()
        dst = work / (rel[:-4] if rel.endswith('.bin') else rel)
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(f.read_bytes().translate(T))
        n += 1
(work / 'out').mkdir(parents=True, exist_ok=True)
print('unpacked %d files in %.0fs' % (n, time.time() - t0), flush=True)
cmd = cfg.get('cmd' if mode == 'part' else 'merge')
if not cmd:
    sys.exit(0)
env = dict(os.environ, PYTHONIOENCODING='utf-8', WORKERS=str(cfg.get('workers', 3)))
env.setdefault('SHARD', '0')
env.setdefault('SHARDS', '1')
print('$', cmd, flush=True)
t1 = time.time()
r = subprocess.run(cmd, cwd=work, shell=True, env=env)
print('%s exit %d  minutes %.1f' % (mode, r.returncode, (time.time() - t1) / 60), flush=True)
sys.exit(r.returncode)
