"""
AutoTube - Subtitle Generator
나레이션 오디오에 맞는 SRT 자막 파일을 자동 생성하는 모듈
"""

import os
import re
import logging

logger = logging.getLogger(__name__)


class SubtitleGenerator:
    """장면별 나레이션 타이밍에 맞춘 SRT 자막 생성"""

    # 한 자막 블록의 최대 글자 수
    MAX_CHARS_PER_LINE = 25
    MAX_LINES_PER_BLOCK = 2

    def __init__(self):
        pass

    def generate_srt(self, scene_audios: list, output_path: str) -> str:
        """
        장면별 오디오 정보를 기반으로 SRT 자막 파일을 생성합니다.

        Args:
            scene_audios: [{"scene_num": 1, "narration": "...", "duration_ms": 5000}]
            output_path: SRT 파일 저장 경로

        Returns:
            str: 생성된 SRT 파일 경로
        """
        logger.info(f"📝 자막(SRT) 생성 시작 ({len(scene_audios)}개 장면)")

        srt_blocks = []
        block_index = 1
        cumulative_ms = 0

        for scene in scene_audios:
            narration = scene["narration"]
            duration_ms = scene["duration_ms"]

            # 나레이션을 자막 청크로 분할
            chunks = self._split_narration(narration)

            if not chunks:
                cumulative_ms += duration_ms
                continue

            # 각 청크의 시간 균등 분배
            chunk_duration = duration_ms / len(chunks)

            for i, chunk in enumerate(chunks):
                start_ms = cumulative_ms + int(i * chunk_duration)
                end_ms = cumulative_ms + int((i + 1) * chunk_duration) - 50  # 약간 겹침 방지

                srt_blocks.append({
                    "index": block_index,
                    "start": self._ms_to_srt_time(start_ms),
                    "end": self._ms_to_srt_time(end_ms),
                    "text": chunk,
                })
                block_index += 1

            cumulative_ms += duration_ms

        # SRT 파일 작성
        srt_content = self._build_srt(srt_blocks)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        logger.info(f"✅ 자막 저장: {output_path} ({len(srt_blocks)}개 블록)")
        return output_path

    def _split_narration(self, text: str) -> list:
        """나레이션 텍스트를 자막에 적합한 청크로 분할"""
        # 문장 단위로 먼저 분리
        sentences = re.split(r'(?<=[.!?。])\s*', text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        chunks = []
        for sentence in sentences:
            if len(sentence) <= self.MAX_CHARS_PER_LINE * self.MAX_LINES_PER_BLOCK:
                chunks.append(self._format_subtitle(sentence))
            else:
                # 긴 문장은 쉼표나 조사 단위로 분할
                sub_parts = self._split_long_sentence(sentence)
                chunks.extend(sub_parts)

        return chunks

    def _split_long_sentence(self, sentence: str) -> list:
        """긴 문장을 자막 크기에 맞게 분할"""
        max_len = self.MAX_CHARS_PER_LINE * self.MAX_LINES_PER_BLOCK

        # 쉼표, 접속사 등으로 분할
        parts = re.split(r'(?<=[,，])\s*|(?<=\s)(?:그리고|하지만|그러나|또한|따라서|그래서|그런데)\s', sentence)
        parts = [p.strip() for p in parts if p.strip()]

        result = []
        current = ""

        for part in parts:
            if len(current) + len(part) <= max_len:
                current = f"{current} {part}".strip() if current else part
            else:
                if current:
                    result.append(self._format_subtitle(current))
                current = part

        if current:
            result.append(self._format_subtitle(current))

        return result if result else [self._format_subtitle(sentence[:max_len])]

    def _format_subtitle(self, text: str) -> str:
        """자막 텍스트를 2줄로 포맷"""
        max_chars = self.MAX_CHARS_PER_LINE

        if len(text) <= max_chars:
            return text

        # 절반 지점에서 공백이나 조사 위치를 찾아 줄바꿈
        mid = len(text) // 2
        # 절반 근처에서 공백 찾기
        best_break = mid
        for offset in range(min(10, mid)):
            if mid + offset < len(text) and text[mid + offset] == ' ':
                best_break = mid + offset
                break
            if mid - offset >= 0 and text[mid - offset] == ' ':
                best_break = mid - offset
                break

        line1 = text[:best_break].strip()
        line2 = text[best_break:].strip()

        return f"{line1}\n{line2}" if line2 else line1

    @staticmethod
    def _ms_to_srt_time(ms: int) -> str:
        """밀리초를 SRT 타임코드 형식으로 변환 (HH:MM:SS,mmm)"""
        if ms < 0:
            ms = 0
        hours = ms // 3600000
        minutes = (ms % 3600000) // 60000
        seconds = (ms % 60000) // 1000
        milliseconds = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    @staticmethod
    def _build_srt(blocks: list) -> str:
        """SRT 블록 리스트를 SRT 파일 형식 문자열로 변환"""
        lines = []
        for block in blocks:
            lines.append(str(block["index"]))
            lines.append(f"{block['start']} --> {block['end']}")
            lines.append(block["text"])
            lines.append("")  # 빈 줄 구분

        return "\n".join(lines)
