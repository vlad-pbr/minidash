import asyncio
from datetime import timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket
from starlette.responses import FileResponse

app = FastAPI()


@app.websocket("/live")
async def live(websocket: WebSocket):
    chunks_dir = Path("./chunks")
    if not (chunks_dir / "init.m4s").exists():
        await websocket.close()
    else:
        await websocket.accept()
        with (chunks_dir / "init.m4s").open("rb") as _init_file:
            await websocket.send_bytes(_init_file.read())
        with (chunks_dir / "media.mp4").open("a+b") as _media_file,\
                (chunks_dir / "meta.txt").open("a+") as _meta_file:
            while await asyncio.sleep(timedelta(seconds=0.5).total_seconds()) is None:
                data = _media_file.read()
                if data:
                    await websocket.send_text(_meta_file.read())
                    await websocket.send_bytes(data)


@app.get("/")
async def index():
    return FileResponse("./index.html")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0")
