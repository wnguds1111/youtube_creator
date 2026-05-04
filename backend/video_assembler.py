"""
AutoTube - Video Assembler (MoviePy v2)
배경 이미지 + 나레이션 오디오 + 자막을 결합하여 최종 영상을 생성하는 모듈
"""

import os
import requests
import logging
import numpy as np
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import (
    ImageClip, AudioFileClip, CompositeVideoClip,
    concatenate_videoclips, ColorClip
)

logger = logging.getLogger(__name__)


class VideoAssembler:
    """장면별 이미지와 오디오를 결합하여 최종 영상 생성"""

    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps
        self.assets_dir = os.path.join(os.path.dirname(__file__), "..", "assets")

    def assemble(
        self,
        scene_audios: list,
        article_images: list,
        content_data: dict,
        subtitle_path: str,
        output_path: str,
        veo_clips: list = None,
    ) -> str:
        """
        최종 영상을 조립합니다.

        Args:
            scene_audios: TTS에서 반환된 장면별 오디오 정보
            article_images: 로컬 이미지 파일 경로 리스트 (Imagen 생성 또는 기사 이미지)
            content_data: 대본 생성기에서 반환된 콘텐츠 데이터
            subtitle_path: SRT 자막 파일 경로
            output_path: 최종 영상 저장 경로
            veo_clips: Flow/Veo에서 생성된 영상 클립 정보 (선택)

        Returns:
            str: 생성된 영상 파일 경로
        """
        logger.info(f"🎬 영상 조립 시작 ({len(scene_audios)}개 장면)")

        # Veo 클립 맵 구성
        veo_map = {}
        if veo_clips:
            for vc in veo_clips:
                if vc.get("clip_path"):
                    veo_map[vc["scene_num"]] = vc["clip_path"]

        scenes = content_data.get("scenes", [])
        video_clips = []

        for i, scene_audio in enumerate(scene_audios):
            scene_num = scene_audio["scene_num"]
            duration_sec = scene_audio["duration_ms"] / 1000.0
            narration = scene_audio.get("narration", "")

            logger.info(f"  🎞️ 장면 {scene_num} 처리 중 ({duration_sec:.1f}초)...")

            # Veo 클립이 있으면 영상 클립 사용
            if scene_num in veo_map:
                try:
                    from moviepy import VideoFileClip
                    veo_clip = VideoFileClip(veo_map[scene_num])
                    veo_clip = veo_clip.resized((self.width, self.height))
                    # 오디오 길이에 맞게 자르기/루프
                    if veo_clip.duration < duration_sec:
                        veo_clip = veo_clip.loop(duration=duration_sec)
                    else:
                        veo_clip = veo_clip.subclipped(0, duration_sec)
                    img_clip = veo_clip
                    logger.info(f"  🎬 Veo 클립 사용: 장면 {scene_num}")
                except Exception as e:
                    logger.warning(f"  ⚠️ Veo 클립 로드 실패: {e}, 이미지 폴백")
                    bg_image = self._prepare_background(scene_num, article_images, scenes, i)
                    if narration:
                        bg_image = self._burn_subtitle(bg_image, narration)
                    img_clip = ImageClip(bg_image, duration=duration_sec)
            else:
                # 이미지 기반 장면
                bg_image = self._prepare_background(scene_num, article_images, scenes, i)
                if narration:
                    bg_image = self._burn_subtitle(bg_image, narration)
                img_clip = ImageClip(bg_image, duration=duration_sec)

            # 오디오 결합
            try:
                audio_clip = AudioFileClip(scene_audio["path"])
                img_clip = img_clip.with_audio(audio_clip)
            except Exception as e:
                logger.warning(f"  ⚠️ 오디오 결합 실패: {e}")

            video_clips.append(img_clip)

        # 인트로 추가
        intro_clip = self._create_intro(content_data.get("youtube_title", ""), duration=3)
        video_clips.insert(0, intro_clip)

        # 아웃트로 추가
        outro_clip = self._create_outro(duration=4)
        video_clips.append(outro_clip)

        # 최종 결합
        logger.info("🔧 최종 영상 렌더링 중...")
        final_video = concatenate_videoclips(video_clips, method="compose")

        # 출력
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        final_video.write_videofile(
            output_path,
            fps=self.fps,
            codec="libx264",
            audio_codec="aac",
            bitrate="5000k",
            preset="medium",
            threads=4,
            logger=None,
        )

        # 리소스 정리
        final_video.close()
        for clip in video_clips:
            clip.close()

        logger.info(f"✅ 영상 생성 완료: {output_path}")
        return output_path

    def _prepare_background(
        self, scene_num: int, article_images: list,
        scenes: list, index: int
    ) -> np.ndarray:
        """장면에 맞는 배경 이미지를 준비 (로컬 파일 또는 URL 지원)"""

        if article_images and index < len(article_images):
            img = self._load_image(article_images[index])
            if img is not None:
                return img

        if article_images:
            img = self._load_image(article_images[index % len(article_images)])
            if img is not None:
                return img

        return self._create_color_background(scene_num)

    def _load_image(self, source: str) -> np.ndarray | None:
        """로컬 파일 경로 또는 URL에서 이미지를 로드"""
        try:
            if os.path.exists(source):
                # 로컬 파일
                img = Image.open(source).convert("RGB")
            elif source.startswith("http"):
                # URL
                resp = requests.get(source, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                img = Image.open(BytesIO(resp.content)).convert("RGB")
            else:
                return None
            return np.array(self._resize_cover(img))
        except Exception as e:
            logger.warning(f"  ⚠️ 이미지 로드 실패 ({str(source)[:50]}): {e}")
            return None

    def _resize_cover(self, img: Image.Image) -> Image.Image:
        """이미지를 영상 해상도에 맞게 cover 크롭"""
        target_ratio = self.width / self.height
        img_ratio = img.width / img.height

        if img_ratio > target_ratio:
            new_width = int(img.height * target_ratio)
            left = (img.width - new_width) // 2
            img = img.crop((left, 0, left + new_width, img.height))
        else:
            new_height = int(img.width / target_ratio)
            top = (img.height - new_height) // 2
            img = img.crop((0, top, img.width, top + new_height))

        return img.resize((self.width, self.height), Image.LANCZOS)

    def _create_color_background(self, scene_num: int) -> np.ndarray:
        """컬러 그라데이션 배경 생성"""
        color_themes = [
            [(25, 25, 60), (50, 20, 80)],
            [(20, 40, 80), (60, 30, 60)],
            [(30, 50, 70), (20, 30, 50)],
            [(40, 20, 60), (20, 40, 70)],
            [(20, 50, 50), (40, 20, 60)],
        ]
        colors = color_themes[(scene_num - 1) % len(color_themes)]

        img = Image.new("RGB", (self.width, self.height))
        draw = ImageDraw.Draw(img)

        for y in range(self.height):
            ratio = y / self.height
            r = int(colors[0][0] * (1 - ratio) + colors[1][0] * ratio)
            g = int(colors[0][1] * (1 - ratio) + colors[1][1] * ratio)
            b = int(colors[0][2] * (1 - ratio) + colors[1][2] * ratio)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))

        return np.array(img)

    def _burn_subtitle(self, img_array: np.ndarray, narration: str) -> np.ndarray:
        """이미지에 자막을 직접 렌더링 (burn-in)"""
        img = Image.fromarray(img_array).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        font = self._get_font(36)

        # 텍스트 줄바꿈
        max_chars = 35
        lines = []
        words = narration.split()
        current_line = ""
        for word in words:
            if len(current_line + word) <= max_chars:
                current_line = f"{current_line} {word}".strip()
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        # 최대 2줄 표시
        display_lines = lines[:2]
        text = "\n".join(display_lines)

        # 자막 배경 박스
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        padding = 20
        box_x = (self.width - text_w) // 2 - padding
        box_y = self.height - text_h - 80 - padding
        draw.rounded_rectangle(
            [(box_x, box_y), (box_x + text_w + padding * 2, box_y + text_h + padding * 2)],
            radius=12,
            fill=(0, 0, 0, 180),
        )

        # 텍스트
        x = (self.width - text_w) // 2
        y = self.height - text_h - 80
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

        result = Image.alpha_composite(img, overlay)
        return np.array(result.convert("RGB"))

    def _create_intro(self, title: str, duration: float = 3) -> ImageClip:
        """인트로 장면 생성"""
        img = Image.new("RGB", (self.width, self.height), (15, 15, 30))
        draw = ImageDraw.Draw(img)

        # 배경 그라데이션
        for y in range(self.height):
            ratio = y / self.height
            r = int(15 + 20 * ratio)
            g = int(15 + 10 * ratio)
            b = int(30 + 40 * ratio)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))

        # 제목 텍스트
        font = self._get_font(60)
        max_chars = 20
        lines = []
        current = ""
        for char in title:
            current += char
            if len(current) >= max_chars:
                lines.append(current)
                current = ""
        if current:
            lines.append(current)

        total_h = len(lines) * 80
        y_start = (self.height - total_h) // 2

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            text_w = bbox[2] - bbox[0]
            x = (self.width - text_w) // 2
            y = y_start + i * 80
            draw.text((x, y), line, font=font, fill=(255, 255, 255),
                       stroke_width=3, stroke_fill=(0, 0, 0))

        clip = ImageClip(np.array(img), duration=duration)
        return clip

    def _create_outro(self, duration: float = 4) -> ImageClip:
        """아웃트로 장면 생성"""
        img = Image.new("RGB", (self.width, self.height), (15, 15, 30))
        draw = ImageDraw.Draw(img)

        for y in range(self.height):
            ratio = y / self.height
            draw.line([(0, y), (self.width, y)],
                      fill=(int(20 * ratio), int(10 * ratio), int(40 + 30 * ratio)))

        font_big = self._get_font(54)
        font_small = self._get_font(32)

        texts = [
            ("구독과 좋아요 부탁드립니다!", font_big, (255, 220, 50)),
            ("🔔 알림 설정도 잊지 마세요!", font_small, (200, 200, 220)),
        ]

        y_pos = self.height // 2 - 60
        for text, font, color in texts:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            x = (self.width - text_w) // 2
            draw.text((x, y_pos), text, font=font, fill=color,
                       stroke_width=2, stroke_fill=(0, 0, 0))
            y_pos += 80

        clip = ImageClip(np.array(img), duration=duration)
        return clip

    def _get_font(self, size: int) -> ImageFont.FreeTypeFont:
        """한국어 폰트 로드"""
        font_candidates = [
            os.path.join(self.assets_dir, "fonts", "NanumGothicBold.ttf"),
            "C:/Windows/Fonts/malgunbd.ttf",
            "C:/Windows/Fonts/malgun.ttf",
            "C:/Windows/Fonts/NanumGothicBold.ttf",
            "C:/Windows/Fonts/gulim.ttc",
        ]
        for path in font_candidates:
            try:
                return ImageFont.truetype(path, size)
            except (IOError, OSError):
                continue

        return ImageFont.load_default()
