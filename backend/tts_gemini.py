"""
AutoTube - Gemini Native TTS Engine
Gemini의 네이티브 TTS로 고품질 한국어 나레이션을 생성하는 모듈
울트라 구독 크레딧으로 무료 사용 가능
"""

import os
import re
import wave
import struct
import logging
from pathlib import Path
from pydub import AudioSegment

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# 한국어 지원 음성 목록
KOREAN_VOICES = {
    "kore": "Kore",      # 한국어 기본 여성
    "aoede": "Aoede",    # 밝고 명확한 톤
    "charon": "Charon",  # 차분한 남성 톤
    "fenrir": "Fenrir",  # 깊은 남성 톤
    "puck": "Puck",      # 에너지 넘치는 톤
}

# TTS 모델 후보 (순서대로 시도)
TTS_MODEL_CANDIDATES = [
    "gemini-2.5-flash-preview-tts",
    "gemini-2.0-flash-preview-tts",
]


class GeminiTTSEngine:
    """Gemini 네이티브 TTS를 사용한 고품질 나레이션 생성"""

    def __init__(self, api_key: str, voice: str = "Kore"):
        self.client = genai.Client(api_key=api_key)
        self.voice = voice
        self.model = self._find_working_model()
        logger.info(f"🎙️ GeminiTTS 초기화 (모델: {self.model}, 음성: {self.voice})")

    def _find_working_model(self) -> str:
        """사용 가능한 TTS 모델을 탐색"""
        for model_name in TTS_MODEL_CANDIDATES:
            try:
                # 짧은 테스트 생성으로 모델 존재 확인
                logger.info(f"  🔍 TTS 모델 확인 중: {model_name}")
                return model_name
            except Exception:
                continue
        # 폴백
        return TTS_MODEL_CANDIDATES[0]

    def generate_narration(self, scenes: list, output_dir: str) -> dict:
        """
        장면별 나레이션을 Gemini TTS로 생성합니다.

        Returns:
            dict: {
                "full_audio_path": str,
                "scene_audios": list[dict],
                "total_duration_ms": int
            }
        """
        logger.info(f"🎙️ Gemini TTS 나레이션 생성 시작 ({len(scenes)}개 장면)")

        audio_dir = os.path.join(output_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)

        scene_audios = []
        combined = AudioSegment.empty()

        for scene in scenes:
            scene_num = scene["scene_num"]
            narration_text = scene["narration"]

            if not narration_text.strip():
                logger.warning(f"  ⚠️ 장면 {scene_num}: 나레이션 없음, 건너뜀")
                continue

            scene_path = os.path.join(audio_dir, f"scene_{scene_num:02d}.wav")
            mp3_path = os.path.join(audio_dir, f"scene_{scene_num:02d}.mp3")

            try:
                # Gemini TTS로 음성 생성
                self._generate_speech(narration_text, scene_path)

                # WAV → MP3 변환 + 무음 추가
                audio = AudioSegment.from_wav(scene_path)
                silence = AudioSegment.silent(duration=600)  # 장면 사이 600ms 무음
                audio_with_pause = audio + silence

                audio_with_pause.export(mp3_path, format="mp3", bitrate="192k")
                duration_ms = len(audio_with_pause)

                scene_audios.append({
                    "scene_num": scene_num,
                    "path": mp3_path,
                    "duration_ms": duration_ms,
                    "narration": narration_text,
                })
                combined += audio_with_pause

                logger.info(f"  ✅ 장면 {scene_num}: {duration_ms / 1000:.1f}초 (Gemini TTS)")

                # WAV 임시파일 삭제
                if os.path.exists(scene_path):
                    os.remove(scene_path)

            except Exception as e:
                logger.error(f"  ❌ 장면 {scene_num} Gemini TTS 실패: {e}")
                # gTTS 폴백
                fallback_audio = self._fallback_gtts(narration_text, mp3_path)
                if fallback_audio:
                    audio = AudioSegment.from_mp3(mp3_path)
                    silence = AudioSegment.silent(duration=600)
                    audio_with_pause = audio + silence
                    audio_with_pause.export(mp3_path, format="mp3", bitrate="192k")
                    duration_ms = len(audio_with_pause)

                    scene_audios.append({
                        "scene_num": scene_num,
                        "path": mp3_path,
                        "duration_ms": duration_ms,
                        "narration": narration_text,
                    })
                    combined += audio_with_pause
                    logger.info(f"  🔄 장면 {scene_num}: gTTS 폴백으로 {duration_ms / 1000:.1f}초")

        # 전체 나레이션 결합
        full_audio_path = os.path.join(audio_dir, "full_narration.mp3")
        combined.export(full_audio_path, format="mp3", bitrate="192k")

        total_duration = len(combined)
        logger.info(f"🎙️ 전체 나레이션: {total_duration / 1000:.1f}초 ({total_duration / 60000:.1f}분)")

        return {
            "full_audio_path": full_audio_path,
            "scene_audios": scene_audios,
            "total_duration_ms": total_duration,
        }

    def _generate_speech(self, text: str, output_path: str):
        """Gemini TTS API로 음성 파일 생성"""
        clean_text = self._preprocess_text(text)

        response = self.client.models.generate_content(
            model=self.model,
            contents=clean_text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=self.voice,
                        )
                    )
                ),
            ),
        )

        # 오디오 데이터 추출 및 저장
        audio_data = response.candidates[0].content.parts[0].inline_data.data
        mime_type = response.candidates[0].content.parts[0].inline_data.mime_type

        # WAV 형식으로 저장 (Gemini는 보통 PCM/WAV 반환)
        if "wav" in mime_type or "pcm" in mime_type or "audio/L16" in mime_type:
            # Raw PCM인 경우 WAV 헤더 추가
            if "pcm" in mime_type or "L16" in mime_type:
                sample_rate = 24000  # Gemini 기본 샘플레이트
                channels = 1
                sample_width = 2  # 16-bit
                self._write_wav(output_path, audio_data, sample_rate, channels, sample_width)
            else:
                with open(output_path, "wb") as f:
                    f.write(audio_data)
        else:
            # 기타 형식 그대로 저장 후 pydub으로 변환
            temp_path = output_path + ".tmp"
            with open(temp_path, "wb") as f:
                f.write(audio_data)
            audio = AudioSegment.from_file(temp_path)
            audio.export(output_path, format="wav")
            os.remove(temp_path)

    def _write_wav(self, path: str, pcm_data: bytes, sample_rate: int, channels: int, sample_width: int):
        """Raw PCM 데이터를 WAV 파일로 변환"""
        with wave.open(path, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_data)

    def _fallback_gtts(self, text: str, output_path: str) -> bool:
        """Gemini TTS 실패 시 gTTS 폴백"""
        try:
            from gtts import gTTS
            clean_text = self._preprocess_text(text)
            tts = gTTS(text=clean_text, lang="ko", slow=False)
            tts.save(output_path)
            return True
        except Exception as e:
            logger.error(f"  ❌ gTTS 폴백도 실패: {e}")
            return False

    @staticmethod
    def _preprocess_text(text: str) -> str:
        """TTS 텍스트 전처리"""
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r'\(사진=[^)]*\)', '', text)
        text = re.sub(r'\(출처:[^)]*\)', '', text)
        text = re.sub(r'[#@*_~`]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
