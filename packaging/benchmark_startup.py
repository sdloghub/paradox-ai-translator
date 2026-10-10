"""Measure process-to-ready startup in the same Windows build environment."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import time


def measure(executable, repeats=3):
    samples = []
    for _ in range(repeats):
        with tempfile.TemporaryDirectory() as data:
            started = time.perf_counter()
            result = subprocess.run([str(executable), '--startup-check', '--data-dir', data],
                                    capture_output=True, text=True, encoding='utf-8', timeout=60, check=True)
            total = time.perf_counter() - started
            report = json.loads(result.stdout.strip().splitlines()[-1])
            assert not report['sdk_loaded'], 'SDK must not load at startup'
            samples.append({'process_to_exit_seconds': round(total, 4), **report})
    return {'samples': samples, 'median_seconds': round(statistics.median(row['process_to_exit_seconds'] for row in samples), 4)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--single', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('dist/startup-benchmark.json'))
    args = parser.parse_args()
    report = {'scope': 'Windows CI runner; same application; fresh empty data; process launch to ready-check exit; excludes browser rendering',
              'onefile': measure(args.single.resolve()), 'folder': measure(args.folder.resolve())}
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
