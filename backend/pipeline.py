"""
AutoTube - Pipeline Orchestrator v2 (Ultra Edition)
Gemini TTS + Imagen + Flow/Veo + YouTube 자동 업로드 통합 파이프라인
"""

import os
import json
import time
import logging
from datetime import datetime

from scraper import ArticleScraper
from script_generator import ScriptGenerator
from tts_gemini import GeminiTTSEngine
from image_generator import ImageGenerator
from subtitle_generator import SubtitleGenerator
from video_assembler import VideoAssembler
from credit_tracker import get_tracker

logger = logging.getLogger(__name__)


class Pipeline:
    """URL → 유튜브 콘텐츠 전체 자동 생성 파이프라인 (Ultra Edition)"""

    STEPS = [
        "article_extraction",
        "script_generation",
        "tts_narration",
        "image_generation",
        "thumbnail_creation",
        "subtitle_generation",
        "video_assembly",
    ]

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

        # Gemini TTS (gTTS 폴백 포함)
        voice = config.get("tts_voice", "Kore")
        self.tts = GeminiTTSEngine(api_key=api_key, voice=voice)

        # Imagen 이미지 생성
        self.image_gen = ImageGenerator(api_key=api_key)

        # 자막 / 영상 조립
        self.subtitle = SubtitleGenerator()
        self.assembler = VideoAssembler(
            width=config.get("video_width", 1920),
            height=config.get("video_height", 1080),
            fps=config.get("video_fps", 30),
        )

        # Flow/Veo 사용 여부
        self.use_flow = config.get("use_flow", False)

    def run(self, url: str, callback=None) -> dict:
        """전체 파이프라인 실행"""
        start_time = time.time()
        project_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        project_dir = os.path.join(self.output_base, project_id)
        os.makedirs(project_dir, exist_ok=True)

        result = {
            "status": "running",
            "project_id": project_id,
            "project_dir": project_dir,
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
            # ═══ STEP 1: 기사 추출 ═══
            update("article_extraction", 0, "기사 내용을 추출하는 중...")
            article = self.scraper.extract(url)
            result["steps_completed"].append("article_extraction")
            update("article_extraction", 100, f"기사 추출 완료: '{article['title']}'")

            with open(os.path.join(project_dir, "article.json"), "w", encoding="utf-8") as f:
                json.dump(article, f, ensure_ascii=False, indent=2)

            # ═══ STEP 2: AI 대본 생성 ═══
            update("script_generation", 0, "AI가 대본과 메타데이터를 작성하는 중...")
            content = self.script_gen.generate(article)
            get_tracker().record_usage("gemini_text", 1, "대본 생성")
            result["steps_completed"].append("script_generation")
            update("script_generation", 100, f"대본 생성 완료: '{content.get('youtube_title', '')}'")

            with open(os.path.join(project_dir, "content.json"), "w", encoding="utf-8") as f:
                json.dump(content, f, ensure_ascii=False, indent=2)

            # ═══ STEP 3: Gemini TTS 나레이션 ═══
            update("tts_narration", 0, "Gemini AI 음성 나레이션을 생성하는 중...")
            tts_result = self.tts.generate_narration(content["scenes"], project_dir)
            scene_count = len(content["scenes"])
            get_tracker().record_usage("gemini_tts", scene_count, f"TTS {scene_count}장면")
            result["steps_completed"].append("tts_narration")
            update("tts_narration", 100, f"나레이션 완료: {tts_result['total_duration_ms'] / 1000:.1f}초")

            # ═══ STEP 4: AI 이미지 생성 (Imagen) ═══
            update("image_generation", 0, "Imagen AI로 장면 이미지를 생성하는 중...")
            scene_images = self.image_gen.generate_scene_images(content["scenes"], project_dir)
            get_tracker().record_usage("imagen_image", len(scene_images), f"장면 이미지 {len(scene_images)}개")
            result["steps_completed"].append("image_generation")
            update("image_generation", 100, f"이미지 생성 완료: {len(scene_images)}개")

            # ═══ STEP 4.5: Flow/Veo 영상 클립 (선택) ═══
            veo_clips = []
            if self.use_flow:
                update("image_generation", 50, "Flow에서 Veo 영상 클립을 생성하는 중...")
                try:
                    from flow_automator import run_flow_generation
                    veo_clips = run_flow_generation(
                        content["scenes"], project_dir,
                        quality=self.config.get("veo_quality", "fast"),
                    )
                    veo_success = sum(1 for c in veo_clips if c.get('clip_path'))
                    veo_type = f"veo_{self.config.get('veo_quality', 'fast')}"
                    get_tracker().record_usage(veo_type, veo_success, f"Veo 클립 {veo_success}개")
                    logger.info(f"🎬 Veo 클립: {veo_success}개 성공")
                except Exception as e:
                    logger.warning(f"⚠️ Flow/Veo 생략: {e}")

            # ═══ STEP 5: 썸네일 생성 ═══
            update("thumbnail_creation", 0, "AI 썸네일을 생성하는 중...")
            thumbnail_path = self.image_gen.generate_thumbnail(
                main_text=content.get("thumbnail_text", article["title"][:10]),
                subtitle=content.get("thumbnail_subtitle", ""),
                article_topic=article["title"],
                output_path=os.path.join(project_dir, "thumbnail.png"),
            )
            result["thumbnail_path"] = thumbnail_path
            get_tracker().record_usage("imagen_thumbnail", 1, "AI 썸네일")
            result["steps_completed"].append("thumbnail_creation")
            update("thumbnail_creation", 100, "AI 썸네일 생성 완료")

            # ═══ STEP 6: 자막 생성 ═══
            update("subtitle_generation", 0, "자막(SRT)을 생성하는 중...")
            subtitle_path = self.subtitle.generate_srt(
                tts_result["scene_audios"],
                os.path.join(project_dir, "subtitles.srt"),
            )
            result["subtitle_path"] = subtitle_path
            result["steps_completed"].append("subtitle_generation")
            update("subtitle_generation", 100, "자막 생성 완료")

            # ═══ STEP 7: 영상 조립 ═══
            update("video_assembly", 0, "최종 영상을 렌더링하는 중...")

            # Veo 클립이 있으면 사용, 없으면 AI 이미지 사용
            image_paths = [si["image_path"] for si in scene_images]

            video_path = self.assembler.assemble(
                scene_audios=tts_result["scene_audios"],
                article_images=image_paths,
                content_data=content,
                subtitle_path=subtitle_path,
                output_path=os.path.join(project_dir, "final_video.mp4"),
                veo_clips=veo_clips if veo_clips else None,
            )
            result["video_path"] = video_path
            result["steps_completed"].append("video_assembly")
            update("video_assembly", 100, "영상 렌더링 완료!")

            # ═══ 메타데이터 저장 ═══
            metadata = {
                "youtube_title": content.get("youtube_title", ""),
                "youtube_description": content.get("youtube_description", ""),
                "hashtags": content.get("hashtags", []),
                "tags": content.get("tags", []),
                "source_url": url,
                "source_name": article.get("source_name", ""),
                "created_at": datetime.now().isoformat(),
                "total_duration_sec": tts_result["total_duration_ms"] / 1000,
                "tts_engine": "gemini",
                "image_engine": "imagen",
                "use_flow": self.use_flow,
            }
            result["metadata"] = metadata

            with open(os.path.join(project_dir, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

            elapsed = time.time() - start_time
            result["status"] = "success"
            result["duration_sec"] = round(elapsed, 1)

            get_tracker().record_video_created()
            logger.info(f"🎉 전체 파이프라인 완료! ({elapsed:.1f}초)")
            return result

        except Exception as e:
            elapsed = time.time() - start_time
            result["status"] = "error"
            result["error"] = str(e)
            result["duration_sec"] = round(elapsed, 1)
            logger.error(f"❌ 파이프라인 실패: {e}", exc_info=True)
            return result
