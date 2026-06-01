"""
AutoTube - Script Generator (Gemini AI)
기사 내용을 바탕으로 유튜브 대본, 제목, 설명, 해시태그를 생성하는 모듈
"""

from google import genai
from google.genai import types
import json
import re
import logging

logger = logging.getLogger(__name__)


class ScriptGenerator:
    """Gemini AI를 사용해 유튜브 콘텐츠를 자동 기획"""

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        logger.info(f"🤖 ScriptGenerator 초기화 (모델: {model_name})")

    def generate(self, article: dict, style: str = "cinematic", reference_url: str = None, target_duration: int = 50, omni_template: str = None) -> dict:
        """
        기사 데이터로부터 유튜브 콘텐츠 전체를 생성합니다.

        Args:
            article: scraper.py에서 반환된 기사 딕셔너리

        Returns:
            dict: {
                "youtube_title": str,
                "youtube_description": str,
                "hashtags": list[str],
                "thumbnail_text": str,
                "thumbnail_subtitle": str,
                "narration_script": str,
                "scenes": list[dict],  # [{scene_num, narration, visual_prompt, duration_sec}]
                "tags": list[str]
            }
        """
        logger.info("📝 대본 및 메타데이터 생성 중...")

        prompt = self._build_prompt(article, style, reference_url, target_duration, omni_template)

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.85,
                    top_p=0.95,
                    max_output_tokens=8000,
                    response_mime_type="application/json",
                ),
            )

            response_text = response.text.strip()
            # 마크다운 코드 블록 제거
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            
            response_text = response_text.strip()
            
            # 혹은 fallback의 정규표현식을 사용하여 확실히 json 추출
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                response_text = json_match.group()

            result = json.loads(response_text)
            logger.info(f"✅ 생성 완료: '{result.get('youtube_title', 'N/A')}'")
            return result

        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ JSON 파싱 실패 ({e}), 텍스트에서 추출 시도...")
            return self._parse_fallback(response.text, article)

        except Exception as e:
            logger.error(f"❌ Gemini 생성 실패: {e}")
            raise

    def _build_prompt(self, article: dict, style: str, reference_url: str, target_duration: int, omni_template: str) -> str:
        """Gemini에 보낼 프롬프트를 구성"""
        
        style_instruction = ""
        if omni_template:
            style_instruction = f"이 영상은 Omni 템플릿 '{omni_template}' 스타일로 제작됩니다. 중요: 4개의 모든 장면(scene)의 `visual_prompt` 시작 부분에 반드시 `[{omni_template} style],` 이라는 지시어를 똑같이 고정값으로 적어주세요. 이를 통해 4개의 영상 클립 전체가 완벽하게 동일한 시각적 컨셉을 유지해야 합니다."
        elif style == "photorealistic":
            style_instruction = "이 영상은 '극사실주의(Photorealistic) 실사' 스타일로 제작됩니다. visual_prompt 작성 시 반드시 실사, 카메라 촬영, 8k 화질, 자연광 등의 키워드를 강조하세요."
        elif style == "animation":
            style_instruction = "이 영상은 '애니메이션(Animation)' 스타일로 제작됩니다. visual_prompt 작성 시 반드시 스튜디오 지브리, 애니메이션, 생동감 넘치는 색감, 2D 셀 셰이딩 등의 키워드를 강조하세요."
        elif style == "illustration":
            style_instruction = "이 영상은 '일러스트(Illustration)' 스타일로 제작됩니다. visual_prompt 작성 시 반드시 디지털 아트, 콘셉트 아트, 일러스트레이션 등의 키워드를 강조하세요."
        else:
            style_instruction = "이 영상은 '시네마틱(Cinematic)' 스타일로 제작됩니다. visual_prompt 작성 시 반드시 시네마틱 렌즈, 고품질 조명, 프리미엄 영상미 등의 키워드를 강조하세요."

        ref_instruction = ""
        if reference_url:
            ref_instruction = f"\n## 참고 URL\n다음 참고 URL의 내용이나 주제, 스타일을 추가로 분석하여 기획에 반영하세요: {reference_url}\n"

        min_chars = target_duration * 4
        max_chars = int(target_duration * 5.5)

        return f"""당신은 한국의 인기 유튜브 뉴스/정보 채널의 전문 콘텐츠 기획자입니다.
{style_instruction}
{ref_instruction}
아래 뉴스 기사를 바탕으로 시청자를 강력하게 사로잡는 유튜브 영상 콘텐츠를 기획해주세요.

## 기사 정보
- 제목: {article['title']}
- 출처: {article['source_name']}
- 본문:
{article['text'][:4000]}

## 요구사항

### 1. 유튜브 제목 (youtube_title)
- 궁금증을 유발하는 클릭 유도 제목 (60자 이내)
- 핵심 키워드를 앞쪽에 배치
- 숫자, 감탄사, 질문형 활용

### 2. 유튜브 설명 (youtube_description)
- 영상 내용을 요약하는 매력적인 설명 (300자 내외)
- 핵심 키워드 포함
- 주의: 시청자에게 구독과 좋아요를 유도하는 멘트는 절대 포함하지 마세요.

### 3. 해시태그 (hashtags)
- 관련 해시태그 8~12개 (#기호 포함)
- 트렌딩 가능한 키워드 우선

### 4. 썸네일 텍스트 (thumbnail_text)
- 썸네일에 큰 글씨로 들어갈 임팩트 있는 텍스트 (10자 이내, 짧고 강렬하게)

### 5. 썸네일 서브타이틀 (thumbnail_subtitle)
- 썸네일 하단에 들어갈 보조 텍스트 (15자 이내)

### 6. 나레이션 대본 (narration_script)
- 전체 나레이션을 하나의 연속된 텍스트로 작성
- **[매우 중요]** 영상 길이가 정확히 40초(각 장면 10초씩)이므로, 음성 TTS가 40초에 딱 맞게 꽉 차도록 **전체 글자 수를 200자~220자 내외(공백 포함)**로 적절하고 밀도 있게 작성하세요. (너무 짧으면 오디오가 비고, 너무 길면 잘립니다.)
- **[기승전결 4단계 구성 원칙]** 4개의 장면이 각각 기승전결(도입-전개-반전-결론)의 명확하고 몰입감 있는 흐름을 형성해야 합니다.
  - **Scene 1 (기 - 3초 초강력 훅):** 호기심이나 반전을 유발하는 강렬한 첫마디로 시청자의 이탈을 방지하세요. (예: "엔비디아 다 팔았는데도, 서학개미들이 조용히 쓸어담은 반도체 주식이 있습니다.")
  - **Scene 2 (승 - 상세 전개):** 도입부에서 제시한 정보를 뒷받침하는 핵심 팩트를 구체적으로 알려주세요.
  - **Scene 3 (전 - 대조/반전):** 정보의 가장 놀랍거나 흥미로운 피크(Peak)를 대조나 반전을 활용해 극대화하세요.
  - **Scene 4 (결 - 결론/안정적 마감):** 기사의 최종 결과 및 정리된 결론을 명확하고 깔끔하게 마감하여 독자에게 정보를 완전하게 전달하세요.
- **[쉬운 단어와 명확한 팩트]** 복잡한 전문 금융 지표나 어려운 용어(예: 순매도 우위 기조, 보관 잔액 등)는 배제하고, 누구나 듣자마자 바로 이해할 수 있는 직관적인 구어체 표현(예: 주식을 대거 팔면서도, 보유한 주식 가치 등)을 사용하여 정확한 정보만 전달하세요.
- 세로형 영상(9:16)에 어울리는 빠른 템포와 강렬한 흡입력
- 주의: 마무리 인사나 "구독, 좋아요" 멘트는 절대 넣지 말고 임팩트 있게 끝내세요.

### 7. 장면 구성 (scenes)
- 전체 내용을 반드시 **정확히 4개의 장면(scene)**으로 나누세요. (10초짜리 영상 4개를 연결하기 위함입니다.)
- 각 장면:
  - scene_num: 1, 2, 3, 4
  - narration: 각 장면에 해당하는 나레이션 대사 배분 (합치면 전체 나레이션과 동일해야 함)
  - visual_prompt: 외부 AI 비디오 생성기에 복사해서 붙여넣기 좋게 아주 구체적이고 프리미엄 영상 스타일이 드러나도록 **영어로 작성**하세요 (15~25단어 내외). 
  - **[비주얼 스타일 일관성 (Style Consistency)]** 4개 장면이 완전히 일치하는 세계관과 화풍을 공유해야 합니다. 동일한 캐릭터, 통일된 컬러 팔레트(Color palette), 유사한 실내/외 배경 테마, 일관된 카메라 톤을 묘사하세요.
  - **[비디오 생성 퀄리티 향상 지침]** 고품질 비디오를 위해 카메라 움직임(예: Slow cinematic pan, dynamic close-up, drone shot, zoom), 조명(예: Volumetric lighting, warm glowing neon, cinematic shadows), 디테일(예: 8k, photorealistic textures, hyper-detailed)을 명확히 명시하세요.
  - **[텍스트 절대 배제]** 프롬프트에 글자, 텍스트, 한자(중문), 영어 단어, 로고, 캡션 등을 생성하라는 내용은 절대 포함하지 마세요. (Absolutely NO Chinese characters, NO text, NO letters, NO words, NO logos)
  - duration_sec: 각 10초 (총 40초 내외)

### 8. 태그 (tags)
- 유튜브 SEO용 태그 10~15개 (한국어)

## 중요 규칙
- 모든 내용은 한국어로 작성
- visual_prompt만 영어로 작성 (9:16 세로형 포맷 강조, 텍스트/한자/글자/단어 등 절대 포함 금지)
- 자극적이되 허위 정보는 절대 포함하지 않기
- 원본 기사의 사실 관계를 정확히 유지
- **시청자가 중도에 이탈하지 않도록 직관적이고 귀에 꽂히는 짧은 호흡의 문장을 사용할 것**

## 응답 형식
반드시 아래 JSON 구조로만 응답하세요:
{{
    "youtube_title": "...",
    "youtube_description": "...",
    "hashtags": ["#...", "#..."],
    "thumbnail_text": "...",
    "thumbnail_subtitle": "...",
    "narration_script": "...",
    "scenes": [
        {{
            "scene_num": 1,
            "narration": "...",
            "visual_prompt": "...",
            "duration_sec": 10
        }},
        {{
            "scene_num": 2,
            "narration": "...",
            "visual_prompt": "...",
            "duration_sec": 10
        }},
        {{
            "scene_num": 3,
            "narration": "...",
            "visual_prompt": "...",
            "duration_sec": 10
        }},
        {{
            "scene_num": 4,
            "narration": "...",
            "visual_prompt": "...",
            "duration_sec": 10
        }}
    ],
    "tags": ["...", "..."]
}}"""

    def _parse_fallback(self, text: str, article: dict) -> dict:
        """JSON 파싱 실패 시 텍스트에서 구조를 추출하는 폴백"""
        # JSON 블록 추출 시도
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # 최소한의 기본 구조 반환
        logger.warning("⚠️ 폴백 모드: 기본 구조로 생성")
        return {
            "youtube_title": f"[속보] {article['title']}",
            "youtube_description": article.get('summary', article['text'][:300]),
            "hashtags": [f"#{kw}" for kw in article.get('keywords', ['뉴스', '속보'])[:8]],
            "thumbnail_text": article['title'][:10],
            "thumbnail_subtitle": article['source_name'],
            "narration_script": article['text'][:1200],
            "scenes": [
                {
                    "scene_num": 1,
                    "narration": article['text'][:200],
                    "visual_prompt": "News broadcast studio with modern graphics, vertical 9:16",
                    "duration_sec": 10
                },
                {
                    "scene_num": 2,
                    "narration": article['text'][200:400] if len(article['text']) > 200 else "...",
                    "visual_prompt": "News broadcast studio with modern graphics, vertical 9:16",
                    "duration_sec": 10
                },
                {
                    "scene_num": 3,
                    "narration": article['text'][400:600] if len(article['text']) > 400 else "...",
                    "visual_prompt": "News broadcast studio with modern graphics, vertical 9:16",
                    "duration_sec": 10
                },
                {
                    "scene_num": 4,
                    "narration": article['text'][600:800] if len(article['text']) > 600 else "...",
                    "visual_prompt": "News broadcast studio with modern graphics, vertical 9:16",
                    "duration_sec": 10
                }
            ],
            "tags": article.get('keywords', ['뉴스'])[:10]
        }
