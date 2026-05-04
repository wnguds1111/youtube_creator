"""
AutoTube - FastAPI Server
웹 UI와 파이프라인을 연결하는 API 서버
"""

import os
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from pipeline import Pipeline
from credit_tracker import get_tracker

# ═══════════════════════════════════════
# 설정
# ═══════════════════════════════════════
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("autotube")

# ═══════════════════════════════════════
# FastAPI 앱
# ═══════════════════════════════════════
app = FastAPI(
    title="AutoTube",
    description="링크 하나로 유튜브 영상을 자동 생성하는 AI 파이프라인",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 (프론트엔드)
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")

app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# ═══════════════════════════════════════
# 상태 관리
# ═══════════════════════════════════════
active_jobs = {}  # job_id -> job status
websocket_connections = {}  # job_id -> WebSocket


# ═══════════════════════════════════════
# 요청 / 응답 모델
# ═══════════════════════════════════════
class CreateRequest(BaseModel):
    url: str
    language: str = "ko"
    gemini_model: str = "gemini-2.5-flash"
    tts_voice: str = "Kore"
    tts_speed: float = 1.0
    video_width: int = 1920
    video_height: int = 1080
    use_flow: bool = False
    veo_quality: str = "fast"


class JobStatus(BaseModel):
    job_id: str
    status: str
    current_step: Optional[str] = None
    steps_completed: list = []
    progress_message: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None


# ═══════════════════════════════════════
# API 엔드포인트
# ═══════════════════════════════════════

@app.get("/")
async def serve_frontend():
    """프론트엔드 HTML 제공"""
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/style.css")
async def serve_css():
    return FileResponse(os.path.join(FRONTEND_DIR, "style.css"), media_type="text/css")


@app.get("/app.js")
async def serve_js():
    return FileResponse(os.path.join(FRONTEND_DIR, "app.js"), media_type="application/javascript")


@app.post("/api/create", response_model=JobStatus)
async def create_video(request: CreateRequest):
    """영상 생성 작업을 시작합니다"""
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or gemini_key == "your_gemini_api_key_here":
        raise HTTPException(
            status_code=400,
            detail="GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요."
        )

    job_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 초기 상태
    active_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "url": request.url,
        "current_step": None,
        "steps_completed": [],
        "progress_message": "작업 대기 중...",
        "result": None,
        "error": None,
    }

    # 백그라운드에서 파이프라인 실행
    config = {
        "gemini_api_key": gemini_key,
        "gemini_model": request.gemini_model,
        "language": request.language,
        "tts_lang": request.language,
        "tts_voice": request.tts_voice,
        "tts_speed": request.tts_speed,
        "video_width": request.video_width,
        "video_height": request.video_height,
        "use_flow": request.use_flow,
        "veo_quality": request.veo_quality,
        "output_dir": OUTPUT_DIR,
    }

    asyncio.create_task(_run_pipeline(job_id, request.url, config))

    return JSONResponse(content=active_jobs[job_id])


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """작업 상태를 조회합니다"""
    if job_id not in active_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(content=active_jobs[job_id])


@app.get("/api/jobs")
async def list_jobs():
    """모든 작업 목록을 반환합니다"""
    return JSONResponse(content=list(active_jobs.values()))


@app.get("/api/credit/status")
async def credit_status():
    """현재 크레딧 사용량을 반환합니다"""
    tracker = get_tracker()
    return JSONResponse(content=tracker.get_status())

@app.get("/api/projects")
async def list_projects():
    """완료된 프로젝트 목록을 반환합니다"""
    projects = []
    if os.path.exists(OUTPUT_DIR):
        for dirname in sorted(os.listdir(OUTPUT_DIR), reverse=True):
            project_dir = os.path.join(OUTPUT_DIR, dirname)
            metadata_path = os.path.join(project_dir, "metadata.json")
            if os.path.isdir(project_dir) and os.path.exists(metadata_path):
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                metadata["project_id"] = dirname
                metadata["has_video"] = os.path.exists(os.path.join(project_dir, "final_video.mp4"))
                metadata["has_thumbnail"] = os.path.exists(os.path.join(project_dir, "thumbnail.png"))
                projects.append(metadata)
    return JSONResponse(content=projects)


