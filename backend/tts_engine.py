"""
AutoTube - TTS Engine
나레이션 텍스트를 음성 파일로 변환하는 모듈
"""

import os
import re
import logging
from pathlib import Path
from gtts import gTTS
from pydub import AudioSegment

logger = logging.getLogger(__name__)


class TTSEngine:
    """Google TTS를 사용한 나레이션 음성 생성"""

    def __init__(self, language: str = "ko", speed: float = 1.0):
        self.language = language
        self.speed = speed

    def generate_narration(self, scenes: list, output_dir: str) -> dict:
        """
        장면별 나레이션을 음성으로 변환합니다.

        Args:
            scenes: 장면 리스트 [{"scene_num": 1, "narration": "...", ...}]
            output_dir: 음성 파일 저장 디렉토리

        Returns:
            dict: {
                "full_audio_path": str,     # 전체 나레이션 오디오 경로
                "scene_audios": list[dict],  # [{"scene_num": 1, "path": "...", "duration_ms": 5000}]
                "total_duration_ms": int
            }
        """
        logger.info(f"🎙️ 나레이션 음성 생성 시작 ({len(scenes)}개 장면)")

        audio_dir = os.path.join(output_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)

        scene_audios = []
        combined = AudioSegment.empty()

        for scene in scenes:
            scene_num = scene["scene_num"]
            narration_text = scene["narration"]

            if not narration_text.strip():
                logger.warning(f"⚠️ 장면 {scene_num}: 나레이션 텍스트 없음, 건너뜀")
                continue

            # 텍스트 전처리
            clean_text = self._preprocess_text(narration_text)

            # gTTS로 음성 생성
            scene_path = os.path.join(audio_dir, f"scene_{scene_num:02d}.mp3")

            try:
                tts = gTTS(text=clean_text, lang=self.language, slow=False)
                tts.save(scene_path)

                # pydub로 로드하여 속도 조절 및 품질 개선
                audio = AudioSegment.from_mp3(scene_path)

                # 속도 조절
                if self.speed != 1.0:
                    audio = self._change_speed(audio, self.speed)

                # 장면 사이에 짧은 무음 추가 (500ms)
                silence = AudioSegment.silent(duration=500)
                audio_with_pause = audio + silence

                # 저장
                audio_with_pause.export(scene_path, format="mp3", bitrate="192k")

                duration_ms = len(audio_with_pause)

                scene_audios.append({
                    "scene_num": scene_num,
                    "path": scene_path,
                    "duration_ms": duration_ms,
                    "narration": narration_text,
                })

                combined += audio_with_pause

                logger.info(f"  ✅ 장면 {scene_num}: {duration_ms / 1000:.1f}초")

            except Exception as e:
                logger.error(f"  ❌ 장면 {scene_num} 음성 생성 실패: {e}")
                continue

        # 전체 나레이션 결합 저장
        full_audio_path = os.path.join(audio_dir, "full_narration.mp3")
        combined.export(full_audio_path, format="mp3", bitrate="192k")

        total_duration = len(combined)
        logger.info(f"🎙️ 전체 나레이션: {total_duration / 1000:.1f}초 ({total_duration / 60000:.1f}분)")

        return {
            "full_audio_path": full_audio_path,
            "scene_audios": scene_audios,
            "total_duration_ms": total_duration,
        }

    def generate_full_narration(self, script: str, output_dir: str) -> dict:
        """전체 나레이션 스크립트를 하나의 오디오로 생성"""
        logger.info("🎙️ 전체 나레이션 단일 생성 모드...")

        audio_dir = os.path.join(output_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)

        clean_text = self._preprocess_text(script)
        full_path = os.path.join(audio_dir, "full_narration.mp3")

        tts = gTTS(text=clean_text, lang=self.language, slow=False)
        tts.save(full_path)

        audio = AudioSegment.from_mp3(full_path)
        if self.speed != 1.0:
            audio = self._change_speed(audio, self.speed)

        audio.export(full_path, format="mp3", bitrate="192k")

        return {
            "full_audio_path": full_path,
            "total_duration_ms": len(audio),
        }

    @staticmethod
    def _preprocess_text(text: str) -> str:
        """TTS를 위한 텍스트 전처리"""
        # URL 제거
        text = re.sub(r'https?://\S+', '', text)
        # 괄호 안의 설명 정리
        text = re.sub(r'\(사진=[^)]*\)', '', text)
        text = re.sub(r'\(출처:[^)]*\)', '', text)
        # 특수문자 정리
        text = re.sub(r'[#@*_~`]', '', text)
        # 연속 공백 정리
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def _change_speed(audio: AudioSegment, speed: float) -> AudioSegment:
        """오디오 재생 속도 변경"""
        if speed == 1.0:
            return audio

        # frame_rate 조절로 속도 변경
        sound_with_altered_frame_rate = audio._spawn(
            audio.raw_data,
            overrides={"frame_rate": int(audio.frame_rate * speed)}
        )
        return sound_with_altered_frame_rate.set_frame_rate(audio.frame_rate)
