"""
AutoTube - Imagen AI Image Generator
Gemini/Imagen API를 사용해 장면 배경 이미지와 썸네일을 AI로 생성하는 모듈
"""

import os
import logging
from pathlib import Path
from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import textwrap

logger = logging.getLogger(__name__)

# Imagen 모델 후보
IMAGEN_MODELS = [
    "imagen-3.0-generate-002",
    "imagen-3.0-generate-001",
]


class ImageGenerator:
    """Imagen API로 AI 이미지를 생성"""

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.model = IMAGEN_MODELS[0]
        self.assets_dir = os.path.join(os.path.dirname(__file__), "..", "assets")
        logger.info(f"🖼️ ImageGenerator 초기화 (모델: {self.model})")

    def generate_scene_images(self, scenes: list, output_dir: str) -> list:
        """
        각 장면의 visual_prompt로 AI 배경 이미지를 생성합니다.

        Returns:
            list: [{"scene_num": 1, "image_path": "..."}, ...]
        """
        logger.info(f"🖼️ 장면 이미지 AI 생성 시작 ({len(scenes)}개 장면)")
        images_dir = os.path.join(output_dir, "images")
        os.makedirs(images_dir, exist_ok=True)

        results = []
        for scene in scenes:
            scene_num = scene["scene_num"]
            prompt = scene.get("visual_prompt", "")

            if not prompt:
                prompt = "Modern news broadcast studio with blue lighting and digital screens"

            output_path = os.path.join(images_dir, f"scene_{scene_num:02d}.png")

            try:
                # 16:9 비율로 생성
                enhanced_prompt = f"{prompt}, cinematic lighting, high quality, 16:9 aspect ratio, photorealistic"

                response = self.client.models.generate_images(
                    model=self.model,
                    prompt=enhanced_prompt,
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio="16:9",
                        safety_filter_level="BLOCK_ONLY_HIGH",
                    ),
                )

                if response.generated_images:
                    image_bytes = response.generated_images[0].image.image_bytes
                    with open(output_path, "wb") as f:
                        f.write(image_bytes)
                    logger.info(f"  ✅ 장면 {scene_num}: AI 이미지 생성 완료")
                else:
                    logger.warning(f"  ⚠️ 장면 {scene_num}: 이미지 생성 결과 없음, 폴백")
                    self._create_fallback_image(output_path, scene_num)

            except Exception as e:
                logger.warning(f"  ⚠️ 장면 {scene_num} Imagen 실패: {e}, 폴백 사용")
                self._create_fallback_image(output_path, scene_num)

            results.append({
                "scene_num": scene_num,
                "image_path": output_path,
            })

        return results

    def generate_thumbnail(
        self,
        main_text: str,
        subtitle: str,
        article_topic: str,
        output_path: str,
    ) -> str:
        """
        AI로 썸네일 배경을 생성하고 텍스트를 오버레이합니다.

        Returns:
            str: 생성된 썸네일 파일 경로
        """
        logger.info(f"🎨 AI 썸네일 생성: '{main_text}'")

        try:
            # 배경 이미지 AI 생성
            bg_prompt = (
                f"YouTube thumbnail background about {article_topic}, "
                f"dramatic lighting, vibrant colors, eye-catching, "
                f"no text, no letters, cinematic, 16:9"
            )

            response = self.client.models.generate_images(
                model=self.model,
                prompt=bg_prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="16:9",
                    safety_filter_level="BLOCK_ONLY_HIGH",
                ),
            )

            if response.generated_images:
                image_bytes = response.generated_images[0].image.image_bytes
                bg_img = Image.open(BytesIO(image_bytes)).convert("RGB")
                bg_img = bg_img.resize((1280, 720), Image.LANCZOS)
            else:
                bg_img = self._create_gradient_bg()

        except Exception as e:
            logger.warning(f"  ⚠️ Imagen 썸네일 배경 실패: {e}, 그라데이션 사용")
            bg_img = self._create_gradient_bg()

        # 오버레이 (어둡게)
        bg_img = self._apply_overlay(bg_img)

        # 텍스트 렌더링
        draw = ImageDraw.Draw(bg_img)
        self._draw_thumbnail_text(draw, main_text, subtitle)
        self._add_decorations(draw)

        # 저장
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        bg_img.save(output_path, "PNG", quality=95)
        logger.info(f"  ✅ 썸네일 저장: {output_path}")
        return output_path

    def _create_fallback_image(self, path: str, scene_num: int):
        """Imagen 실패 시 그라데이션 폴백"""
        themes = [
            [(25, 25, 60), (50, 20, 80)],
            [(20, 40, 80), (60, 30, 60)],
            [(30, 50, 70), (20, 30, 50)],
            [(40, 20, 60), (20, 40, 70)],
            [(20, 50, 50), (40, 20, 60)],
        ]
        colors = themes[(scene_num - 1) % len(themes)]
        img = Image.new("RGB", (1920, 1080))
        draw = ImageDraw.Draw(img)
        for y in range(1080):
            r = int(colors[0][0] + (colors[1][0] - colors[0][0]) * y / 1080)
            g = int(colors[0][1] + (colors[1][1] - colors[0][1]) * y / 1080)
            b = int(colors[0][2] + (colors[1][2] - colors[0][2]) * y / 1080)
            draw.line([(0, y), (1920, y)], fill=(r, g, b))
        img.save(path, "PNG")

    def _create_gradient_bg(self) -> Image.Image:
        """그라데이션 배경"""
        img = Image.new("RGB", (1280, 720))
        draw = ImageDraw.Draw(img)
        for y in range(720):
            ratio = y / 720
            r = int(40 * (1 - ratio) + 20 * ratio)
            g = int(20 * (1 - ratio) + 10 * ratio)
            b = int(80 * (1 - ratio) + 50 * ratio)
            draw.line([(0, y), (1280, y)], fill=(r, g, b))
        return img

    def _apply_overlay(self, img: Image.Image) -> Image.Image:
        """반투명 어두운 오버레이"""
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.55)

        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for y in range(img.size[1]):
            alpha = int(160 * (y / img.size[1]))
            draw.line([(0, y), (img.size[0], y)], fill=(0, 0, 0, alpha))
        img = img.convert("RGBA")
        img = Image.alpha_composite(img, overlay)
        return img.convert("RGB")

    def _draw_thumbnail_text(self, draw: ImageDraw.Draw, main_text: str, subtitle: str):
        """썸네일에 텍스트 렌더링"""
        main_font = self._get_font(90, bold=True)
        lines = textwrap.wrap(main_text, width=12)

        line_height = 100
        total_h = len(lines) * line_height
        y_start = (720 - total_h) // 2 - 20

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=main_font)
            x = (1280 - (bbox[2] - bbox[0])) // 2
            y = y_start + i * line_height
            draw.text((x, y), line, font=main_font, fill=(255, 255, 255),
                       stroke_width=6, stroke_fill=(0, 0, 0))

        if subtitle:
            sub_font = self._get_font(42, bold=False)
            bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
            x = (1280 - (bbox[2] - bbox[0])) // 2
            y = y_start + len(lines) * line_height + 10
            draw.text((x, y), subtitle, font=sub_font, fill=(255, 220, 50),
                       stroke_width=3, stroke_fill=(0, 0, 0))

    def _add_decorations(self, draw: ImageDraw.Draw):
        """장식 요소"""
        accent = (255, 60, 60)
        draw.rectangle([(0, 0), (8, 720)], fill=accent)
        draw.rectangle([(0, 714), (1280, 720)], fill=accent)

        badge_font = self._get_font(28, bold=True)
        badge_text = "NEW"
        bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
        bw = bbox[2] - bbox[0] + 30
        bh = bbox[3] - bbox[1] + 16
        bx, by = 1280 - bw - 30, 30
        draw.rounded_rectangle([(bx, by), (bx + bw, by + bh)], radius=8, fill=accent)
        draw.text((bx + 15, by + 5), badge_text, font=badge_font, fill=(255, 255, 255))

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        """한국어 폰트 로드"""
        candidates = [
            os.path.join(self.assets_dir, "fonts", "NanumGothicBold.ttf"),
            "C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf",
            "C:/Windows/Fonts/gulim.ttc",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except (IOError, OSError):
                continue
        return ImageFont.load_default()