@app.post("/api/upload/{project_id}")
async def upload_to_youtube(project_id: str, privacy: str = "private"):
    """완성된 프로젝트를 YouTube에 업로드합니다"""
    from youtube_uploader import YouTubeUploader

    project_dir = os.path.join(OUTPUT_DIR, project_id)
    metadata_path = os.path.join(project_dir, "metadata.json")
    video_path = os.path.join(project_dir, "final_video.mp4")
    thumbnail_path = os.path.join(project_dir, "thumbnail.png")
    subtitle_path = os.path.join(project_dir, "subtitles.srt")

    if not os.path.exists(metadata_path) or not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="프로젝트를 찾을 수 없습니다")

    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    uploader = YouTubeUploader()
    if not uploader.is_configured:
        raise HTTPException(
            status_code=400,
            detail="YouTube 업로드 미설정: client_secrets.json을 backend/ 폴더에 배치하세요"
        )

    result = uploader.upload(
        video_path=video_path,
        title=metadata.get("youtube_title", "AutoTube Video"),
        description=metadata.get("youtube_description", ""),
        tags=metadata.get("tags", []),
        hashtags=metadata.get("hashtags", []),
        thumbnail_path=thumbnail_path if os.path.exists(thumbnail_path) else None,
        subtitle_path=subtitle_path if os.path.exists(subtitle_path) else None,
        privacy=privacy,
    )

    return JSONResponse(content=result)


@app.get("/api/youtube/status")
async def youtube_status():
    """YouTube 업로드 설정 상태 확인"""
    from youtube_uploader import YouTubeUploader
    uploader = YouTubeUploader()
    return JSONResponse(content={
        "configured": uploader.is_configured,
        "has_token": os.path.exists(os.path.join(os.path.dirname(__file__), "youtube_token.pickle")),
    })


# ═══════════════════════════════════════
# WebSocket (실시간 진행 상황)
# ═══════════════════════════════════════

@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()
    websocket_connections[job_id] = websocket
    logger.info(f"🔌 WebSocket 연결: {job_id}")

    try:
        while True:
            # 클라이언트에서 ping 등 수신
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket 해제: {job_id}")
        websocket_connections.pop(job_id, None)


async def _notify_ws(job_id: str, data: dict):
    """WebSocket을 통해 클라이언트에 진행 상황 전송"""
    ws = websocket_connections.get(job_id)
    if ws:
        try:
            await ws.send_json(data)
        except Exception:
            pass


async def _run_pipeline(job_id: str, url: str, config: dict):
    """백그라운드에서 파이프라인 실행"""
    active_jobs[job_id]["status"] = "running"

    # 메인 이벤트 루프 참조 저장 (스레드 안전한 콜백을 위해)
    loop = asyncio.get_running_loop()

    def progress_callback(step, progress, message):
        active_jobs[job_id]["current_step"] = step
        active_jobs[job_id]["progress_message"] = message
        if step not in active_jobs[job_id]["steps_completed"] and progress >= 100:
            active_jobs[job_id]["steps_completed"].append(step)

        # WebSocket 알림 (스레드 안전하게 메인 루프에 스케줄링)
        try:
            loop.call_soon_threadsafe(
                asyncio.ensure_future,
                _notify_ws(job_id, {
                    "type": "progress",
                    "step": step,
                    "progress": progress,
                    "message": message,
                    "steps_completed": list(active_jobs[job_id]["steps_completed"]),
                })
            )
        except Exception:
            pass  # 루프가 닫힌 경우 무시

    try:
        pipeline = Pipeline(config)
        # 동기 파이프라인을 비동기로 실행
        result = await loop.run_in_executor(
            None, lambda: pipeline.run(url, callback=progress_callback)
        )

        active_jobs[job_id]["status"] = result["status"]
        active_jobs[job_id]["result"] = result
        active_jobs[job_id]["error"] = result.get("error")

        await _notify_ws(job_id, {
            "type": "complete",
            "status": result["status"],
            "result": result,
        })

    except Exception as e:
        active_jobs[job_id]["status"] = "error"
        active_jobs[job_id]["error"] = str(e)
        logger.error(f"❌ 파이프라인 에러: {e}", exc_info=True)

        await _notify_ws(job_id, {
            "type": "error",
            "error": str(e),
        })


# ═══════════════════════════════════════
# 서버 시작
# ═══════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8500, reload=True)
