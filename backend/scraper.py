"""
AutoTube - Article Scraper
기사 URL에서 제목, 본문, 이미지를 추출하는 모듈
"""

import requests
from newspaper import Article
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
import logging

logger = logging.getLogger(__name__)


class ArticleScraper:
    """뉴스/블로그 기사에서 콘텐츠를 추출"""

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }

    def __init__(self, language: str = "ko"):
        self.language = language

    def extract(self, url: str) -> dict:
        """
        URL에서 기사 콘텐츠를 추출합니다.

        Returns:
            dict: {
                "url": str,
                "title": str,
                "text": str,
                "summary": str,
                "authors": list[str],
                "publish_date": str | None,
                "top_image": str | None,
                "images": list[str],
                "keywords": list[str],
                "source_name": str
            }
        """
        logger.info(f"🔍 기사 추출 시작: {url}")

        try:
            # newspaper3k로 기사 파싱
            article = Article(url, language=self.language)
            article.download()
            article.parse()

            try:
                article.nlp()
            except Exception:
                pass

            # 추가 이미지 수집 (newspaper3k가 놓칠 수 있는 이미지)
            extra_images = self._extract_extra_images(url)

            # 모든 이미지 통합 (중복 제거)
            all_images = list(dict.fromkeys(
                [img for img in [article.top_image] + list(article.images) + extra_images
                 if img and self._is_valid_image(img)]
            ))

            # 소스명 추출
            parsed = urlparse(url)
            source_name = parsed.netloc.replace("www.", "")

            result = {
                "url": url,
                "title": article.title or "제목 없음",
                "text": article.text or "",
                "summary": article.summary if hasattr(article, 'summary') and article.summary else "",
                "authors": article.authors or [],
                "publish_date": str(article.publish_date) if article.publish_date else None,
                "top_image": article.top_image,
                "images": all_images[:10],  # 최대 10개
                "keywords": article.keywords if hasattr(article, 'keywords') else [],
                "source_name": source_name,
            }

            logger.info(f"✅ 기사 추출 완료: '{result['title']}' (이미지 {len(result['images'])}개)")
            return result

        except Exception as e:
            logger.error(f"❌ 기사 추출 실패: {e}")
            # 폴백: requests + BeautifulSoup으로 시도
            return self._fallback_extract(url)

    def _fallback_extract(self, url: str) -> dict:
        """newspaper3k 실패 시 BeautifulSoup으로 폴백"""
        logger.info("📎 폴백 추출 모드 시작...")

        try:
            resp = requests.get(url, headers=self.HEADERS, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # 제목 추출
            title = ""
            for tag in [soup.find("h1"), soup.find("title")]:
                if tag:
                    title = tag.get_text(strip=True)
                    break

            # 본문 추출 (article 태그 우선, 없으면 큰 p 태그들)
            text = ""
            article_tag = soup.find("article")
            if article_tag:
                paragraphs = article_tag.find_all("p")
            else:
                paragraphs = soup.find_all("p")

            text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20)

            # 이미지 추출
            images = self._extract_extra_images(url, soup=soup)

            parsed = urlparse(url)
            source_name = parsed.netloc.replace("www.", "")

            return {
                "url": url,
                "title": title or "제목 없음",
                "text": text,
                "summary": text[:300] if text else "",
                "authors": [],
                "publish_date": None,
                "top_image": images[0] if images else None,
                "images": images[:10],
                "keywords": [],
                "source_name": source_name,
            }
        except Exception as e:
            logger.error(f"❌ 폴백 추출도 실패: {e}")
            raise ValueError(f"기사를 추출할 수 없습니다: {url}")

    def _extract_extra_images(self, url: str, soup=None) -> list:
        """페이지에서 고품질 이미지 URL을 추가로 추출"""
        if soup is None:
            try:
                resp = requests.get(url, headers=self.HEADERS, timeout=10)
                soup = BeautifulSoup(resp.text, "lxml")
            except Exception:
                return []

        images = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src:
                src = urljoin(url, src)
                if self._is_valid_image(src):
                    images.append(src)

        # og:image 메타 태그
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            images.insert(0, og_image["content"])

        return images

    @staticmethod
    def _is_valid_image(url: str) -> bool:
        """유효한 콘텐츠 이미지인지 확인 (아이콘/광고 제외)"""
        if not url:
            return False

        # 너무 작은 이미지나 아이콘 제외
        exclude_patterns = [
            r'icon', r'logo', r'avatar', r'badge', r'button',
            r'banner.*ad', r'advert', r'tracker', r'pixel',
            r'1x1', r'spacer', r'blank', r'emoji',
            r'\.gif$', r'\.svg$'
        ]
        url_lower = url.lower()
        for pattern in exclude_patterns:
            if re.search(pattern, url_lower):
                return False

        return True
