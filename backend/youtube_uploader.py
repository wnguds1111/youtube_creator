"""
AutoTube - YouTube Auto Uploader
YouTube Data API v3를 사용해 영상을 자동 업로드하는 모듈

초기 설정:
1. Google Cloud Console에서 프로젝트 생성
2. YouTube Data API v3 활성화
3. OAuth 2.0 클라이언트 ID 생성 (데스크톱 앱)
4. client_secrets.json 다운로드 후 backend/ 폴더에 배치
"""

import os
import pickle
import logging
import httplib2
from pathlib import Path

logger = logging.getLogger(__name__)

# OAuth 스코프
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

# 토큰 저장 경로
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "youtube_token.pickle")


class YouTubeUploader:
    """YouTube Data API v3로 영상, 썸네일, 자막을 자동 업로드"""

    def __init__(self, client_secrets_path: str = None):
        """
        Args:
            client_secrets_path: OAuth 클라이언트 시크릿 JSON 파일 경로
                                 기본값: backend/client_secrets.json
        """
        import base64
        self.client_secrets = client_secrets_path or os.path.join(
            os.path.dirname(__file__), "client_secrets.json"
        )
        self.service = None
        
        # Railway 등 환경 변수에서 값 주입 처리
        client_secrets_env = os.getenv("YOUTUBE_CLIENT_SECRETS_JSON")
        if client_secrets_env and not os.path.exists(self.client_secrets):
            with open(self.client_secrets, "w", encoding="utf-8") as f:
                f.write(client_secrets_env)
                
        token_path = os.path.join(os.path.dirname(__file__), "youtube_token.pickle")
        token_base64_env = os.getenv("YOUTUBE_TOKEN_BASE64")
        if token_base64_env and not os.path.exists(token_path):
            with open(token_path, "wb") as f:
                f.write(base64.b64decode(token_base64_env))

        self._is_configured = os.path.exists(self.client_secrets) and os.path.exists(token_path)

        if self._is_configured:
            logger.info("📤 YouTubeUploader 초기화")
        else:
            logger.warning(f"⚠️ YouTube 업로드 미설정: {self.client_secrets} 또는 token.pickle 없음")

    @property
    def is_configured(self) -> bool:
        """YouTube 업로드가 설정되었는지 확인"""
        return self._is_configured

    def authenticate(self) -> bool:
        """OAuth 인증 수행 (최초 1회 브라우저 로그인 필요)"""
        if not self._is_configured:
            logger.error("❌ client_secrets.json이 없습니다")
            return False

        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds = None

            # 저장된 토큰 로드
            if os.path.exists(TOKEN_PATH):
                with open(TOKEN_PATH, "rb") as f:
                    creds = pickle.load(f)

            # 토큰이 없거나 만료된 경우
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    logger.info("🔄 토큰 갱신 중...")
                    creds.refresh(Request())
                else:
                    logger.info("🔐 브라우저에서 YouTube 로그인을 완료해주세요...")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.client_secrets, YOUTUBE_SCOPES
                    )
                    creds = flow.run_local_server(port=8599, open_browser=True)

                # 토큰 저장
                with open(TOKEN_PATH, "wb") as f:
                    pickle.dump(creds, f)
                logger.info("✅ YouTube 인증 완료 (토큰 저장됨)")

            self.service = build("youtube", "v3", credentials=creds)
            return True

        except Exception as e:
            logger.error(f"❌ YouTube 인증 실패: {e}")
            return False

    def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list = None,
        hashtags: list = None,
        thumbnail_path: str = None,
        subtitle_path: str = None,
        privacy: str = "private",
        category_id: str = "25",
    ) -> dict:
        """
        영상을 YouTube에 업로드합니다.

        Args:
            video_path: 영상 파일 경로
            title: 영상 제목
            description: 영상 설명
            tags: SEO 태그 리스트
            hashtags: 해시태그 리스트 (설명에 추가)
            thumbnail_path: 썸네일 이미지 경로
            subtitle_path: SRT 자막 파일 경로
            privacy: "private", "unlisted", "public"
            category_id: 유튜브 카테고리 (25=뉴스/정치, 22=인물/블로그, 28=과학기술)

        Returns:
            dict: {"video_id": str, "url": str, "status": str}
        """
        if not self.service:
            if not self.authenticate():
                return {"status": "error", "error": "인증 실패"}

        try:
            from googleapiclient.http import MediaFileUpload

            # 해시태그를 설명에 추가
            full_description = description
            if hashtags:
                full_description += "\n\n" + " ".join(hashtags)

            # 영상 메타데이터
            body = {
                "snippet": {
                    "title": title[:100],  # 유튜브 제한
                    "description": full_description[:5000],
                    "tags": (tags or [])[:500],
                    "categoryId": category_id,
                    "defaultLanguage": "ko",
                    "defaultAudioLanguage": "ko",
                },
                "status": {
                    "privacyStatus": privacy,
                    "selfDeclaredMadeForKids": False,
                },
            }

            # 영상 업로드
            logger.info(f"📤 YouTube 업로드 시작: '{title}'")
            media = MediaFileUpload(
                video_path,
                mimetype="video/mp4",
                resumable=True,
                chunksize=1024 * 1024 * 10,  # 10MB 청크
            )

            request = self.service.videos().insert(
                part=",".join(body.keys()),
                body=body,
                media_body=media,
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    logger.info(f"  📤 업로드 진행: {progress}%")

            video_id = response["id"]
            video_url = f"https://youtu.be/{video_id}"
            logger.info(f"✅ 영상 업로드 완료: {video_url}")

            # 썸네일 업로드
            if thumbnail_path and os.path.exists(thumbnail_path):
                try:
                    self.service.thumbnails().set(
                        videoId=video_id,
                        media_body=MediaFileUpload(thumbnail_path, mimetype="image/png"),
                    ).execute()
                    logger.info("  ✅ 썸네일 설정 완료")
                except Exception as e:
                    logger.warning(f"  ⚠️ 썸네일 설정 실패: {e}")

            # 자막 업로드
            if subtitle_path and os.path.exists(subtitle_path):
                try:
                    self.service.captions().insert(
                        part="snippet",
                        body={
                            "snippet": {
                                "videoId": video_id,
                                "language": "ko",
                                "name": "한국어 자막",
                            }
                        },
                        media_body=MediaFileUpload(subtitle_path, mimetype="application/x-subrip"),
                    ).execute()
                    logger.info("  ✅ 자막 업로드 완료")
                except Exception as e:
                    logger.warning(f"  ⚠️ 자막 업로드 실패: {e}")

            return {
                "status": "success",
                "video_id": video_id,
                "url": video_url,
                "privacy": privacy,
            }

        except Exception as e:
            logger.error(f"❌ YouTube 업로드 실패: {e}")
            return {"status": "error", "error": str(e)}

    def get_channel_info(self) -> dict | None:
        """인증된 채널 정보 조회"""
        if not self.service:
            if not self.authenticate():
                return None

        try:
            response = self.service.channels().list(
                part="snippet,statistics",
                mine=True,
            ).execute()

            if response.get("items"):
                channel = response["items"][0]
                return {
                    "id": channel["id"],
                    "title": channel["snippet"]["title"],
                    "subscribers": channel["statistics"].get("subscriberCount", "0"),
                    "videos": channel["statistics"].get("videoCount", "0"),
                }
        except Exception as e:
            logger.error(f"❌ 채널 정보 조회 실패: {e}")

        return None
