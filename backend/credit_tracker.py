"""
AutoTube - Credit Tracker
울트라 구독 25,000 크레딧 사용량을 추적하고 잔량을 표시하는 모듈
API 호출마다 예상 크레딧 소모를 기록하여 로컬에서 관리
"""

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# 크레딧 소모 추정치 (모델별)
CREDIT_COSTS = {
    # Gemini 텍스트 생성 (무료 API 사용 시 0, Ultra 사용 시 미미)
    "gemini_text": 0.5,
    # Gemini TTS (장면 1개당)
    "gemini_tts": 2,
    # Imagen 이미지 생성 (1장당)
    "imagen_image": 3,
    # Imagen 썸네일 (1장)
    "imagen_thumbnail": 3,
    # Veo Fast (클립 1개, ~8초)
    "veo_fast": 20,
    # Veo Quality (클립 1개, ~8초)
    "veo_quality": 100,
}

# 크레딧 데이터 저장 경로
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CREDIT_FILE = os.path.join(DATA_DIR, "credit_usage.json")

# 월간 크레딧 한도
MONTHLY_BUDGET = 25000


class CreditTracker:
    """울트라 크레딧 사용량 추적기"""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.data = self._load()
        self._check_monthly_reset()

    def _load(self) -> dict:
        """저장된 크레딧 데이터 로드"""
        if os.path.exists(CREDIT_FILE):
            try:
                with open(CREDIT_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        return self._create_fresh_data()

    def _create_fresh_data(self) -> dict:
        """새 월간 데이터 생성"""
        now = datetime.now()
        return {
            "month": now.strftime("%Y-%m"),
            "total_budget": MONTHLY_BUDGET,
            "used": 0,
            "remaining": MONTHLY_BUDGET,
            "calls": [],
            "summary": {
                "gemini_text": {"count": 0, "credits": 0},
                "gemini_tts": {"count": 0, "credits": 0},
                "imagen_image": {"count": 0, "credits": 0},
                "imagen_thumbnail": {"count": 0, "credits": 0},
                "veo_fast": {"count": 0, "credits": 0},
                "veo_quality": {"count": 0, "credits": 0},
            },
            "videos_created": 0,
            "last_updated": now.isoformat(),
        }

    def _check_monthly_reset(self):
        """월이 바뀌면 자동 리셋"""
        current_month = datetime.now().strftime("%Y-%m")
        if self.data.get("month") != current_month:
            logger.info(f"📅 월간 크레딧 리셋: {self.data.get('month')} → {current_month}")
            # 이전 달 백업
            old_month = self.data.get("month", "unknown")
            backup_path = os.path.join(DATA_DIR, f"credit_usage_{old_month}.json")
            try:
                with open(backup_path, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            self.data = self._create_fresh_data()
            self._save()

    def _save(self):
        """데이터를 파일에 저장"""
        self.data["last_updated"] = datetime.now().isoformat()
        try:
            with open(CREDIT_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"❌ 크레딧 데이터 저장 실패: {e}")

    def record_usage(self, usage_type: str, count: int = 1, description: str = ""):
        """
        API 호출에 대한 크레딧 사용 기록

        Args:
            usage_type: CREDIT_COSTS의 키 (gemini_text, gemini_tts, imagen_image 등)
            count: 호출 횟수
            description: 설명 메모
        """
        cost_per_unit = CREDIT_COSTS.get(usage_type, 0)
        total_cost = cost_per_unit * count

        # 호출 기록 추가 (최근 500개까지만 유지)
        call_record = {
            "type": usage_type,
            "count": count,
            "credits": total_cost,
            "description": description,
            "timestamp": datetime.now().isoformat(),
        }
        self.data["calls"].append(call_record)
        if len(self.data["calls"]) > 500:
            self.data["calls"] = self.data["calls"][-500:]

        # 합계 업데이트
        self.data["used"] += total_cost
        self.data["remaining"] = max(0, self.data["total_budget"] - self.data["used"])

        # 요약 업데이트
        if usage_type in self.data["summary"]:
            self.data["summary"][usage_type]["count"] += count
            self.data["summary"][usage_type]["credits"] += total_cost

        self._save()
        logger.info(f"💳 크레딧 사용: {usage_type} x{count} = {total_cost} 크레딧 (잔여: {self.data['remaining']:.0f})")

    def record_video_created(self):
        """영상 1건 생성 기록"""
        self.data["videos_created"] = self.data.get("videos_created", 0) + 1
        self._save()

    def get_status(self) -> dict:
        """현재 크레딧 상태 반환"""
        self._check_monthly_reset()

        used = self.data["used"]
        remaining = self.data["remaining"]
        budget = self.data["total_budget"]
        pct = (used / budget * 100) if budget > 0 else 0

        # 예상 가능 영상 수 계산
        # 기본 영상 1건 = text(0.5) + tts*5(10) + imagen*5(15) + thumbnail(3) ≈ 29 크레딧
        base_cost_per_video = 29
        veo_cost_per_video = 120  # Fast 기준 6클립

        est_basic = int(remaining / base_cost_per_video) if base_cost_per_video > 0 else 0
        est_veo = int(remaining / (base_cost_per_video + veo_cost_per_video)) if (base_cost_per_video + veo_cost_per_video) > 0 else 0

        return {
            "month": self.data["month"],
            "total_budget": budget,
            "used": round(used, 1),
            "remaining": round(remaining, 1),
            "percentage_used": round(pct, 1),
            "videos_created": self.data.get("videos_created", 0),
            "summary": self.data["summary"],
            "estimates": {
                "basic_videos_remaining": est_basic,
                "veo_videos_remaining": est_veo,
            },
            "last_updated": self.data.get("last_updated", ""),
            "status": "ok" if pct < 80 else ("warning" if pct < 95 else "critical"),
        }

    def get_recent_calls(self, limit: int = 20) -> list:
        """최근 API 호출 내역"""
        return self.data["calls"][-limit:][::-1]

    def estimate_video_cost(self, scene_count: int, use_veo: bool = False, veo_quality: str = "fast") -> dict:
        """영상 1건 예상 크레딧 소모 계산"""
        text_cost = CREDIT_COSTS["gemini_text"]
        tts_cost = CREDIT_COSTS["gemini_tts"] * scene_count
        image_cost = CREDIT_COSTS["imagen_image"] * scene_count
        thumb_cost = CREDIT_COSTS["imagen_thumbnail"]

        veo_cost = 0
        if use_veo:
            veo_type = f"veo_{veo_quality}"
            veo_cost = CREDIT_COSTS.get(veo_type, 20) * scene_count

        total = text_cost + tts_cost + image_cost + thumb_cost + veo_cost

        return {
            "text_generation": text_cost,
            "tts_narration": tts_cost,
            "image_generation": image_cost,
            "thumbnail": thumb_cost,
            "veo_clips": veo_cost,
            "total": round(total, 1),
            "remaining_after": round(self.data["remaining"] - total, 1),
        }


# 싱글톤 인스턴스
_tracker_instance = None

def get_tracker() -> CreditTracker:
    """크레딧 트래커 싱글톤 반환"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = CreditTracker()
    return _tracker_instance
