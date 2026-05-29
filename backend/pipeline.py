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
from omni_video_generator import OmniVideoGenerator

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
        self.omni_gen = OmniVideoGenerator(api_key=api_key)

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
            
        # 썸네일 자동 생성
        self._generate_thumbnail(content, project_dir, self.config.get("omni_template"))
            
        logger.info(f"[{project_id}] 1단계 완료! ({time.time() - start_time:.1f}초)")
        
        return {
            "project_id": project_id,
            "content": content
        }

    def _generate_thumbnail(self, content: dict, project_dir: str, omni_template: str):
        """Imagen 3.0 모델을 사용하여 유튜브용 16:9 썸네일을 자동 생성합니다."""
        logger.info("🎨 유튜브 썸네일 이미지 생성 중...")
        try:
            from google import genai
            from google.genai import types
            import io
            from PIL import Image
            
            client = genai.Client(api_key=self.config["gemini_api_key"])
            
            style_prefix = f"[{omni_template} style] " if omni_template else ""
            prompt_base = content.get("thumbnail_text", "") + " " + content.get("thumbnail_subtitle", "")
            if not prompt_base.strip() and content.get("scenes"):
                prompt_base = content["scenes"][0].get("visual_prompt", "")
                
            prompt = f"{style_prefix}Create a highly engaging YouTube thumbnail background image for a video about: {prompt_base}. Absolutely NO Chinese characters, NO text, NO words, NO letters anywhere in the image. Masterpiece, highly detailed, strong {omni_template if omni_template else 'cinematic'} aesthetic."
            
            result = client.models.generate_images(
                model='imagen-3.0-generate-001',
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="16:9",
                    output_mime_type="image/jpeg",
                )
            )
            
            if result.generated_images:
                img_bytes = result.generated_images[0].image.image_bytes
                img = Image.open(io.BytesIO(img_bytes))
                
                thumbnail_path = os.path.join(project_dir, "thumbnail.png")
                img.save(thumbnail_path, format="PNG")
                logger.info(f"✅ 썸네일 생성 완료: {thumbnail_path}")
        except Exception as e:
            logger.error(f"⚠️ 썸네일 생성 실패 (건너뜀): {e}")

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
            result["result"] = {"video_path": final_video_path, "project_id": project_id, "metadata": metadata}
            update("complete", 100, f"🎉 전체 파이프라인 완료! ({time.time() - start_time:.1f}초)")

        except Exception as e:
            logger.error(f"❌ 파이프라인 실패: {str(e)}", exc_info=True)
            result["status"] = "error"
            result["error"] = str(e)
            if callback:
                callback("error", 0, f"오류 발생: {str(e)}")

        return result

    def auto_generate(self, url: str, callback=None) -> dict:
        """논스톱 완전 자동화 파이프라인 (대본 추출 -> 숏츠 비디오 전체 자동 생성)"""
        start_time = time.time()
        
        # 1. Prepare
        if callback: callback("prepare", 0, "기사 추출 및 대본 작성 중...")
        prepare_result = self.prepare(url)
        project_id = prepare_result["project_id"]
        content = prepare_result["content"]
        project_dir = os.path.join(self.output_base, project_id)
        
        # 2. Omni 비디오 클립 생성
        if callback: callback("video_generation", 0, "Omni AI를 사용해 비디오 클립을 자동 생성하는 중...")
        veo_clips = []
        scenes = content.get("scenes", [])
        
        veo_clips_dir = os.path.join(project_dir, "veo_clips")
        os.makedirs(veo_clips_dir, exist_ok=True)
        
        for i, scene in enumerate(scenes):
            scene_num = scene.get("scene_num", i+1)
            prompt = scene.get("visual_prompt", "")
            if callback: callback("video_generation", int((i / max(1, len(scenes))) * 100), f"장면 {scene_num}/{len(scenes)} 비디오 생성 중...")
            
            output_path = os.path.join(veo_clips_dir, f"scene_{scene_num:02d}.mp4")
            generated_path = self.omni_gen.generate_clip(prompt, output_path, duration_sec=scene.get("duration_sec", 10))
            if generated_path:
                veo_clips.append(generated_path)
            else:
                logger.warning(f"장면 {scene_num} 비디오 생성 실패, 건너뜁니다.")
        
        if callback: callback("video_generation", 100, "모든 비디오 클립 생성 완료")
        
        # 3. Assemble
        return self.assemble(project_id, uploaded_clips=veo_clips, callback=callback)
