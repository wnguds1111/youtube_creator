"""
AutoTube - Video Assembler (MoviePy v2)
배경 이미지 + 나레이션 오디오 + 자막을 결합하여 최종 영상을 생성하는 모듈
"""

import os
import logging
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import (
    ImageClip, AudioFileClip, CompositeVideoClip,
    VideoFileClip, concatenate_videoclips, ColorClip
)

logger = logging.getLogger(__name__)


class VideoAssembler:
    """장면별 이미지와 오디오를 결합하여 최종 영상 생성"""

    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps

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
        장면별 오디오 + 배경(이미지/Veo클립) + 자막을 결합하여 영상 생성

        Args:
            scene_audios: [{"scene_num": 1, "path": "...", "duration_ms": 5000, "narration": "..."}]
            article_images: ["images/scene_01.png", ...]
            content_data: 대본 데이터 (scenes, youtube_title 등)
            subtitle_path: SRT 자막 파일 경로
            output_path: 최종 영상 저장 경로
            veo_clips: [{"scene_num": 1, "clip_path": "..." or None}] (선택)

        Returns:
            str: 생성된 영상 파일 경로
        """
        logger.info(f"🎬 영상 조립 시작 ({len(scene_audios)}개 장면, {self.width}x{self.height})")

        scenes = content_data.get("scenes", [])
        video_clips = []

        for i, audio_info in enumerate(scene_audios):
            scene_num = audio_info["scene_num"]
            audio_path = audio_info["path"]
            narration = audio_info.get("narration", "")

            try:
                # 오디오 로드
                audio_clip = AudioFileClip(audio_path)
                duration = audio_clip.duration

                # 배경 준비 (Veo 클립 > AI 이미지 > 컬러 폴백)
                bg_clip = self._prepare_background(
                    scene_num, article_images, scenes, i, veo_clips, duration
                )

                # 자막 오버레이
                if narration:
                    subtitle_frame = self._create_subtitle_frame(narration)
                    subtitle_clip = ImageClip(subtitle_frame, duration=duration)
                    scene_clip = CompositeVideoClip([bg_clip, subtitle_clip])
                else:
                    scene_clip = bg_clip

                # 오디오 합성
                scene_clip = scene_clip.with_audio(audio_clip)
                video_clips.append(scene_clip)
                logger.info(f"  ✅ 장면 {scene_num}: {duration:.1f}초")

            except Exception as e:
                logger.error(f"  ❌ 장면 {scene_num} 조립 실패: {e}")
                continue

        if not video_clips:
            raise RuntimeError("조립 가능한 장면이 없습니다")

        # 인트로 추가
        intro_clip = self._create_intro(content_data.get("youtube_title", ""), duration=3)
        video_clips.insert(0, intro_clip)

        # 최종 영상 결합 및 출력
        logger.info(f"🎞️ {len(video_clips)}개 클립을 결합하는 중...")
        final = concatenate_videoclips(video_clips, method="compose")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        temp_audio = os.path.join(os.path.dirname(output_path) or ".", "temp_audio.m4a")
        final.write_videofile(
            output_path,
            fps=self.fps,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            bitrate="8000k",
            threads=4,
            logger=None,
            temp_audiofile=temp_audio,
            remove_temp=False
        )
        
        try:
            final.close()
            # 수동 삭제 시도 (실패해도 무시)
            if os.path.exists(temp_audio):
                os.remove(temp_audio)
        except Exception:
            pass

        logger.info(f"✅ 최종 영상 저장: {output_path} ({final.duration:.1f}초)")
        return output_path

    def _prepare_background(
        self,
        scene_num: int,
        article_images: list,
        scenes: list,
        index: int,
        veo_clips: list = None,
        duration: float = 5.0,
    ):
        """
        장면 배경 클립을 준비합니다.
        우선순위: Veo 영상 클립 → AI 이미지 → 컬러 그라데이션 폴백
        """
        # 1순위: Veo 영상 클립
        if veo_clips:
            for vc in veo_clips:
                if vc.get("scene_num") == scene_num and vc.get("clip_path"):
                    try:
                        main_clip = VideoFileClip(vc["clip_path"])
                        main_clip = main_clip.resized((self.width, self.height))
                        
                        # 영상 길이(duration)가 충분하고(15초 이상), 기사 이미지가 있으면 믹스 모드!
                        if article_images and duration > 15:
                            clips = []
                            # 처음 시작은 고품질 AI 영상으로 이목 끌기 (최대 8초)
                            first_part = min(main_clip.duration, 8.0)
                            clips.append(main_clip.subclipped(0, first_part))
                            
                            current_time = first_part
                            img_index = 0
                            
                            # 남은 시간을 이미지 4초 / 영상 루프 4초 번갈아가며 채우기
                            while current_time < duration:
                                remaining = duration - current_time
                                
                                # 1. 원본 기사 이미지 보여주기
                                if img_index < len(article_images):
                                    img_path = article_images[img_index]
                                    if os.path.exists(img_path):
                                        img_dur = min(4.0, remaining)
                                        try:
                                            img = Image.open(img_path).convert("RGB")
                                            img = img.resize((self.width, self.height), Image.LANCZOS)
                                            iclip = ImageClip(np.array(img), duration=img_dur)
                                            clips.append(iclip)
                                            current_time += img_dur
                                            remaining -= img_dur
                                        except Exception:
                                            pass
                                    img_index += 1
                                
                                # 2. 남은 시간이 있다면 다시 AI 영상을 루프 (트랜지션 느낌)
                                if remaining > 0:
                                    vid_dur = min(4.0, remaining)
                                    import moviepy.video.fx as vfx
                                    clips.append(main_clip.with_effects([vfx.Loop(duration=vid_dur)]))
                                    current_time += vid_dur
                            
                            from moviepy import concatenate_videoclips
                            mixed_clip = concatenate_videoclips(clips, method="compose")
                            logger.info(f"  🎬 장면 {scene_num}: 영상({first_part}s) + 기사 이미지 믹스 적용!")
                            return mixed_clip
                            
                        # 믹스 모드가 아니라면 기존대로 무한 루프
                        if main_clip.duration < duration:
                            import moviepy.video.fx as vfx
                            main_clip = main_clip.with_effects([vfx.Loop(duration=duration)])
                        else:
                            main_clip = main_clip.subclipped(0, duration)
                        logger.info(f"  🎬 장면 {scene_num}: 단일 영상 반복(Loop) 사용")
                        return main_clip
                    except Exception as e:
                        logger.warning(f"  ⚠️ Veo 클립 로드 실패: {e}")

        # 2순위: AI 이미지
        if index < len(article_images):
            img_path = article_images[index]
            if os.path.exists(img_path):
                try:
                    img = Image.open(img_path).convert("RGB")
                    img = img.resize((self.width, self.height), Image.LANCZOS)
                    clip = ImageClip(np.array(img), duration=duration)
                    logger.info(f"  🖼️ 장면 {scene_num}: AI 이미지 사용")
                    return clip
                except Exception as e:
                    logger.warning(f"  ⚠️ 이미지 로드 실패: {e}")

        # 3순위: 컬러 그라데이션 폴백
        logger.warning(f"  ⚠️ 장면 {scene_num}: 폴백 그라데이션 배경 사용")
        return self._create_color_background(scene_num, duration)

    def _create_color_background(self, scene_num: int, duration: float = 5.0) -> ImageClip:
        """컬러 그라데이션 폴백 배경"""
        themes = [
            [(25, 25, 60), (50, 20, 80)],
            [(20, 40, 80), (60, 30, 60)],
            [(30, 50, 70), (20, 30, 50)],
            [(40, 20, 60), (20, 40, 70)],
            [(20, 50, 50), (40, 20, 60)],
        ]
        colors = themes[(scene_num - 1) % len(themes)]
        img = Image.new("RGB", (self.width, self.height))
        draw = ImageDraw.Draw(img)
        for y in range(self.height):
            r = int(colors[0][0] + (colors[1][0] - colors[0][0]) * y / self.height)
            g = int(colors[0][1] + (colors[1][1] - colors[0][1]) * y / self.height)
            b = int(colors[0][2] + (colors[1][2] - colors[0][2]) * y / self.height)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))
        clip = ImageClip(np.array(img), duration=duration)
        return clip

    def _create_subtitle_frame(self, text: str):
        """프리미엄 스타일 자막 오버레이 생성 (투명 레이어)"""
        overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        font = self._get_font(48, bold=True)

        # 자막 줄바꿈 처리
        max_chars_per_line = 18 if self.width < self.height else 28
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test = f"{current_line} {word}".strip()
            if len(test) <= max_chars_per_line:
                current_line = f"{current_line} {word}".strip()
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        # 최대 3줄 표시
        display_lines = lines[:3]
        text = "\n".join(display_lines)

        bbox = draw.textbbox((0, 0), text, font=font, align="center")
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        x = (self.width - text_w) // 2
        # 자막을 화면 중앙보다 살짝 아래로 (원래 하단에 있던 것을 위로 올림)
        y = (self.height - text_h) // 2 + (100 if self.width < self.height else 50)

        # 프리미엄 텍스트 스타일링 (외곽선 + 그림자)
        shadow_offset = 4
        # 부드러운 그림자 효과를 위해 두 번 렌더링 (그림자 영역 확장)
        draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=(0, 0, 0, 150), align="center", stroke_width=6, stroke_fill=(0, 0, 0, 150))
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 255), stroke_width=5, stroke_fill=(0, 0, 0, 255), align="center")

        return np.array(overlay)

    def _create_intro(self, title: str, duration: float = 3) -> ImageClip:
        """세련되고 프리미엄한 인트로 장면 생성"""
        img = Image.new("RGB", (self.width, self.height), (10, 10, 20))
        draw = ImageDraw.Draw(img)

        # 1. 고급스러운 방사형(Radial) 그라데이션 배경 (다크 퍼플 -> 블랙)
        center_x, center_y = self.width // 2, self.height // 2
        max_radius = int((self.width**2 + self.height**2)**0.5 / 2)
        
        for y in range(self.height):
            for x in range(self.width):
                dist = ((x - center_x)**2 + (y - center_y)**2)**0.5
                ratio = dist / max_radius
                # 색상 혼합: 퍼플 (60, 20, 100) -> 다크 (10, 10, 15)
                r = int(60 * (1 - ratio) + 10 * ratio)
                g = int(20 * (1 - ratio) + 10 * ratio)
                b = int(100 * (1 - ratio) + 15 * ratio)
                # 성능을 위해 픽셀 단위 조작 대신 그라데이션 라인/원 등을 사용하는 것이 좋으나
                # 이 함수는 단 한 프레임만 그리므로 픽셀 단위도 금방 끝납니다.
                
        # (최적화를 위해 위의 픽셀 단위 처리는 주석처리하고, Y축 리니어 그라데이션에 오버레이를 씁니다)
        for y in range(self.height):
            ratio = y / self.height
            # 상단(퍼플) -> 하단(진한 블랙퍼플)
            r = int(50 - 40 * ratio)
            g = int(20 - 15 * ratio)
            b = int(80 - 60 * ratio)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))

        # 2. 장식용 빛(Glow) 효과 (좌측 상단, 우측 하단)
        draw.ellipse([(-200, -200), (600, 600)], fill=(124, 58, 237, 30))
        draw.ellipse([(self.width-500, self.height-500), (self.width+200, self.height+200)], fill=(236, 72, 153, 30))

        # 3. 'HOT ISSUE' 뱃지 (상단 중앙)
        badge_font = self._get_font(32, bold=True)
        badge_text = "🔥 HOT ISSUE"
        bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
        bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        bx, by = (self.width - bw) // 2, self.height // 2 - 180
        
        # 뱃지 배경 (둥근 사각형 효과를 위해 폴리곤이나 타원+사각형)
        draw.rounded_rectangle([bx - 20, by - 10, bx + bw + 20, by + bh + 15], radius=15, fill=(239, 68, 68))
        draw.text((bx, by), badge_text, font=badge_font, fill=(255, 255, 255))

        # 4. 메인 제목 텍스트 (그림자 + 그라데이션 느낌 텍스트)
        font = self._get_font(75, bold=True)
        
        # 텍스트 줄바꿈 로직 (화면 너비의 80%를 넘지 않도록)
        words = title.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = f"{current_line} {word}".strip()
            test_w = draw.textbbox((0, 0), test_line, font=font)[2]
            if test_w <= self.width * 0.8:
                current_line = test_line
            else:
                if current_line: lines.append(current_line)
                current_line = word
        if current_line: lines.append(current_line)

        # 줄 간격 및 시작 Y 위치 계산
        line_height = 100
        total_h = len(lines) * line_height
        y_start = (self.height - total_h) // 2 + 40

        for i, line in enumerate(lines):
            l_bbox = draw.textbbox((0, 0), line, font=font)
            text_w = l_bbox[2] - l_bbox[0]
            x = (self.width - text_w) // 2
            y = y_start + i * line_height
            
            # 부드러운 그림자 (검은색)
            draw.text((x+5, y+5), line, font=font, fill=(0, 0, 0, 180))
            draw.text((x+2, y+2), line, font=font, fill=(0, 0, 0, 200))
            
            # 메인 텍스트 (흰색)
            draw.text((x, y), line, font=font, fill=(255, 255, 255))
            
        # 5. 하단 꾸밈 선 (Accent Line)
        line_w = 400
        line_x = (self.width - line_w) // 2
        line_y = y_start + total_h + 60
        draw.rectangle([line_x, line_y, line_x + line_w, line_y + 6], fill=(168, 85, 247))

        clip = ImageClip(np.array(img), duration=duration)
        return clip

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        """프리미엄 한국어 폰트 로드"""
        base_dir = os.path.dirname(os.path.dirname(__file__))
        local_font_eb = os.path.join(base_dir, "assets", "fonts", "NanumSquareEB.ttf")
        local_font_b = os.path.join(base_dir, "assets", "fonts", "NanumSquareB.ttf")
        
        font_candidates = [
            local_font_eb if bold else local_font_b,
            local_font_b,
            "C:/Windows/Fonts/NanumSquareEB.ttf" if bold else "C:/Windows/Fonts/NanumSquareB.ttf",
            "C:/Windows/Fonts/NanumSquareB.ttf",
            "C:/Windows/Fonts/NanumSquareR.ttf",
            "C:/Windows/Fonts/NotoSansKR-Bold.otf",
            "C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf",
        ]
        for path in font_candidates:
            try:
                return ImageFont.truetype(path, size)
            except (IOError, OSError):
                continue

        return ImageFont.load_default()