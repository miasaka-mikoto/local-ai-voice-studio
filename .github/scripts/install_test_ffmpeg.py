"""Expose the pinned test wheel's FFmpeg without changing machine settings."""
from pathlib import Path
import os
import shutil
import subprocess
import imageio_ffmpeg

source = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
if not source.is_file():
    raise RuntimeError('Pinned test FFmpeg binary missing')
target_dir = Path(os.environ['RUNNER_TEMP']) / 'voice-studio-test-ffmpeg'
target_dir.mkdir(exist_ok=True)
target = target_dir / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
shutil.copy2(source, target)
target.chmod(target.stat().st_mode | 0o111)
subprocess.run([str(target), '-version'], check=True, timeout=15)
with Path(os.environ['GITHUB_PATH']).open('a', encoding='utf-8') as output:
    output.write(str(target_dir) + '\n')
