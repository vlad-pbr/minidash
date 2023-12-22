import asyncio
import json
import os
import shutil
import time
from asyncio import subprocess
from datetime import timedelta, datetime
from pathlib import Path
from typing import AsyncIterator

import numpy as np
from PIL import Image

DESIRED_FPS: int = 30
FRAMES_PER_KEYFRAME: int = 30
H264_CRF: int = 35
_ENCODER_CMD = [
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


async def _frames(frames_dir: Path) -> AsyncIterator[tuple[np.ndarray, str, timedelta]]:

    frame_names = sorted(os.listdir(frames_dir))
    delta = timedelta(seconds=1 / DESIRED_FPS)
    start_time = datetime.now()

    while True:
        for frame_name in frame_names:
            then = timedelta(seconds=time.perf_counter())
            yield np.asarray(Image.open(frames_dir / frame_name)), frame_name, datetime.now() - start_time

            elapsed = timedelta(seconds=time.perf_counter()) - then
            if elapsed < delta:
                await asyncio.sleep((delta - elapsed).total_seconds())


async def _atoms(output: asyncio.StreamReader) -> AsyncIterator[tuple[bytes, bytes]]:
    while not output.at_eof():
        atom_size_bytes, atom_type = await output.readexactly(4), await output.readexactly(4)
        atom_size = int.from_bytes(atom_size_bytes, "big")
        atom_data = atom_size_bytes + atom_type + await output.readexactly(atom_size - 8)

        yield atom_type, atom_data


async def encode(frames_dir: Path):

    encoder_process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        *_ENCODER_CMD,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE
    )
    meta: dict[float, str] = {}

    async def _feed():
        async for frame, metadata, ts in _frames(frames_dir):
            encoder_process.stdin.write(frame.tobytes())
            meta[ts.total_seconds()] = metadata

    async def _store():

        chunks_dir = Path("./chunks")
        if chunks_dir.exists():
            shutil.rmtree(chunks_dir)
        chunks_dir.mkdir()

        atoms = _atoms(encoder_process.stdout)

        with (chunks_dir / "init.m4s").open("wb") as _init_chunk:
            for init_atom_type in (b"ftyp", b"moov"):
                atom_type, atom_data = await anext(atoms)
                assert atom_type == init_atom_type,\
                    f"received unexpected atom '{atom_type}' while expecting '{init_atom_type}"
                _init_chunk.write(atom_data)

        with (chunks_dir / "media.mp4").open("wb") as _media_chunk, (chunks_dir / "meta.txt").open("w") as _meta_chunk:
            while not encoder_process.stdout.at_eof():
                for media_atom_type in (b"moof", b"mdat"):
                    atom_type, atom_data = await anext(atoms)
                    assert atom_type == media_atom_type, \
                        f"received unexpected atom '{atom_type}' while expecting '{media_atom_type}"

                    _media_chunk.write(atom_data)

                _meta_chunk.write(json.dumps(meta))
                _meta_chunk.flush()
                meta.clear()
                _media_chunk.flush()

    async with asyncio.TaskGroup() as tg:
        tg.create_task(_feed())
        tg.create_task(_store())


if __name__ == "__main__":
    asyncio.run(encode(Path("./frames")))
