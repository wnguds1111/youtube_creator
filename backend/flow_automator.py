"""
AutoTube - Flow Automator (Veo Video Generation)
Playwright를 사용하여 Google Flow 웹 UI를 자동화하여
울트라 구독 크레딧으로 Veo 영상 클립을 생성하는 모듈

최초 1회 구글 로그인 필요 → 이후 세션 재사용
"""

import os
import time
import json
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Flow URL
FLOW_URL = "https://labs.google/flow"

# 브라우저 프로필 저장 경로
BROWSER_PROFILE_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "browser_profile")


class FlowAutomator:
    """Google Flow 웹 UI를 Playwright로 자동화하여 Veo 영상 클립 생성"""

    def __init__(self, quality: str = "fast", headless: bool = False):
        """
        Args:
            quality: "fast" (Veo 3.1 Fast, ~20 크레딧) 또는 "quality" (Veo 3.1, ~100 크레딧)
            headless: True면 백그라운드 실행 (첫 로그인 시는 False 필수)
        """
        self.quality = quality
        self.headless = headless
        self.browser = None
        self.context = None
        self.page = None

    async def setup(self):
        """브라우저 초기화 및 Flow 페이지 로드"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("❌ Playwright가 설치되지 않았습니다. 'pip install playwright && playwright install chromium' 실행 필요")
            raise

        os.makedirs(BROWSER_PROFILE_DIR, exist_ok=True)

        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=BROWSER_PROFILE_DIR,
            headless=self.headless,
            viewport={"width": 1920, "height": 1080},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self.page = self.browser.pages[0] if self.browser.pages else await self.browser.new_page()

        logger.info(f"🌐 Flow 페이지 로드 중: {FLOW_URL}")
        await self.page.goto(FLOW_URL, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)

    async def check_auth(self) -> bool:
        """로그인 상태 확인"""
        try:
            # 구글 로그인 페이지로 리다이렉트되었는지 확인
            current_url = self.page.url
            if "accounts.google.com" in current_url:
                logger.warning("⚠️ 구글 로그인이 필요합니다")
                return False
            # Flow 인터페이스 요소가 있는지 확인
            await self.page.wait_for_selector("body", timeout=5000)
            return True
        except Exception:
            return False

    async def wait_for_login(self, timeout_sec: int = 300):
        """사용자가 수동으로 로그인할 때까지 대기"""
        logger.info("🔐 구글 로그인을 완료해주세요... (브라우저 창에서 로그인)")
        start = time.time()
        while time.time() - start < timeout_sec:
            if await self.check_auth():
                logger.info("✅ 로그인 성공!")
                return True
            await asyncio.sleep(3)
        logger.error("❌ 로그인 타임아웃")
        return False

    async def generate_video_clip(
        self,
        prompt: str,
        output_path: str,
        timeout_sec: int = 180,
    ) -> str | None:
        """
        Flow에서 Veo 영상 클립 1개를 생성합니다.

        Args:
            prompt: 영상 생성 프롬프트 (영어)
            output_path: 저장할 파일 경로
            timeout_sec: 생성 대기 최대 시간

        Returns:
            str: 생성된 파일 경로 또는 None (실패 시)
        """
        logger.info(f"  🎬 Veo 클립 생성 중: '{prompt[:50]}...'")

        try:
            # Flow 인터페이스에서 새 영상 생성
            # NOTE: Flow UI가 변경될 수 있어 선택자는 업데이트 필요

            # 1. 프롬프트 입력 영역 찾기
            prompt_input = await self._find_prompt_input()
            if not prompt_input:
                logger.error("  ❌ 프롬프트 입력 영역을 찾을 수 없습니다")
                return None

            # 2. 프롬프트 입력
            await prompt_input.fill("")
            await prompt_input.fill(prompt)
            await asyncio.sleep(1)

            # 3. 생성 버튼 클릭
            generate_btn = await self._find_generate_button()
            if generate_btn:
                await generate_btn.click()
            else:
                # Enter 키로 생성 시도
                await prompt_input.press("Enter")

            # 4. 생성 완료 대기
            logger.info(f"  ⏳ Veo 생성 대기 중... (최대 {timeout_sec}초)")
            video_url = await self._wait_for_video(timeout_sec)

            if video_url:
                # 5. 다운로드
                await self._download_video(video_url, output_path)
                logger.info(f"  ✅ Veo 클립 저장: {output_path}")
                return output_path
            else:
                logger.warning("  ⚠️ 영상 생성 결과를 찾을 수 없습니다")
                return None

        except Exception as e:
            logger.error(f"  ❌ Veo 클립 생성 실패: {e}")
            return None

    async def generate_scene_clips(
        self,
        scenes: list,
        output_dir: str,
    ) -> list:
        """
        여러 장면의 Veo 영상 클립을 순차 생성합니다.

        Returns:
            list: [{"scene_num": 1, "clip_path": "..." or None}, ...]
        """
        clips_dir = os.path.join(output_dir, "veo_clips")
        os.makedirs(clips_dir, exist_ok=True)

        results = []
        for scene in scenes:
            scene_num = scene["scene_num"]
            prompt = scene.get("visual_prompt", "")

            if not prompt:
                results.append({"scene_num": scene_num, "clip_path": None})
                continue

            output_path = os.path.join(clips_dir, f"scene_{scene_num:02d}.mp4")

            clip_path = await self.generate_video_clip(
                prompt=prompt,
                output_path=output_path,
                timeout_sec=180,
            )

            results.append({
                "scene_num": scene_num,
                "clip_path": clip_path,
            })

            # 클립 간 약간의 간격
            await asyncio.sleep(2)

        return results

    async def _find_prompt_input(self):
        """프롬프트 입력 필드 탐색"""
        selectors = [
            'textarea[placeholder*="prompt"]',
            'textarea[placeholder*="Prompt"]',
            'textarea[placeholder*="describe"]',
            'textarea[aria-label*="prompt"]',
            'div[contenteditable="true"]',
            'textarea',
        ]
        for sel in selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=3000)
                if el:
                    return el
            except Exception:
                continue
        return None

    async def _find_generate_button(self):
        """생성 버튼 탐색"""
        selectors = [
            'button:has-text("Generate")',
            'button:has-text("Create")',
            'button:has-text("생성")',
            'button[aria-label*="generate"]',
            'button[aria-label*="Generate"]',
        ]
        for sel in selectors:
            try:
                el = await self.page.wait_for_selector(sel, timeout=2000)
                if el:
                    return el
            except Exception:
                continue
        return None

    async def _wait_for_video(self, timeout_sec: int) -> str | None:
        """영상 생성 완료 대기 및 URL 획득"""
        start = time.time()
        while time.time() - start < timeout_sec:
            try:
                # 비디오 요소 탐색
                video_el = await self.page.query_selector("video source, video[src]")
                if video_el:
                    src = await video_el.get_attribute("src")
                    if src and src.startswith("http"):
                        return src

                # 다운로드 링크 탐색
                download_el = await self.page.query_selector('a[download], a[href*=".mp4"]')
                if download_el:
                    href = await download_el.get_attribute("href")
                    if href:
                        return href

            except Exception:
                pass

            await asyncio.sleep(5)

        return None

    async def _download_video(self, url: str, output_path: str):
        """URL에서 영상 파일 다운로드"""
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(url)
            with open(output_path, "wb") as f:
                f.write(response.content)

    async def close(self):
        """브라우저 정리"""
        if self.browser:
            await self.browser.close()
        if hasattr(self, '_playwright') and self._playwright:
            await self._playwright.stop()
        logger.info("🌐 Flow 브라우저 종료")


def run_flow_generation(scenes: list, output_dir: str, quality: str = "fast") -> list:
    """
    동기 래퍼: Flow를 통해 Veo 클립 생성

    Returns:
        list: [{"scene_num": 1, "clip_path": "..." or None}, ...]
    """
    async def _run():
        automator = FlowAutomator(quality=quality, headless=False)
        try:
            await automator.setup()

            if not await automator.check_auth():
                logged_in = await automator.wait_for_login()
                if not logged_in:
                    return [{"scene_num": s["scene_num"], "clip_path": None} for s in scenes]

            return await automator.generate_scene_clips(scenes, output_dir)
        finally:
            await automator.close()

    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(_run())
    except Exception as e:
        logger.error(f"❌ Flow 자동화 실패: {e}")
        return [{"scene_num": s["scene_num"], "clip_path": None} for s in scenes]
    finally:
        loop.close()
