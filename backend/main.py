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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from pipeline import Pipeline
from credit_tracker import get_tracker
from db import db
from fastapi import Depends, Header

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

# 정적 파일 (프론트엔드 및 아웃풋)
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")

# 마운트 전 폴더가 존재하지 않으면 생성 (Railway 등에서 폴더 누락으로 인한 에러 방지)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(FRONTEND_DIR, exist_ok=True)

app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# ═══════════════════════════════════════
# 상태 관리
# ═══════════════════════════════════════
active_jobs = {}  # job_id -> job status
websocket_connections = {}  # job_id -> WebSocket


# ═══════════════════════════════════════
# 요청 / 응답 모델
# ═══════════════════════════════════════
class PrepareRequest(BaseModel):
    url: str
    language: str = "ko"
    gemini_model: str = "gemini-2.5-flash"
    tts_voice: str = "Kore"
    tts_speed: float = 1.0
    video_width: int = 1080
    video_height: int = 1920
    target_duration: int = 50
    gemini_api_key: Optional[str] = None
    omni_template: Optional[str] = None
    tts_voice: Optional[str] = "Puck"

class JobStatus(BaseModel):
    job_id: str
    status: str
    current_step: Optional[str] = None
    steps_completed: list = []
    progress_message: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None

class AuthRequest(BaseModel):
    username: str
    password: str

async def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증이 필요합니다.")
    token = authorization.split(" ")[1]
    username = db.get_user_from_session(token)
    if not username:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")
    return username


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


@app.post("/api/auth/register")
async def auth_register(req: AuthRequest):
    success, msg = db.register(req.username, req.password)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}

@app.post("/api/auth/login")
async def auth_login(req: AuthRequest):
    token = db.login(req.username, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 틀렸습니다.")
    return {"token": token, "username": req.username}

class GoogleAuthRequest(BaseModel):
    token: str

@app.get("/api/auth/me")
async def auth_me(username: str = Depends(get_current_user)):
    user_info = db.users.get(username, {})
    return {
        "username": username,
        "name": user_info.get("name"),
        "picture": user_info.get("picture"),
        "auth_provider": user_info.get("auth_provider", "local")
    }

@app.post("/api/auth/google")
async def auth_google(req: GoogleAuthRequest):
    import requests
    # Verify the token
    verify_url = f"https://oauth2.googleapis.com/tokeninfo?id_token={req.token}"
    response = requests.get(verify_url)
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="유효하지 않은 구글 토큰입니다.")
    user_info = response.json()
    email = user_info.get("email")
    name = user_info.get("name", email.split("@")[0] if email else "User")
    picture = user_info.get("picture")
    
    if not email:
        raise HTTPException(status_code=400, detail="이메일 정보를 가져올 수 없습니다.")
        
    token = db.google_login(email, name, picture)
    return {"token": token, "username": email, "name": name, "picture": picture}

