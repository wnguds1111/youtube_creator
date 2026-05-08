"""
AutoTube - Thumbnail Creator
AI 기반 유튜브 썸네일 자동 생성 모듈
"""

import os
import requests
import logging
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import textwrap

logger = logging.getLogger(__name__)


class ThumbnailCreator:
    """유튜브 썸네일 이미지를 자동 생성"""

    # 유튜브 썸네일 크기
    WIDTH = 1280
    HEIGHT = 720

    # 그라데이션 컬러 프리셋
    GRADIENT_PRESETS = {
        "hot": [(220, 40, 40), (180, 30, 80)],
        "breaking": [(200, 20, 20), (30, 30, 30)],
        "tech": [(20, 60, 150), (80, 40, 180)],
        "economy": [(20, 100, 60), (30, 60, 120)],
        "world": [(30, 50, 120), (100, 20, 80)],
        "default": [(40, 40, 80), (20, 20, 50)],
    }

    def __init__(self, assets_dir: str = None):
        self.assets_dir = assets_dir or os.path.join(os.path.dirname(__file__), "..", "assets")

    def create(
        self,
        main_text: str,
        subtitle: str = "",
        background_image_url: str = None,
        output_path: str = "thumbnail.png",
        theme: str = "default",
    ) -> str:
        """
        유튜브 썸네일을 생성합니다.

        Args:
            main_text: 메인 텍스트 (큰 글씨)
            subtitle: 서브 텍스트 (작은 글씨)
            background_image_url: 배경 이미지 URL (없으면 그라데이션)
            output_path: 저장 경로
            theme: 컬러 테마

        Returns:
            str: 생성된 썸네일 파일 경로
        """
        logger.info(f"🎨 썸네일 생성: '{main_text}'")

        # 1. 배경 이미지 준비
        if background_image_url:
            bg = self._load_background_image(background_image_url)
        else:
            bg = self._create_gradient_background(theme)

        # 2. 오버레이 효과
        bg = self._apply_overlay(bg, theme)

        # 3. 텍스트 배치
        draw = ImageDraw.Draw(bg)

        # 메인 텍스트 (큰 글씨)
        main_font = self._get_font(size=90, bold=True)
        self._draw_text_with_stroke(
            draw, main_text, main_font,
            position="center",
            stroke_width=6,
            text_color=(255, 255, 255),
            stroke_color=(0, 0, 0),
        )

        # 서브 텍스트
        if subtitle:
            sub_font = self._get_font(size=42, bold=False)
            self._draw_text_with_stroke(
                draw, subtitle, sub_font,
                position="bottom",
                stroke_width=3,
                text_color=(255, 220, 50),
                stroke_color=(0, 0, 0),
            )

        # 4. 장식 요소
        self._add_decorations(draw, theme)

        # 5. 저장
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        bg.save(output_path, "PNG", quality=95)

        logger.info(f"✅ 썸네일 저장: {output_path}")
        return output_path

    def _load_background_image(self, url: str) -> Image.Image:
        """URL에서 배경 이미지를 다운로드하고 크롭"""
        try:
            resp = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0"
            })
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")

            # 1280x720 비율로 크롭
            target_ratio = self.WIDTH / self.HEIGHT
            img_ratio = img.width / img.height

            if img_ratio > target_ratio:
                new_width = int(img.height * target_ratio)
                left = (img.width - new_width) // 2
                img = img.crop((left, 0, left + new_width, img.height))
            else:
                new_height = int(img.width / target_ratio)
                top = (img.height - new_height) // 2
                img = img.crop((0, top, img.width, top + new_height))

            img = img.resize((self.WIDTH, self.HEIGHT), Image.LANCZOS)

            # 약간 어둡게 + 블러 처리
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(0.5)
            img = img.filter(ImageFilter.GaussianBlur(radius=3))

            return img

        except Exception as e:
            logger.warning(f"⚠️ 배경 이미지 로드 실패: {e}, 그라데이션 사용")
            return self._create_gradient_background("default")

    def _create_gradient_background(self, theme: str) -> Image.Image:
        """그라데이션 배경 생성"""
        colors = self.GRADIENT_PRESETS.get(theme, self.GRADIENT_PRESETS["default"])
        color1, color2 = colors

        img = Image.new("RGB", (self.WIDTH, self.HEIGHT))
        draw = ImageDraw.Draw(img)

        for y in range(self.HEIGHT):
            ratio = y / self.HEIGHT
            r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
            g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
            b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
            draw.line([(0, y), (self.WIDTH, y)], fill=(r, g, b))

        return img

    def _apply_overlay(self, img: Image.Image, theme: str) -> Image.Image:
        """반투명 오버레이 추가"""
        overlay = Image.new("RGBA", (self.WIDTH, self.HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 하단에서 상단으로 그라데이션 오버레이
        for y in range(self.HEIGHT):
            alpha = int(180 * (y / self.HEIGHT))
            draw.line([(0, y), (self.WIDTH, y)], fill=(0, 0, 0, alpha))

        img = img.convert("RGBA")
        img = Image.alpha_composite(img, overlay)
        return img.convert("RGB")

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        """폰트 로드 (시스템 폰트 폴백)"""
        # Windows 한국어 폰트 경로들
        font_candidates = [
            "C:/Windows/Fonts/NanumSquareEB.ttf" if bold else "C:/Windows/Fonts/NanumSquareB.ttf",
            "C:/Windows/Fonts/NanumSquareB.ttf",
            "C:/Windows/Fonts/NanumSquareR.ttf",
            os.path.join(self.assets_dir, "fonts", "NanumSquareB.ttf"),
            "C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf",
        ]

        for font_path in font_candidates:
            try:
                return ImageFont.truetype(font_path, size)
            except (IOError, OSError):
                continue

        logger.warning("⚠️ 한국어 폰트를 찾을 수 없어 기본 폰트 사용")
        return ImageFont.load_default()

    def _draw_text_with_stroke(
        self,
        draw: ImageDraw.Draw,
        text: str,
        font: ImageFont.FreeTypeFont,
        position: str = "center",
        stroke_width: int = 4,
        text_color: tuple = (255, 255, 255),
        stroke_color: tuple = (0, 0, 0),
    ):
        """테두리가 있는 텍스트 렌더링"""
        # 텍스트 줄바꿈 (한 줄에 너무 길면)
        max_chars = 12
        lines = textwrap.wrap(text, width=max_chars)
        if not lines:
            return

        line_height = font.size + 10
        total_text_height = line_height * len(lines)

        if position == "center":
            y_start = (self.HEIGHT - total_text_height) // 2 - 20
        elif position == "bottom":
            y_start = self.HEIGHT - total_text_height - 80
        else:
            y_start = 60

        for i, line in enumerate(lines):
            # 텍스트 크기 계산
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (self.WIDTH - text_width) // 2
            y = y_start + i * line_height

            # 테두리 (stroke)
            draw.text(
                (x, y), line, font=font,
                fill=text_color,
                stroke_width=stroke_width,
                stroke_fill=stroke_color,
            )

    def _add_decorations(self, draw: ImageDraw.Draw, theme: str):
        """장식 요소 추가 (모서리 강조, 로고 등)"""
        accent_color = {
            "hot": (255, 60, 60),
            "breaking": (255, 30, 30),
            "tech": (60, 140, 255),
            "economy": (50, 200, 100),
            "world": (100, 80, 220),
            "default": (255, 200, 50),
        }.get(theme, (255, 200, 50))

        # 상단 좌측 강조 바
        draw.rectangle([(0, 0), (8, self.HEIGHT)], fill=accent_color)

        # 하단 강조 라인
        draw.rectangle([(0, self.HEIGHT - 6), (self.WIDTH, self.HEIGHT)], fill=accent_color)

        # 상단 우측 "NEW" 또는 "속보" 배지
        badge_font = self._get_font(size=28, bold=True)
        badge_text = "NEW"
        badge_bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
        badge_w = badge_bbox[2] - badge_bbox[0] + 30
        badge_h = badge_bbox[3] - badge_bbox[1] + 16

        badge_x = self.WIDTH - badge_w - 30
        badge_y = 30
        draw.rounded_rectangle(
            [(badge_x, badge_y), (badge_x + badge_w, badge_y + badge_h)],
            radius=8,
            fill=accent_color,
        )
        draw.text(
            (badge_x + 15, badge_y + 5),
            badge_text, font=badge_font,
            fill=(255, 255, 255),
        )
