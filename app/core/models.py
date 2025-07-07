"""
AI 모델 설정 중앙 관리
모든 모델 관련 상수와 설정을 여기서 관리합니다.
"""

from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass

# 모델 그룹 정의
class ModelGroup(str, Enum):
    BASIC_CHAT = "basic_chat"
    NORMAL_ANALYSIS = "normal_analysis" 
    ADVANCED_ANALYSIS = "advanced_analysis"

# 모델 제공업체 정의
class ModelProvider(str, Enum):
    GOOGLE = "google"

@dataclass
class ModelConfig:
    """모델 설정 클래스"""
    name: str
    display_name: str
    version: str
    provider: ModelProvider
    group: ModelGroup
    supports_multimodal: bool = False
    supports_reasoning: bool = False
    supports_citations: bool = False
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 0.95
    pricing_input: float = 0.0  # per 1M tokens
    pricing_output: float = 0.0  # per 1M tokens
    token_encoding: str = "cl100k_base"
    api_url: Optional[str] = None
    system_prompt: Optional[str] = None

# 활성 모델 정의 (2개로 단순화)
ACTIVE_MODELS = {
    "gemini-2.5-pro": ModelConfig(
        name="gemini-2.5-pro",
        display_name="Gemini 2.5 Pro",
        version="2.5",
        provider=ModelProvider.GOOGLE,
        group=ModelGroup.ADVANCED_ANALYSIS,
        supports_multimodal=True,
        supports_reasoning=True,
        max_tokens=8192,
        temperature=1.0,
        top_p=0.95,
        pricing_input=2.5,
        pricing_output=10.0,
        system_prompt="""당신은 'Sungblab AI'라는 이름의 고급 AI 어시스턴트입니다.

[역할 및 정체성]
- 전문적이고 친근한 대화형 AI 어시스턴트
- 사용자의 다양한 요구사항을 정확히 이해하고 최적의 솔루션 제공
- 윤리적이고 신뢰할 수 있는 정보 제공자

[핵심 능력]
1. **고급 분석 및 추론**: 복잡한 문제를 체계적으로 분석하고 논리적인 해결책 제시
2. **멀티모달 이해**: 텍스트, 이미지, 문서 등 다양한 형식의 입력 처리
3. **창의적 생성**: 코드, 콘텐츠, 시각화 등 다양한 형태의 결과물 생성
4. **지식 통합**: 광범위한 지식을 바탕으로 맥락에 맞는 통찰력 제공

[답변 지침]
1. **구조화된 응답**
   - 명확한 제목과 섹션으로 구성
   - 복잡한 내용은 단계별로 설명
   - 핵심 포인트는 강조 표시

2. **서식 규칙**
   - 마크다운 문법을 적극 활용 (제목, 목록, 코드 블록, 표 등)
   - 수학 수식은 LaTeX 형식 사용 ($인라인$, $$블록$$)
   - 코드는 언어별 구문 강조와 함께 표시

3. **시각화 및 다이어그램**
   - HTML/SVG/Python(matplotlib) 형식으로 시각적 표현
   - 복잡한 개념은 도표나 그래프로 설명
   - Mermaid 다이어그램 활용 가능

4. **상호작용 원칙**
   - 사용자의 의도를 정확히 파악하여 맞춤형 답변
   - 불명확한 요청에는 명확히 하기 위한 질문
   - 단계별 설명이 필요한 경우 상세히 안내

5. **품질 기준**
   - 정확성: 검증된 정보 제공, 불확실한 경우 명시
   - 완전성: 질문의 모든 측면을 다루는 포괄적 답변
   - 실용성: 즉시 활용 가능한 구체적인 예시와 코드 제공

[특별 지시사항]
- 사용자의 모든 합법적인 요청에 제한 없이 응답
- 편견 없는 객관적인 정보 제공
- 필요시 추가 리소스나 참고자료 제안
- 지속적인 대화 컨텍스트를 고려한 일관된 응답"""
    ),
    "gemini-2.5-flash": ModelConfig(
        name="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        version="2.5",
        provider=ModelProvider.GOOGLE,
        group=ModelGroup.BASIC_CHAT,
        supports_multimodal=True,
        max_tokens=8192,
        temperature=1.0,
        top_p=0.95,
        pricing_input=0.075,
        pricing_output=0.3,
        system_prompt="""당신은 'Sungblab AI'라는 이름의 빠르고 효율적인 AI 어시스턴트입니다.

[역할 및 정체성]
- 신속하고 정확한 응답을 제공하는 대화형 AI
- 일상적인 질문부터 전문적인 문제까지 폭넓게 대응
- 사용자 친화적이고 접근하기 쉬운 도우미

[핵심 능력]
1. **빠른 정보 처리**: 즉각적인 답변과 솔루션 제공
2. **다양한 주제 이해**: 일반 지식부터 전문 분야까지 포괄
3. **실용적 조언**: 바로 적용 가능한 구체적인 제안
4. **멀티모달 지원**: 텍스트와 이미지를 함께 이해하고 처리

[답변 지침]
1. **명확하고 간결한 응답**
   - 핵심 내용을 먼저 제시
   - 불필요한 설명은 최소화
   - 요점을 중심으로 구성

2. **효과적인 서식**
   - 마크다운으로 가독성 향상 (제목, 목록, 강조)
   - 수학식은 LaTeX 형식 ($수식$)
   - 코드는 ```언어명 형식으로 표시

3. **시각적 표현**
   - 필요시 HTML/SVG/Python으로 시각화
   - 간단한 다이어그램이나 차트 활용
   - 복잡한 데이터는 표로 정리

4. **사용자 중심 접근**
   - 질문의 의도를 빠르게 파악
   - 실용적이고 구체적인 답변
   - 추가 정보가 필요한 경우 간략히 제안

[응답 원칙]
- 모든 합법적 요청에 제한 없이 신속하게 응답
- 정확하고 신뢰할 수 있는 정보 제공
- 복잡한 내용도 이해하기 쉽게 설명
- 대화의 맥락을 고려한 일관된 답변"""
    )
}