@app.post("/api/auth/logout")
async def auth_logout(authorization: str = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        db.logout(token)
    return {"message": "로그아웃 완료"}

@app.post("/api/prepare")
async def prepare_video(request: PrepareRequest, username: str = Depends(get_current_user)):
    """1단계: 기사 추출 및 대본, 프롬프트 생성"""
    gemini_key = request.gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not gemini_key or gemini_key == "your_gemini_api_key_here":
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY가 설정되지 않았습니다. API 키를 입력하거나 .env 파일을 확인하세요.")

    config = {
        "gemini_api_key": gemini_key,
        "gemini_model": request.gemini_model,
        "language": request.language,
        "tts_lang": request.language,
        "tts_voice": request.tts_voice,
        "tts_speed": request.tts_speed,
        "video_width": request.video_width,
        "video_height": request.video_height,
        "target_duration": request.target_duration,
        "output_dir": OUTPUT_DIR,
        "owner": username,
        "omni_template": request.omni_template,
    }

    pipeline = Pipeline(config)
    try:
        # 동기 작업이므로 백그라운드 없이 즉시 반환
        result = pipeline.prepare(request.url)
        
        # 설정 저장 (2단계에서 사용하기 위함)
        project_dir = os.path.join(OUTPUT_DIR, result["project_id"])
        with open(os.path.join(project_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Prepare failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/assemble/{job_id}", response_model=JobStatus)
async def assemble_video(
    job_id: str, 
    files: list[UploadFile] = File(...), 
    image_files: list[UploadFile] = File(default=[]),
    username: str = Depends(get_current_user)
):
    """2단계: 업로드된 영상으로 최종 결과물 조립"""
    project_dir = os.path.join(OUTPUT_DIR, job_id)
    if not os.path.exists(project_dir):
        raise HTTPException(status_code=404, detail="Project not found")
        
    config_path = os.path.join(project_dir, "config.json")
    if not os.path.exists(config_path):
        raise HTTPException(status_code=400, detail="Config not found for this project")
        
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        
    # 권한 체크
    if config.get("owner") != username:
        raise HTTPException(status_code=403, detail="본인의 프로젝트만 조립할 수 있습니다.")

    # 파일 저장
    veo_clips_dir = os.path.join(project_dir, "veo_clips")
    os.makedirs(veo_clips_dir, exist_ok=True)
    
    saved_paths = []
    # 파일 이름 순으로 정렬 (scene_1.mp4, scene_2.mp4 등에 매핑하기 위해 클라이언트에서 순서대로 보냈다고 가정)
    for idx, file in enumerate(files):
        ext = file.filename.split('.')[-1]
        file_path = os.path.join(veo_clips_dir, f"scene_{idx+1:02d}.{ext}")
        with open(file_path, "wb") as f:
            f.write(await file.read())
        saved_paths.append(file_path)

    saved_images = []
    for img in image_files:
        if not img.filename: continue
        user_images_dir = os.path.join(project_dir, "user_images")
        os.makedirs(user_images_dir, exist_ok=True)
        ext = img.filename.split('.')[-1]
        img_path = os.path.join(user_images_dir, f"custom_{len(saved_images):02d}.{ext}")
        with open(img_path, "wb") as f:
            f.write(await img.read())
        saved_images.append(img_path)

    # 파이프라인 초기화
    if not config.get("gemini_api_key"):
        config["gemini_api_key"] = os.getenv("GEMINI_API_KEY")
    pipeline = Pipeline(config)
    
    active_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "current_step": None,
        "steps_completed": [],
        "progress_message": "영상 조립 대기 중...",
        "result": None,
        "error": None,
    }

    async def _run_assemble():
        def callback(step, progress, message):
            active_jobs[job_id]["current_step"] = step
            active_jobs[job_id]["progress_message"] = message
            if progress >= 100 and step not in active_jobs[job_id]["steps_completed"]:
                active_jobs[job_id]["steps_completed"].append(step)

        # 백그라운드 스레드로 실행 (루프 블로킹 방지)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: pipeline.assemble(job_id, saved_paths, saved_images, callback))
        active_jobs[job_id].update(result)

    asyncio.create_task(_run_assemble())
    return JSONResponse(content=active_jobs[job_id])


@app.post("/api/auto-generate", response_model=JobStatus)
async def auto_generate_video(request: PrepareRequest, username: str = Depends(get_current_user)):
    """논스톱 완전 자동화: 대본 추출부터 Omni 영상 생성, 최종 조립까지 한 번에 실행"""
    gemini_key = request.gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not gemini_key or gemini_key == "your_gemini_api_key_here":
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY가 설정되지 않았습니다.")

    config = {
        "gemini_api_key": gemini_key,
        "gemini_model": request.gemini_model,
        "language": request.language,
        "tts_lang": request.language,
        "tts_voice": request.tts_voice,
        "tts_speed": request.tts_speed,
        "video_width": request.video_width,
        "video_height": request.video_height,
        "target_duration": request.target_duration,
        "output_dir": OUTPUT_DIR,
        "owner": username,
        "omni_template": request.omni_template,
    }

    job_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    active_jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "current_step": "initialize",
        "steps_completed": [],
        "progress_message": "자동화 파이프라인 시작 중...",
        "result": None,
        "error": None,
    }

    pipeline = Pipeline(config)

    async def _run_auto_generate():
        def callback(step, progress, message):
            active_jobs[job_id]["current_step"] = step
            active_jobs[job_id]["progress_message"] = message
            if progress >= 100 and step not in active_jobs[job_id]["steps_completed"]:
                active_jobs[job_id]["steps_completed"].append(step)
            
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: pipeline.auto_generate(request.url, callback))
        active_jobs[job_id].update(result)

    asyncio.create_task(_run_auto_generate())
    
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
async def list_projects(username: str = Depends(get_current_user)):
    """완료된 프로젝트 목록을 반환합니다"""
    projects = []
    if os.path.exists(OUTPUT_DIR):
        for dirname in sorted(os.listdir(OUTPUT_DIR), reverse=True):
            project_dir = os.path.join(OUTPUT_DIR, dirname)
            metadata_path = os.path.join(project_dir, "metadata.json")
            if os.path.isdir(project_dir) and os.path.exists(metadata_path):
                try:
                    with open(metadata_path, "r", encoding="utf-8") as f:
                        metadata = json.load(f)
                except Exception:
                    continue
                
                # 본인 프로젝트만 필터링 (기존 프로젝트 하위호환 위해 owner 없는 경우도 일단 제외)
                if metadata.get("owner") != username:
                    continue

                metadata["project_id"] = dirname
                metadata["has_video"] = os.path.exists(os.path.join(project_dir, "final_video.mp4"))
                metadata["has_thumbnail"] = os.path.exists(os.path.join(project_dir, "thumbnail.png"))
                projects.append(metadata)
    return JSONResponse(content=projects)


@app.post("/api/upload/{project_id}")
async def upload_to_youtube(project_id: str, privacy: str = "private", username: str = Depends(get_current_user)):
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

    if metadata.get("owner") and metadata.get("owner") != username:
        raise HTTPException(status_code=403, detail="본인의 프로젝트만 업로드할 수 있습니다.")

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

    if result.get("status") == "success":
        metadata["youtube_status"] = "success"
        metadata["youtube_url"] = result.get("url")
        metadata["youtube_uploaded_at"] = datetime.now().isoformat()
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

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


