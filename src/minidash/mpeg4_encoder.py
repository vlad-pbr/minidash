import datetime
import os
from pathlib import Path
from subprocess import DEVNULL, PIPE, Popen
from threading import Thread
from typing import Any, Generator
from encoders.encoder import Encoder

DESIRED_FPS: int = 30
FRAMES_PER_KEYFRAME: int = 30
H264_CRF: int = 35


class MPEG4Encoder(Encoder):

    _encoder_cmd = [
        "ffmpeg",
        "-r", f"{DESIRED_FPS}",

        "-f", "mjpeg",
        "-i", "pipe:0",

        # "-f", "srt",
        # "-i", "dynamic_bk.srt",

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

        "-scodec", "mov_text",

        "pipe:1"
    ]

    @classmethod
    def get_content_type(cls) -> str:
        return "video/mp4"

    @classmethod
    def encode(cls, input: Generator[bytes, Any, None]) -> Generator[bytes, Any, None]:
        
        # init completion flag
        complete = False
        metafile_path = Path("dynamic.srt")

        if metafile_path.is_file():
            os.remove(metafile_path)

        with metafile_path.open("w") as metafile:

            def _format_ts(ts: datetime.timedelta) -> str:
                return f"0{ts}"[:-3].replace(".", ",")

            # run encoder process
            encoder_process = Popen(
                cls._encoder_cmd,
                stdin=PIPE,
                stdout=PIPE,
                # stderr=DEVNULL
            )

            def _feed():
                sub_id = 1
                buffer = datetime.timedelta(seconds=0)
                start = datetime.datetime.now()

                for frame in input:

                    # feed new frame while completion flag is not set
                    if not complete:

                        ts_start = datetime.datetime.now() + buffer - start
                        ts_end = ts_start + datetime.timedelta(seconds=1 / DESIRED_FPS)
                        metafile.write(f"{sub_id}\n{_format_ts(ts_start)} --> {_format_ts(ts_end)}\n{sub_id}\n\n")
                        metafile.flush()
                        sub_id += 1

                        encoder_process.stdin.write(frame)

                    # completion is set - iterating thread must close the interator
                    else:
                        input.close()
                        return

            Thread(target=_feed).start()

            # yield encoded frames until generator is closed
            try:

                while True:
                    atom_size_bytes, atom_type = encoder_process.stdout.read(4), encoder_process.stdout.read(4)
                    atom_size = int.from_bytes(atom_size_bytes, byteorder="big") - 8
                    atom_data = encoder_process.stdout.read(atom_size)

                while True:
                    d = os.read(encoder_process.stdout.fileno(), 999999)
                    print(len(d))
                    yield d
            except GeneratorExit:
                pass

        # cleanup
        complete = True
        encoder_process.kill()
        os.remove(metafile_path)
