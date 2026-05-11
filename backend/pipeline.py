"""
AutoTube - Pipeline Orchestrator v3 (Lightweight Hybrid Edition)
AI가 대본과 프롬프트를 추출하고, 사용자가 첨부한 영상으로 최종 조립하는 2단계 파이프라인
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import List

from scraper import ArticleScraper
from script_generator import ScriptGenerator
from tts_gemini import GeminiTTSEngine
from subtitle_generator import SubtitleGenerator
from video_assembler import VideoAssembler
from credit_tracker import get_tracker

logger = logging.getLogger(__name__)

class Pipeline:
    """초경량 2단계 파이프라인"""
    
    def __init__(self, config: dict):
        self.config = config
        self.output_base = config.get("output_dir", os.path.join(os.path.dirname(__file__), "..", "output"))
        api_key = config["gemini_api_key"]

        # 모듈 초기화
        self.scraper = ArticleScraper(language=config.get("language", "ko"))
        self.script_gen = ScriptGenerator(
            api_key=api_key,
            model_name=config.get("gemini_model", "gemini-2.5-flash"),
        )
        
        voice = config.get("tts_voice", "Kore")
        self.tts = GeminiTTSEngine(api_key=api_key, voice=voice)
        self.subtitle = SubtitleGenerator()
        self.assembler = VideoAssembler(
            width=config.get("video_width", 1080),
            height=config.get("video_height", 1920),
            fps=config.get("video_fps", 30),
        )

    def prepare(self, url: str) -> dict:
        """1단계: 기사 추출 및 대본/프롬프트 생성"""
        start_time = time.time()
        project_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        project_dir = os.path.join(self.output_base, project_id)
        os.makedirs(project_dir, exist_ok=True)
        
        logger.info(f"[{project_id}] 1단계 시작: 기사 추출 중...")
        article = self.scraper.extract(url)
        with open(os.path.join(project_dir, "article.json"), "w", encoding="utf-8") as f:
            json.dump(article, f, ensure_ascii=False, indent=2)
            
        logger.info(f"[{project_id}] 1단계 진행: AI 대본 및 프롬프트 생성 중...")
        content = self.script_gen.generate(
            article,
            style=self.config.get("image_style", "cinematic"),
            reference_url=self.config.get("reference_url"),
            target_duration=self.config.get("target_duration", 50)
        )
        
        get_tracker().record_usage("gemini_text", 1, "대본 및 프롬프트 생성")
        
        with open(os.path.join(project_dir, "content.json"), "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
            
        logger.info(f"[{project_id}] 1단계 완료! ({time.time() - start_time:.1f}초)")
        
        return {
            "project_id": project_id,
            "content": content
        }

    def assemble(self, project_id: str, uploaded_clips: List[str], uploaded_images: List[str] = None, callback=None) -> dict:
        """2단계: 업로드된 영상 기반으로 음성, 자막, 영상 조립 및 유튜브 업로드"""
        start_time = time.time()
        project_dir = os.path.join(self.output_base, project_id)
        
        result = {
            "status": "running",
            "project_id": project_id,
            "steps_completed": [],
            "current_step": None,
            "error": None,
        }

        def update(step, progress, message):
            result["current_step"] = step
            logger.info(f"[{step}] {message}")
            if callback:
                callback(step, progress, message)

        try:
            # content.json 불러오기
            with open(os.path.join(project_dir, "content.json"), "r", encoding="utf-8") as f:
                content = json.load(f)
                
            article_images = []
            try:
                with open(os.path.join(project_dir, "article.json"), "r", encoding="utf-8") as f:
                    article = json.load(f)
                    article_images = article.get("images", [])
            except Exception:
                pass
                
            if uploaded_images:
                article_images = uploaded_images
                
            # ═══ STEP 3: Gemini TTS 나레이션 ═══
            update("tts_narration", 0, "AI 음성 나레이션을 생성하는 중...")
            tts_result = self.tts.generate_narration(content["scenes"], project_dir)
            scene_count = len(content["scenes"])
            get_tracker().record_usage("gemini_tts", scene_count, f"TTS {scene_count}장면")
            result["steps_completed"].append("tts_narration")
            update("tts_narration", 100, f"나레이션 완료: {tts_result['total_duration_ms'] / 1000:.1f}초")

            # ═══ STEP 4: 자막 생성 ═══
            update("subtitle_generation", 0, "SRT 자막을 생성하는 중...")
            srt_path = os.path.join(project_dir, "subtitles.srt")
            subtitle_path = self.subtitle.generate_srt(tts_result["scene_audios"], srt_path)
            result["steps_completed"].append("subtitle_generation")
            update("subtitle_generation", 100, "자막 생성 완료")

            # ═══ STEP 5: 최종 영상 조립 ═══
            update("video_assembly", 0, "첨부된 영상을 바탕으로 최종 조립 중...")
            final_video_path = os.path.join(project_dir, "final_video.mp4")
            
            # 클립 경로를 딕셔너리 리스트 형태로 변환 (VideoAssembler 호환)
            veo_clips = []
            for i, clip_path in enumerate(uploaded_clips):
                veo_clips.append({"scene_num": i+1, "clip_path": clip_path})
                
            self.assembler.assemble(
                scene_audios=tts_result["scene_audios"],
                article_images=article_images,
                content_data=content,
                subtitle_path=subtitle_path,
                output_path=final_video_path,
                veo_clips=veo_clips
            )
            
            result["steps_completed"].append("video_assembly")
            update("video_assembly", 100, "최종 영상 조립 완료!")

            # ═══ 메타데이터 저장 ═══
            metadata = {
                "youtube_title": content.get("youtube_title", ""),
                "youtube_description": content.get("youtube_description", ""),
                "hashtags": content.get("hashtags", []),
                "tags": content.get("tags", []),
                "created_at": datetime.now().isoformat(),
                "total_duration_sec": tts_result["total_duration_ms"] / 1000,
                "tts_engine": "gemini",
                "use_flow_manual": True,
                "owner": self.config.get("owner", "anonymous")
            }
            result["metadata"] = metadata
            with open(os.path.join(project_dir, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

            result["status"] = "success"
            result["result"] = {"video_path": final_video_path, "project_id": project_id}
            update("complete", 100, f"🎉 전체 파이프라인 완료! ({time.time() - start_time:.1f}초)")

        except Exception as e:
            logger.error(f"❌ 파이프라인 실패: {str(e)}", exc_info=True)
            result["status"] = "error"
            result["error"] = str(e)
            if callback:
                callback("error", 0, f"오류 발생: {str(e)}")

        return result
