import asyncio
import os
import time
from datetime import timedelta
from pathlib import Path
from subprocess import Popen, PIPE
from typing import AsyncIterator, IO

import numpy as np
from PIL import Image

DESIRED_FPS: int = 30
FRAMES_PER_KEYFRAME: int = 30
H264_CRF: int = 35
_ENCODER_CMD = [
    "ffmpeg",
    "-r", f"{DESIRED_FPS}",

    "-f", "rawvideo",
    "-pixel_format", "rgb24",
    "-video_size", "1280x720",
    "-i", "pipe:0",

    "-g", f"{FRAMES_PER_KEYFRAME}",
    "-vf", "drawtext=text='%{localtime}':fontsize=48:fontcolor=white:box=1:boxborderw=6:boxcolor=black@0.75:x=(w-text_w)/2:y=h-text_h-20",
    "-vcodec", "libx264",
    "-tune", "zerolatency",
    "-flush_packets", "1",
    "-preset", "ultrafast",
    "-crf", f"{H264_CRF}",
    "-an",
    "-f", "mp4",
    "-movflags", "frag_keyframe+empty_moov+faststart+default_base_moof",

    "pipe:1"
]


async def frames(frames_dir: Path) -> AsyncIterator[np.ndarray]:

    frame_names = sorted(os.listdir(frames_dir))
    delta = timedelta(seconds=1 / DESIRED_FPS)

    while True:
        for frame_name in frame_names:
            then = timedelta(seconds=time.perf_counter())
            yield np.asarray(Image.open(frames_dir / frame_name))

            elapsed = timedelta(seconds=time.perf_counter()) - then
            if elapsed < delta:
                await asyncio.sleep((delta - elapsed).total_seconds())


async def atoms(output: IO) -> AsyncIterator[tuple[bytes, bytes]]:
    while output.readable():
        atom_size_bytes, atom_type = await asyncio.to_thread(output.read, 4), await asyncio.to_thread(output.read, 4)
        atom_size = int.from_bytes(atom_size_bytes, "big")
        atom_data = atom_size_bytes + atom_type + await asyncio.to_thread(output.read, atom_size - 8)

        yield atom_type, atom_data


async def encode(frames_dir: Path):

    encoder_process = Popen(
        _ENCODER_CMD,
        stdin=PIPE,
        stdout=PIPE,
    )

    async def _feed():
        async for frame in frames(frames_dir):
            encoder_process.stdin.write(frame.tobytes())

    async def _print():
        async for atom_type, _ in atoms(encoder_process.stdout):
            print(atom_type)

    async with asyncio.TaskGroup() as tg:
        tg.create_task(_feed())
        tg.create_task(_print())

if __name__ == "__main__":
    asyncio.run(encode(Path("./frames")))