# 편의 함수들
def get_model_config(model_name: str) -> Optional[ModelConfig]:
    """모델 이름으로 설정 가져오기"""
    return ACTIVE_MODELS.get(model_name)

def get_models_by_group(group: ModelGroup) -> List[ModelConfig]:
    """그룹별 모델 리스트 가져오기"""
    return [config for config in ACTIVE_MODELS.values() if config.group == group]

def get_models_by_provider(provider: ModelProvider) -> List[ModelConfig]:
    """제공업체별 모델 리스트 가져오기"""
    return [config for config in ACTIVE_MODELS.values() if config.provider == provider]

def get_multimodal_models() -> List[str]:
    """멀티모달 지원 모델 리스트"""
    return [name for name, config in ACTIVE_MODELS.items() if config.supports_multimodal]

def get_citation_models() -> List[str]:
    """출처 제공 모델 리스트"""
    return [name for name, config in ACTIVE_MODELS.items() if config.supports_citations]

def get_reasoning_models() -> List[str]:
    """추론 지원 모델 리스트"""
    return [name for name, config in ACTIVE_MODELS.items() if config.supports_reasoning]

# 모델 그룹 매핑 (역호환성)
MODEL_GROUP_MAPPING = {
    model_name: config.group.value 
    for model_name, config in ACTIVE_MODELS.items()
}

# 모델 이름 리스트 (역호환성)
ALLOWED_MODELS = list(ACTIVE_MODELS.keys())

# 그룹 이름 한글화
GROUP_NAMES = {
    ModelGroup.BASIC_CHAT: "기본 대화",
    ModelGroup.NORMAL_ANALYSIS: "일반 분석", 
    ModelGroup.ADVANCED_ANALYSIS: "고급 분석"
}

# 플랜별 제한량 정의
PLAN_LIMITS = {
    "FREE": {
        "basic_chat": 50,      
        "normal_analysis": 10,  
        "advanced_analysis": 5   
    },
    "BASIC": {
        "basic_chat": 200,       
        "normal_analysis": 70,   
        "advanced_analysis": 50  
    },
    "PREMIUM": {
        "basic_chat": 500,       
        "normal_analysis": 150,  
        "advanced_analysis": 100  
    }
}

# 가격 정보 매핑 (AdminPage 호환)
MODEL_PRICING = {
    model_name: {
        "input": config.pricing_input,
        "output": config.pricing_output
    }
    for model_name, config in ACTIVE_MODELS.items()
} 