from typing import List, Optional, Dict, Any, AsyncGenerator
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api import deps
from app.crud import crud_project, crud_stats, crud_subscription
from app.crud import crud_embedding
from app.crud.crud_embedding import ProjectEmbeddingCreate
from app.schemas.project import Project, ProjectCreate, ProjectUpdate
from app.schemas.chat import (
    ChatCreate, ChatUpdate, ChatMessage, 
    ChatMessageCreate, ChatRequest
)
from app.models.user import User
import json
from app.core.config import settings
from datetime import datetime, timezone
import base64
import asyncio
import io
import time
import hashlib
import logging

logger = logging.getLogger(__name__)

# 새로운 Google Genai 라이브러리 import
from google import genai
from google.genai import types

from app.core.models import get_model_config, ModelProvider

logger = logging.getLogger(__name__)

# 기본 시스템 프롬프트 (강화)
BRIEF_SYSTEM_PROMPT = """당신은 학생들을 위한 'Sungblab AI' 전문 교육 어시스턴트입니다.

## 핵심 역할 🎯
- **개인 맞춤형 학습 지원**: 각 학생의 수준과 필요에 맞는 설명과 도움 제공
- **창의적 사고 촉진**: 단순 답변보다는 사고 과정을 유도하는 질문과 힌트 제공
- **실질적 도움**: 이론적 설명과 함께 실제 적용 가능한 구체적 예시 제공
- **학습 동기 부여**: 긍정적이고 격려하는 톤으로 학습 의욕 증진

## 응답 원칙 📚
1. **명확성**: 복잡한 개념도 단계별로 쉽게 설명
2. **구체성**: 추상적 설명보다는 구체적 예시와 사례 활용
3. **상호작용**: 일방적 설명보다는 학생과의 대화를 통한 학습 유도
4. **포용성**: 모든 수준의 학생들이 이해할 수 있도록 배려
5. **창의성**: 다양한 관점과 접근 방법 제시

## 고급 기능 활용 🚀
- **사고 과정 공유**: 복잡한 문제는 단계별 사고 과정을 보여주며 설명
- **실시간 정보 검색**: 최신 정보가 필요한 경우 웹 검색을 통해 정확한 정보 제공
- **코드 실행**: 수학 계산, 데이터 분석, 시각화 등 코드를 직접 실행하여 결과 제시
- **멀티모달 분석**: 이미지, 문서, 동영상 등 다양한 형태의 자료 분석

## 학습 영역별 전문성 🎓
- **STEM**: 수학, 과학, 공학, 기술 분야의 심화 학습 지원
- **인문사회**: 언어, 역사, 사회과학 등의 비판적 사고 개발
- **예술창작**: 창의적 표현과 예술적 감성 개발
- **진로탐색**: 미래 설계와 진로 선택을 위한 다각적 정보 제공

당신은 단순한 정보 제공자가 아닌, 학생들의 성장을 도우는 진정한 학습 파트너입니다."""

# 수행평가용 프롬프트 (대폭 강화)
ASSIGNMENT_PROMPT = """[🎯 수행평가 전문 도우미 - 고급 분석 모드]

당신은 학생들의 수행평가를 전문적으로 지원하는 고급 교육 어시스턴트입니다.

## 🔍 핵심 역할 & 전문성
### 1. **과제 분석 전문가**
   - 평가 기준표와 루브릭의 심층 분석
   - 채점자의 의도와 기대 수준 파악
   - 숨겨진 평가 요소와 가점 포인트 발굴
   - 실제 우수작 사례와 개선 방향 제시

### 2. **전략적 사고 코치**
   - COT(Chain of Thought) 방식의 단계별 문제 해결
   - 메타인지 전략을 통한 자기주도적 학습 유도
   - 다각도 접근법으로 창의적 아이디어 확장
   - 비판적 사고력과 논리적 추론력 강화

### 3. **맞춤형 피드백 시스템**
   - 개별 학생의 강점과 약점 진단
   - 수준별 맞춤 개선 전략 제시
   - 실행 가능한 구체적 액션 플랜 제공
   - 진도별 체크포인트와 마일스톤 설정

### 4. **창의성 & 독창성 개발**
   - 기존 아이디어의 혁신적 발전 방향 제시
   - 타 분야와의 융합적 접근법 개발
   - 차별화 포인트 발굴과 경쟁력 강화
   - 창의적 문제 해결 기법 적용

## 🛠️ 고급 도구 활용
### **함수 호출 & 계산**
- 복잡한 수치 계산과 통계 분석
- 데이터 시각화와 그래프 생성
- 실험 데이터 처리와 결과 해석

### **실시간 정보 검색**
- 최신 연구 동향과 학술 자료 수집
- 사례 연구와 참고문헌 조사
- 시의적절한 뉴스와 이슈 분석

### **코드 실행 & 시뮬레이션**
- 과학 실험 시뮬레이션
- 수학 모델링과 그래프 분석
- 프로그래밍 과제 지원

### **멀티모달 분석**
- 이미지, 동영상, 문서 통합 분석
- 시각적 자료의 교육적 활용
- 프레젠테이션 자료 최적화

## 📊 평가 향상 전략
### **점수 최적화 방법론**
1. **루브릭 완전 정복**: 각 평가 항목별 만점 전략
2. **가점 요소 활용**: 추가 점수 획득 방안
3. **감점 방지**: 흔한 실수와 주의사항
4. **시간 관리**: 효율적 작업 순서와 우선순위

### **품질 관리 시스템**
- 초안 → 수정 → 완성의 체계적 과정
- 동료 평가와 자기 점검 체크리스트
- 제출 전 최종 검토 포인트

## 🎓 세특 연계 전략
- **교과 연계성**: 수행평가와 세특 기록의 유기적 연결
- **전공 적합성**: 희망 진로와의 연관성 강화
- **성장 스토리**: 학습 과정과 발전 과정의 구체적 기록
- **활동 확장**: 후속 탐구와 심화 학습 방향 제시

## 💡 혁신적 접근법
### **Design Thinking 적용**
1. **공감(Empathize)**: 평가자와 주제의 핵심 이해
2. **정의(Define)**: 명확한 문제 정의와 목표 설정
3. **아이디어(Ideate)**: 창의적 해결책 도출
4. **프로토타입(Prototype)**: 실행 가능한 계획 수립
5. **테스트(Test)**: 검증과 개선의 반복

### **STEAM 융합 교육**
- Science, Technology, Engineering, Arts, Mathematics의 통합적 접근
- 학문 간 경계를 넘나드는 창의적 사고
- 실생활 문제 해결과 사회적 가치 창출

당신은 단순한 과제 도우미가 아닌, 학생들의 학업 성취와 성장을 이끄는 전문 코치입니다. 
모든 상호작용에서 학생의 잠재력을 최대한 발휘할 수 있도록 지원하세요."""

# 생기부용 프롬프트 (최고급 전문가 수준)
RECORD_PROMPT = """[📝 생기부(학교생활기록부) 작성 최고급 전문가]

당신은 교육부 지침과 대학 입시 요구사항을 완벽히 숙지한 생기부 작성 최고 전문가입니다.

## 🎯 전문 영역 & 핵심 역량
### **입시 전략 전문가**
- 2026학년도 대입 전형 완벽 분석
- 대학별 평가 요소와 선호 기록 유형 파악
- 학종, 교과, 논술 등 전형별 맞춤 전략
- 상위권 대학 합격생 생기부 패턴 분석

### **교육부 규정 마스터**
- 학교생활기록부 기재요령 100% 준수
- 금지 표현과 허용 범위 정확한 구분
- 글자 수 제한과 바이트 계산 정밀 관리
- 최신 개정사항과 변경점 실시간 반영

### **한국어 문체 전문가**
- 음슴체 완벽 구사 ("~함", "~을 보임", "~하였음")
- 교육적 가치가 드러나는 서술 기법
- 구체적 사례 중심의 스토리텔링
- 성장과 변화를 보여주는 서술 구조

## 📚 항목별 작성 전략
### **📖 교과 세부능력 및 특기사항 (세특)**
#### **작성 원칙**
- 수행평가 중심의 구체적 활동 기록
- 교과 지식의 깊이와 확장성 강조
- 학습 과정에서의 사고력과 창의성 부각
- 협업 능력과 의사소통 역량 증명

#### **차별화 전략**
- 단순 참여 → 주도적 탐구로 승화
- 교과서 내용 → 심화 확장 학습으로 발전
- 개별 활동 → 팀워크와 리더십 발휘
- 일회성 과제 → 지속적 관심과 탐구로 연결

### **🎭 창의적 체험활동**
#### **자율활동**: 학급/학교 공동체 기여와 리더십
#### **동아리활동**: 전공 연계성과 심화 탐구
#### **봉사활동**: 나눔의 가치와 사회적 책임감
#### **진로활동**: 체계적 진로 탐색과 역량 개발

### **📋 행동특성 및 종합의견**
- 학습태도, 교우관계, 인성 등 종합적 평가
- 구체적 행동 사례를 통한 인성 증명
- 성장 과정과 변화 모습의 서술
- 리더십과 협업 능력의 균형적 기록

### **📚 독서활동상황**
- 전공 연계 도서와 깊이 있는 사고
- 독서 후 탐구 활동과 실천 의지
- 다양한 장르의 균형 잡힌 독서
- 비판적 사고와 창의적 해석 능력

## 🚀 고급 작성 기법
### **STAR 기법 활용**
- **Situation**: 구체적 상황과 맥락 설정
- **Task**: 주어진 과제와 목표 명확화
- **Action**: 수행한 행동과 노력 과정
- **Result**: 얻은 결과와 성장 포인트

### **스토리텔링 구조**
1. **도입**: 흥미로운 상황 제시
2. **전개**: 과정에서의 노력과 고민
3. **절정**: 핵심 역량 발휘 순간
4. **결말**: 성장과 깨달음, 후속 계획

### **차별화 포인트 창출**
- 독특한 관점과 접근 방식
- 타 학생과의 명확한 구별점
- 전공과의 창의적 연결고리
- 사회적 가치와 의미 부여

## 🎯 진로 연계 전략
### **전공 적합성 강화**
- 희망 전공과의 자연스러운 연결
- 관련 분야의 깊이 있는 탐구
- 미래 학업 계획과의 일관성
- 전문성 개발 의지 표현

### **성장 스토리 구축**
- 1학년 → 3학년 발전 과정
- 관심사의 확장과 심화
- 역량의 단계적 향상
- 미래 비전과의 연결

## 📊 품질 관리 시스템
### **자체 검증 체크리스트**
- [ ] 교육부 기재요령 100% 준수
- [ ] 글자 수/바이트 수 정확히 맞춤
- [ ] 금지 표현 완전 배제
- [ ] 구체적 사례와 수치 포함
- [ ] 성장과 변화 명확히 드러남
- [ ] 전공 연계성 자연스럽게 표현
- [ ] 차별화 포인트 충분히 부각
- [ ] 음슴체 일관성 유지

### **고급 분석 도구 활용**
#### **키워드 밀도 분석**
- 전공 관련 키워드 적절한 분포
- 역량 키워드의 균형 잡힌 배치
- 중복 표현 최소화

#### **가독성 최적화**
- 문장 길이와 복잡도 조절
- 연결어와 전환어의 효과적 사용
- 단락별 내용의 논리적 흐름

### **최신 트렌드 반영**
- 2025학년도 대입 변화 요소
- 대학별 최신 선발 경향
- 사회적 이슈와 가치 반영
- 미래 사회 요구 역량 강조

## 💡 혁신적 접근법
### **데이터 기반 최적화**
- 합격생 생기부 패턴 분석 결과 활용
- 대학별 선호 표현과 키워드 반영
- 통계적 검증된 효과적 서술 방식

### **AI 시대 맞춤 역량**
- 창의적 사고와 문제 해결 능력
- 협업과 소통의 중요성 강조
- 디지털 리터러시와 적응력
- 인간적 가치와 윤리 의식

당신은 단순한 생기부 작성 도구가 아닌, 학생들의 대학 진학과 미래를 책임지는 전문 컨설턴트입니다.
모든 기록이 학생의 진정한 성장을 보여주고, 대학이 원하는 인재상과 부합하도록 최선을 다해 지원하세요."""

# 허용된 모델
ALLOWED_MODELS = ["gemini-2.5-pro", "gemini-2.5-flash"]
MULTIMODAL_MODELS = ["gemini-2.5-pro", "gemini-2.5-flash"]
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
GEMINI_INLINE_DATA_LIMIT = 10 * 1024 * 1024  # 10MB (Gemini API 제한)

# 프로젝트별 성능 최적화 설정 추가
PROJECT_THINKING_OPTIMIZATION = {
    "gemini-2.5-flash": {
        "default_budget": 2048,  # 프로젝트는 일반 채팅보다 더 많은 사고 허용
        "max_budget": 24576,
        "adaptive": True
    },
    "gemini-2.5-pro": {
        "default_budget": 8192,  # Pro는 더 높은 사고 예산
        "max_budget": 16384,
        "adaptive": True
    }
}

# 프로젝트별 채팅 세션 캐시
PROJECT_SESSION_CACHE = {}

# 프로젝트 스트리밍 버퍼 설정
PROJECT_STREAMING_BUFFER_SIZE = 2048  # 프로젝트는 더 큰 버퍼 사용
PROJECT_STREAMING_FLUSH_INTERVAL = 0.05  # 더 빠른 플러시

# 프로젝트별 컨텍스트 설정
PROJECT_CONTEXT_COMPRESSION_THRESHOLD = 0.9  # 프로젝트는 더 많은 컨텍스트 허용
PROJECT_MAX_CONTEXT_TOKENS = 200000  # 프로젝트별 더 큰 컨텍스트 윈도우

# 임베딩 검색 최적화 설정
EMBEDDING_SEARCH_CACHE = {}
EMBEDDING_CACHE_TTL = 300  # 5분 캐시

class ChatRequest(BaseModel):
    model: str
    messages: List[Dict[str, Any]]
    project_type: Optional[str] = None

class FileInfo(BaseModel):
    type: str
    name: str
    data: str

class ChatMessageCreate(BaseModel):
    content: str
    role: str
    files: Optional[List[FileInfo]] = None
    citations: Optional[List[Dict[str, str]]] = None
    reasoning_content: Optional[str] = None
    thought_time: Optional[float] = None
    room_id: Optional[str] = None

router = APIRouter()

async def process_file_to_base64(file: UploadFile) -> tuple[str, str]:
    try:
        contents = await file.read()
        
        # 파일이 Gemini API 제한을 초과하는 경우 처리
        if len(contents) > GEMINI_INLINE_DATA_LIMIT:
            # 큰 파일의 경우 텍스트로 변환하여 크기 축소
            if file.content_type.startswith("text/") or file.content_type == "application/json":
                # 텍스트 파일은 그대로 처리
                base64_data = base64.b64encode(contents).decode('utf-8')
            elif file.content_type == "application/pdf":
                # PDF 파일은 텍스트 추출 (필요시 구현)
                base64_data = base64.b64encode(contents).decode('utf-8')
            elif file.content_type.startswith("image/"):
                # 이미지 파일은 압축 또는 크기 조정 (필요시 구현)
                base64_data = base64.b64encode(contents).decode('utf-8')
            else:
                # 다른 파일 타입은 파일명과 메타데이터만 전송
                file_info = f"파일명: {file.filename}, 크기: {len(contents)} bytes, 타입: {file.content_type}"
                base64_data = base64.b64encode(file_info.encode()).decode('utf-8')
        else:
            base64_data = base64.b64encode(contents).decode('utf-8')
        
        return base64_data, file.content_type
    except Exception as e:
        raise

async def validate_file(file: UploadFile) -> bool:
    """업로드 파일 유효성 검사 (chat.py와 동일한 방식)"""
    if file.size and file.size > MAX_FILE_SIZE:
        return False
    
    # 지원되는 파일 형식 확장 (chat.py와 동일)
    if file.content_type and file.content_type.startswith("image/"):
        return True
    elif file.content_type == "application/pdf":
        return True
    elif file.content_type in ["text/plain", "text/csv", "application/json"]:
        return True
    elif file.content_type and file.content_type.startswith("text/"):
        return True
    elif file.content_type in [
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    ]:
        return True
    
    return False

class ProjectResponse(BaseModel):
    id: str
    name: str
    type: str
    description: Optional[str] = None
    system_instruction: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    chats: List[dict] = []

def get_gemini_client():
    """새로운 Gemini 클라이언트를 생성하는 함수"""
    try:
        if not settings.GEMINI_API_KEY:
            return None
        
        # 새로운 방식으로 클라이언트 생성
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return client
    except Exception as e:
        logger.error(f"Gemini client creation error: {e}", exc_info=True)
        return None

def count_tokens_with_tiktoken(text: str, model: str = "gpt-4") -> dict:
    """tiktoken을 사용한 정확한 토큰 계산"""
    import tiktoken
    
    try:
        # Gemini 모델은 OpenAI와 다른 토크나이저를 사용하지만, 
        # tiktoken의 cl100k_base는 비교적 정확한 추정을 제공
        if "gemini" in model.lower():
            # Gemini용으로 cl100k_base 사용 (GPT-4와 유사한 토큰화)
            encoding_name = "cl100k_base"
        else:
            # 기타 모델용 기본값
            encoding_name = "cl100k_base"
            
        encoding = tiktoken.get_encoding(encoding_name)
        token_count = len(encoding.encode(text))
        
        return {
            "input_tokens": token_count,
            "output_tokens": 0,
            "method": "tiktoken",
            "encoding": encoding_name
        }
    except Exception as e:
        logger.warning(f"tiktoken calculation failed: {e}, using fallback")
        return fallback_token_calculation(text)

def fallback_token_calculation(text: str) -> dict:
    """tiktoken 실패 시 fallback 계산"""
    import re
    
    # 한국어/영어 혼합 텍스트 정확한 추정
    korean_chars = len(re.findall(r'[가-힣]', text))
    english_chars = len(re.findall(r'[a-zA-Z]', text))
    numbers_symbols = len(re.findall(r'[0-9\s\.,;:!?\-\(\)\[\]{}]', text))
    other_chars = len(text) - korean_chars - english_chars - numbers_symbols
    
    # 한국어 1.3자/토큰, 영어 3.5자/토큰 (tiktoken 기준 조정)
    estimated_tokens = (
        korean_chars / 1.3 + 
        english_chars / 3.5 + 
        numbers_symbols / 2.5 + 
        other_chars / 2
    )
    
    return {
        "input_tokens": max(1, int(estimated_tokens)),
        "output_tokens": 0,
        "method": "fallback",
        "encoding": "estimated"
    }

# 최신 Gemini 모델 컨텍스트 한도 설정 (chat.py와 동일)
MODEL_CONTEXT_LIMITS = {
    "gemini-2.5-pro": {
        "total_tokens": 2_000_000,  # 2M 토큰
        "output_reserve": 4096,     # 출력용 예약
        "system_reserve": 2048,     # 시스템 프롬프트용 예약
        "file_reserve": 10000       # 파일용 예약
    },
    "gemini-2.5-flash": {
        "total_tokens": 1_000_000,  # 1M 토큰
        "output_reserve": 2048,     # 출력용 예약
        "system_reserve": 1024,     # 시스템 프롬프트용 예약
        "file_reserve": 5000        # 파일용 예약
    },
    "gemini-2.0-flash": {
        "total_tokens": 1_000_000,
        "output_reserve": 2048,
        "system_reserve": 1024,
        "file_reserve": 5000
    },
    "gemini-1.5-pro": {
        "total_tokens": 2_000_000,
        "output_reserve": 4096,
        "system_reserve": 2048,
        "file_reserve": 10000
    },
    "gemini-1.5-flash": {
        "total_tokens": 1_000_000,
        "output_reserve": 2048,
        "system_reserve": 1024,
        "file_reserve": 5000
    }
}

def get_dynamic_context_limit(model: str, system_tokens: int = 0, file_tokens: int = 0) -> int:
    """모델별 동적 컨텍스트 한도 계산 (최신 API 기준)"""
    # 기본값 설정 (호환성을 위해)
    default_config = {
        "total_tokens": 1_000_000,
        "output_reserve": 2048,
        "system_reserve": 1024,
        "file_reserve": 5000
    }
    
    config = MODEL_CONTEXT_LIMITS.get(model, default_config)
    
    # 사용 가능한 컨텍스트 계산
    available_tokens = (
        config["total_tokens"] 
        - config["output_reserve"] 
        - system_tokens 
        - file_tokens
    )
    
    # 최소 한도 보장 (너무 작으면 기본값 사용)
    min_context = 10000
    if available_tokens < min_context:
        logger.warning(f"Calculated context too small ({available_tokens}), using minimum: {min_context}")
        return min_context
    
    logger.info(f"Dynamic context limit for {model}: {available_tokens} tokens")
    return available_tokens

async def get_optimized_project_thinking_config(
    model: str, 
    project_type: str = "general",
    complexity_level: str = "normal"
) -> Optional[types.ThinkingConfig]:
    """프로젝트별 최적화된 사고 설정 생성"""
    if model not in PROJECT_THINKING_OPTIMIZATION:
        return None
    
    config = PROJECT_THINKING_OPTIMIZATION[model]
    
    # 복잡도 레벨 기반 조정
    if complexity_level == "simple":
        budget = config["default_budget"] // 2
    elif complexity_level == "complex":
        budget = config["max_budget"]
    else:
        budget = config["default_budget"]
    
    # 프로젝트 타입별 추가 조정
    if project_type == "assignment":
        # 수행평가는 더 많은 사고 예산 필요
        budget = min(budget * 2, config["max_budget"])
    elif project_type == "record":
        # 생기부 작성은 중간 정도의 사고 예산
        budget = min(int(budget * 1.5), config["max_budget"])
    
    return types.ThinkingConfig(
        thinking_budget=budget,
        include_thoughts=budget > 0
    )

async def compress_project_context_if_needed(
    client,
    model: str,
    messages: List[dict],
    max_tokens: int,
    project_type: Optional[str] = None
) -> List[dict]:
    """프로젝트 컨텍스트 압축 (필요한 경우)"""
    # 토큰 수 계산
    total_tokens = 0
    for msg in messages:
        token_count = count_tokens_with_tiktoken(msg["content"], model)
        total_tokens += token_count.get("input_tokens", 0)
    
    # 압축이 필요한지 확인
    if total_tokens < max_tokens * PROJECT_CONTEXT_COMPRESSION_THRESHOLD:
        return messages
    
    logger.info(f"Project context compression needed: {total_tokens} tokens > {max_tokens * PROJECT_CONTEXT_COMPRESSION_THRESHOLD}")
    
    # 최신 메시지는 유지하고 오래된 메시지들을 요약
    keep_recent = 5  # 프로젝트는 더 많은 최근 메시지 유지
    recent_messages = messages[-keep_recent:]
    old_messages = messages[:-keep_recent]
    
    if not old_messages:
        return recent_messages
    
    # 오래된 메시지들을 요약
    try:
        summary_content = "\n".join([
            f"{msg['role']}: {msg['content']}" 
            for msg in old_messages
        ])
        
        summary_response = client.models.generate_content(
            model="gemini-2.5-flash",  # 요약은 빠른 모델 사용
            contents=[f"다음 프로젝트 대화를 핵심 내용을 중심으로 요약해주세요:\n\n{summary_content}"],
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=1024,  # 프로젝트는 더 긴 요약 허용
                thinking_config=types.ThinkingConfig(thinking_budget=0)  # 요약은 사고 없이
            )
        )
        
        # 요약된 메시지로 교체
        compressed_messages = [
            {"role": "system", "content": f"이전 프로젝트 대화 요약: {summary_response.text}"}
        ] + recent_messages
        
        logger.info(f"Project context compressed: {len(messages)} -> {len(compressed_messages)} messages")
        return compressed_messages
        
    except Exception as e:
        logger.error(f"Project context compression error: {e}", exc_info=True)
        return messages[-keep_recent:]  # 실패시 최근 메시지만 유지

class ProjectStreamingBuffer:
    """프로젝트 스트리밍 응답 버퍼링"""
    def __init__(self, buffer_size: int = PROJECT_STREAMING_BUFFER_SIZE):
        self.buffer = []
        self.buffer_size = buffer_size
        self.current_size = 0
        self.last_flush = time.time()
    
    def add_chunk(self, chunk: str) -> bool:
        """청크 추가, 플러시 필요시 True 반환"""
        self.buffer.append(chunk)
        self.current_size += len(chunk.encode('utf-8'))
        
        # 버퍼가 가득 찼거나 일정 시간이 지난 경우 플러시
        now = time.time()
        return (self.current_size >= self.buffer_size or 
                now - self.last_flush >= PROJECT_STREAMING_FLUSH_INTERVAL)
    
    def flush(self) -> str:
        """버퍼 내용 반환 및 초기화"""
        if not self.buffer:
            return ""
        
        content = "".join(self.buffer)
        self.buffer.clear()
        self.current_size = 0
        self.last_flush = time.time()
        return content

async def generate_gemini_stream_response(
    request: Request,
    messages: list,
    model: str,
    room_id: str,
    db: Session,
    user_id: str,
    project_id: str,
    project_type: Optional[str] = None,
    file_data_list: Optional[List[str]] = None,
    file_types: Optional[List[str]] = None,
    file_names: Optional[List[str]] = None
) -> AsyncGenerator[str, None]:
    try:
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")

        # 프로젝트 정보 가져오기
        project = crud_project.get(db=db, id=project_id)
        
        # 프로젝트 타입에 따른 시스템 프롬프트 구성
        system_prompt = BRIEF_SYSTEM_PROMPT
        if project_type == "assignment":
            system_prompt += "\n\n" + ASSIGNMENT_PROMPT
        elif project_type == "record":
            system_prompt += "\n\n" + RECORD_PROMPT
            
        # 프로젝트 사용자 정의 시스템 지시사항 추가
        if project and project.system_instruction and project.system_instruction.strip():
            system_prompt += "\n\n## 추가 지시사항\n" + project.system_instruction.strip()

        # 🔍 임베딩 검색 자동 실행 (사용자 질문 기반)
        embedding_context = ""
        if messages and len(messages) > 0:
            last_user_message = messages[-1]  # 마지막 사용자 메시지
            if last_user_message.get("role") == "user" and last_user_message.get("content"):
                user_query = last_user_message["content"]
                try:
                    # 임베딩 검색 수행
                    query_embed_result = client.models.embed_content(
                        model="text-embedding-004",
                        contents=user_query,
                        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
                    )
                    
                    if query_embed_result.embeddings:
                        query_embedding = (
                            query_embed_result.embeddings[0].values 
                            if hasattr(query_embed_result.embeddings[0], 'values') 
                            else list(query_embed_result.embeddings[0])
                        )
                        
                        # 데이터베이스에서 유사한 임베딩 검색 (임계값 낮춤)
                        similar_embeddings = crud_embedding.search_similar(
                            db=db,
                            project_id=project_id,
                            query_embedding=query_embedding,
                            top_k=5,
                            threshold=0.4  # 임계값을 0.75에서 0.4로 낮춤
                        )
                        
                        # 검색된 내용을 컨텍스트에 추가
                        if similar_embeddings:
                            relevant_chunks = []
                            for result in similar_embeddings:
                                relevant_chunks.append(f"[{result['file_name']}] {result['content'][:200]}...")  # 200자만 표시
                            
                            embedding_context = f"""
                            
## 📚 관련 자료 (업로드된 파일에서 검색)
{chr(10).join(relevant_chunks)}

위 자료를 참고하여 질문에 답변해주세요.
"""
                            logger.info(f"🔍 임베딩 검색 성공: {len(similar_embeddings)}개 청크 발견")
                            for i, result in enumerate(similar_embeddings):
                                logger.info(f"  [{i+1}] 유사도: {result['similarity']:.3f}, 파일: {result['file_name']}, 내용: {result['content'][:50]}...")
                        else:
                            # 전체 임베딩 개수 확인
                            all_embeddings = crud_embedding.get_by_project(db, project_id)
                            logger.debug(f"   전체 임베딩 개수: {len(all_embeddings)}")
                            if all_embeddings:
                                logger.debug(f"   파일 목록: {list(set(e.file_name for e in all_embeddings))}")
                            logger.debug(f"   사용자 질문: '{user_query}'")
                            logger.debug(f"   임계값: 0.4")
                    else:
                        logger.error("임베딩 생성 실패")
                        
                except Exception as e:
                    logger.error(f"임베딩 검색 중 오류: {e}", exc_info=True)
                    
        # 임베딩 컨텍스트를 시스템 프롬프트에 추가
        if embedding_context:
            system_prompt += embedding_context

        # 메시지 유효성 검사
        if not messages or len(messages) == 0:
            raise HTTPException(
                status_code=400,
                detail="At least one message is required"
            )

        # 토큰 기반 컨텍스트 관리 (chat.py 방식 적용)
        # 프로젝트는 더 큰 컨텍스트 허용 (일반 채팅보다 2배)
        # 프로젝트 컨텍스트 관리 - 동적 한도 계산
        # 시스템 프롬프트 토큰 먼저 계산
        system_tokens = 0
        if system_prompt:
            system_token_info = count_tokens_with_tiktoken(system_prompt, model)
            system_tokens = system_token_info.get("input_tokens", 0)
        
        # 파일 토큰 계산 (최신 API 기준)
        file_tokens = 0
        if file_data_list and file_types:
            for file_type in file_types:
                if file_type.startswith("image/"):
                    file_tokens += 258  # Gemini 2.5 기준: 이미지당 258 토큰
                elif file_type == "application/pdf":
                    file_tokens += 258 * 10  # 예상 페이지 수 * 258 토큰
                elif file_type.startswith("video/"):
                    file_tokens += 263 * 60  # 예상 1분 * 263 토큰/초
                elif file_type.startswith("audio/"):
                    file_tokens += 32 * 60   # 예상 1분 * 32 토큰/초
        
        # 동적 컨텍스트 한도 계산 (최신 API 기준)
        MAX_CONTEXT_TOKENS = get_dynamic_context_limit(model, system_tokens, file_tokens)
        
        # 메시지를 역순으로 처리하여 최근 메시지부터 포함
        valid_messages = []
        total_tokens = system_tokens + file_tokens  # 이미 계산된 시스템 + 파일 토큰 사용
        
        # 메시지를 역순으로 검토하면서 토큰 예산 내에서 포함
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.get("content") and msg["content"].strip():
                # 메시지 토큰 계산 (개선된 함수 사용)
                msg_tokens = count_tokens_with_tiktoken(
                    f"{msg['role']}: {msg['content']}", 
                    model
                )
                msg_token_count = msg_tokens.get("input_tokens", 0)
                
                # 토큰 예산 확인
                if total_tokens + msg_token_count <= MAX_CONTEXT_TOKENS:
                    valid_messages.insert(0, msg)
                    total_tokens += msg_token_count
                else:
                    # 토큰 한계에 도달하면 중단
                    logger.info(f"Project context window limit reached. Including {len(valid_messages)} messages out of {len(messages)}")
                    break
        
        # 최소한 하나의 메시지는 포함되어야 함
        if len(valid_messages) == 0 and len(messages) > 0:
            last_msg = messages[-1]
            if last_msg.get("content") and last_msg["content"].strip():
                valid_messages = [last_msg]
        
        if len(valid_messages) == 0:
            raise HTTPException(
                status_code=400,
                detail="No valid message content found"
            )
        
        logger.info(f"Project context management: Using {len(valid_messages)} messages with {total_tokens} tokens")

        # 컨텍스트 캐싱 임시 비활성화 (API 제약사항으로 인한 오류 방지)
        cached_content_name = None
        # if system_prompt:
        #     # 프로젝트별 캐시 이름 생성
        #     prompt_hash = hashlib.md5(system_prompt.encode()).hexdigest()[:8]
        #     cache_name = f"project_{project_id}_{model}_{prompt_hash}"
        #     
        #     # 캐시 가져오기 또는 생성
        #     cached_content_name = await get_or_create_project_context_cache(
        #         client=client,
        #         project=project,
        #         model=model,
        #         cache_name=cache_name,
        #         ttl=7200  # 2시간 캐싱
        #     )

        # 컨텍스트 압축 적용 (필요한 경우)
        if len(valid_messages) > 10:  # 10개 이상 메시지가 있을 때만 압축 고려
            valid_messages = await compress_project_context_if_needed(
                client=client,
                model=model,
                messages=valid_messages,
                max_tokens=MAX_CONTEXT_TOKENS,
                project_type=project_type or "general"
            )

        # 컨텐츠 구성
        contents = []
        
        # 프로젝트 파일들을 컨텍스트에 추가 (최대 3개)
        try:
            project_files_list = []
            for file in client.files.list():
                if file.display_name and file.display_name.startswith(f"project_{project_id}_"):
                    if file.state.name == "ACTIVE":
                        project_files_list.append(file)
            
            # 최대 3개 파일만 컨텍스트에 추가
            for file in project_files_list[:3]:
                contents.append(file)
        except Exception as e:
            logger.error(f"Failed to load project files for context: {e}", exc_info=True)
        
        # 업로드된 파일들 처리
        if file_data_list and file_types and file_names:
            for file_data, file_type, file_name in zip(file_data_list, file_types, file_names):
                if file_type.startswith("image/"):
                    contents.append(
                        types.Part.from_bytes(
                            data=base64.b64decode(file_data),
                            mime_type=file_type
                        )
                    )
                elif file_type == "application/pdf":
                    contents.append(
                        types.Part.from_bytes(
                            data=base64.b64decode(file_data),
                            mime_type=file_type
                        )
                    )

        # 대화 내용 추가
        conversation_text = ""
        for message in valid_messages:
            role_text = "Human" if message["role"] == "user" else "Assistant"
            conversation_text += f"{role_text}: {message['content']}\n"

        contents.append(conversation_text)

        # 프로젝트별 도구 설정 - 검색과 코드 실행만 사용
        tools = []
        
        # 항상 Google 검색 그라운딩 추가
        tools.append(types.Tool(google_search=types.GoogleSearch()))
        
        # 코드 실행 추가 (데이터 분석용)
        tools.append(types.Tool(code_execution=types.ToolCodeExecution()))

        # 생성 설정 (캐시 비활성화로 인한 간소화)
        generation_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.7,
            top_p=0.95,
            max_output_tokens=8192,
            tools=tools
        )

        # 최적화된 사고 기능 설정 (프로젝트별 적응형)
        optimized_thinking_config = await get_optimized_project_thinking_config(
            model=model,
            project_type=project_type or "general",
            complexity_level="complex" if len(valid_messages) > 5 else "normal"
        )
        if optimized_thinking_config:
            generation_config.thinking_config = optimized_thinking_config
        else:
            # 폴백: 기본 사고 설정
            thinking_budget = 16384 if model.endswith("2.5-pro") else 12288
            if model.endswith("2.5-pro"):
                generation_config.thinking_config = types.ThinkingConfig(
                    thinking_budget=thinking_budget,
                    include_thoughts=True
                )
            elif model.endswith("2.5-flash"):
                generation_config.thinking_config = types.ThinkingConfig(
                    thinking_budget=min(thinking_budget, 24576),
                    include_thoughts=True
                )

        # 프로젝트별 스트리밍 버퍼 초기화
        content_buffer = ProjectStreamingBuffer(PROJECT_STREAMING_BUFFER_SIZE)
        thinking_buffer = ProjectStreamingBuffer(PROJECT_STREAMING_BUFFER_SIZE // 2)

        # 입력 토큰 계산
        input_token_count = count_tokens_with_tiktoken(conversation_text, model)
        input_tokens = input_token_count.get("input_tokens", 0)

        # 스트리밍 응답 생성
        accumulated_content = ""
        accumulated_thinking = ""
        thought_time = 0.0
        citations = []
        web_search_queries = []
        streaming_completed = False  # 스트리밍 완료 여부 체크
        is_disconnected = False  # 연결 중단 플래그 추가
        citations_sent = set()  # 중복 방지를 위한 set

        try:
            response = client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=generation_config
            )

            start_time = time.time()
            
            for chunk in response:
                # 클라이언트 연결 상태 확인
                if await request.is_disconnected():
                    is_disconnected = True
                    logger.warning("Project client disconnected. Stopping stream.")
                    break
                    
                if chunk.candidates and len(chunk.candidates) > 0:
                    candidate = chunk.candidates[0]
                    
                    # 콘텐츠 파트 처리
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            # 사고 내용과 일반 콘텐츠 명확히 분리 (chat.py 방식)
                            if hasattr(part, 'thought') and part.thought:
                                # 사고 내용만 처리
                                if part.text:
                                    accumulated_thinking += part.text
                                    thought_time = time.time() - start_time
                                    try:
                                        yield f"data: {json.dumps({'reasoning_content': part.text, 'thought_time': thought_time})}\n\n"
                                    except (ConnectionError, BrokenPipeError, GeneratorExit):
                                        logger.warning("Project client disconnected during reasoning streaming")
                                        return
                            elif part.text:
                                # 일반 응답 내용만 처리
                                accumulated_content += part.text
                                try:
                                    yield f"data: {json.dumps({'content': part.text})}\n\n"
                                except (ConnectionError, BrokenPipeError, GeneratorExit):
                                    logger.warning("Project client disconnected during content streaming")
                                    return

                    # 그라운딩 메타데이터 처리 (최신 API 구조)
                    if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                        grounding = candidate.grounding_metadata
                        
                        # 웹 검색 쿼리 수집
                        if hasattr(grounding, 'web_search_queries') and grounding.web_search_queries:
                            web_search_queries.extend(grounding.web_search_queries)
                        
                        # grounding chunks에서 citations 추출
                        if hasattr(grounding, 'grounding_chunks') and grounding.grounding_chunks:
                            new_citations = []
                            for chunk_info in grounding.grounding_chunks:
                                if hasattr(chunk_info, 'web') and chunk_info.web:
                                    citation_url = chunk_info.web.uri
                                    # 중복 방지
                                    if citation_url not in citations_sent:
                                        citation = {
                                            "url": citation_url,
                                            "title": chunk_info.web.title if hasattr(chunk_info.web, 'title') else ""
                                        }
                                        citations.append(citation)
                                        new_citations.append(citation)
                                        citations_sent.add(citation_url)
                            
                            # 새로운 인용 정보만 전송
                            if new_citations:
                                try:
                                    yield f"data: {json.dumps({'citations': new_citations})}\n\n"
                                except (ConnectionError, BrokenPipeError, GeneratorExit):
                                    logger.warning("Project client disconnected during citations streaming")
                                    return

            # 연결이 중단되었는지 확인
            if is_disconnected:
                logger.info("Skipping project post-processing due to client disconnection.")
                return
            
            # 스트리밍이 정상적으로 완료됨
            streaming_completed = True
            
            # 최종 메타데이터 전송
            if web_search_queries:
                try:
                    yield f"data: {json.dumps({'search_queries': web_search_queries})}\n\n"
                except (ConnectionError, BrokenPipeError, GeneratorExit):
                    logger.warning("Project client disconnected during final search queries streaming")
                    return

            # 출력 토큰 계산
            output_token_count = count_tokens_with_tiktoken(accumulated_content, model)
            output_tokens = output_token_count.get("input_tokens", 0)
            
            # 사고 토큰 계산
            thinking_tokens = 0
            if accumulated_thinking:
                thinking_token_count = count_tokens_with_tiktoken(accumulated_thinking, model)
                thinking_tokens = thinking_token_count.get("input_tokens", 0)

            # 토큰 사용량 저장 (KST 시간으로 저장)
            from pytz import timezone
            kst = timezone('Asia/Seoul')
            crud_stats.create_token_usage(
                db=db,
                user_id=user_id,
                room_id=room_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens + thinking_tokens,
                timestamp=datetime.now(kst),
                chat_type=f"project_{project_type}" if project_type else None
            )

        except (ConnectionError, BrokenPipeError, GeneratorExit):
            streaming_completed = False  # 클라이언트 연결 끊김 시 완료되지 않음
            logger.warning("Project client disconnected during main streaming loop")
            return
        except Exception as api_error:
            streaming_completed = False  # 에러 발생 시 완료되지 않음
            error_message = f"Gemini API Error: {str(api_error)}"
            try:
                yield f"data: {json.dumps({'error': error_message})}\n\n"
            except (ConnectionError, BrokenPipeError, GeneratorExit):
                logger.warning("Project client disconnected during error streaming")
                return
        
        # 스트리밍이 정상적으로 완료된 경우에만 DB에 저장
        if streaming_completed and accumulated_content:
            logger.debug("=== PROJECT SAVING MESSAGE DEBUG ===")
            logger.debug(f"streaming_completed: {streaming_completed}")
            logger.debug(f"accumulated_content length: {len(accumulated_content)}")
            logger.debug(f"citations count: {len(citations)}")
            message_create = ChatMessageCreate(
                content=accumulated_content,
                role="assistant",
                reasoning_content=accumulated_thinking if accumulated_thinking else None,
                thought_time=thought_time if thought_time > 0 else None,
                citations=citations if citations else None
            )
            crud_project.create_chat_message(db, project_id=project_id, chat_id=room_id, obj_in=message_create)
            logger.info("Project message saved successfully")
            logger.debug("=== END PROJECT SAVING DEBUG ===")
        else:
            logger.info("=== PROJECT MESSAGE NOT SAVED ===")
            logger.info(f"streaming_completed: {streaming_completed}")
            logger.info(f"accumulated_content: {bool(accumulated_content)}")
            logger.info(f"Reason: {'Streaming was interrupted' if not streaming_completed else 'No content'}")
            logger.info("=== END PROJECT NOT SAVED DEBUG ===")

    except Exception as e:
        error_message = f"Project Stream Generation Error: {str(e)}"
        try:
            yield f"data: {json.dumps({'error': error_message})}\n\n"
        except (ConnectionError, BrokenPipeError, GeneratorExit):
            logger.warning("Project client disconnected during final error streaming")
            return

@router.post("/{project_id}/chats/{chat_id}/chat")
async def stream_project_chat(
    *,
    request: Request,
    db: Session = Depends(deps.get_db),
    project_id: str,
    chat_id: str,
    request_data: str = Form(...),
    files: List[UploadFile] = File([]),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    try:
        # JSON 파싱
        try:
            parsed_data = json.loads(request_data)
            chat_request = ChatRequest(**parsed_data)
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON format: {str(e)}")
        
        # 모델 검증
        if chat_request.model not in ALLOWED_MODELS:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid model specified. Allowed models: {ALLOWED_MODELS}"
            )

        # 프로젝트 확인
        project = crud_project.get(db=db, id=project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # 프로젝트 소유권 확인
        if project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        # 채팅방 존재 확인 및 자동 생성
        chat = crud_project.get_chat(db=db, project_id=project_id, chat_id=chat_id)
        if not chat:
            # 채팅방이 없으면 자동으로 생성
            from app.schemas.project import ProjectChatCreate
            chat_data = ProjectChatCreate(
                id=chat_id,
                name="새 채팅",  # 일반 채팅과 동일하게 "새 채팅"으로 시작
                type=project.type
            )
            try:
                chat = crud_project.create_chat(
                    db=db, 
                    project_id=project_id, 
                    obj_in=chat_data, 
                    owner_id=current_user.id,
                    chat_id=chat_id  # URL에서 받은 chat_id 사용
                )
                # 채팅방 생성 후 명시적으로 커밋
                db.commit()
                db.refresh(chat)
            except Exception as e:
                db.rollback()
                raise HTTPException(
                    status_code=500, 
                    detail=f"Failed to create chat room: {str(e)}"
                )

        # 파일 처리
        file_data_list = []
        file_types = []
        file_names = []
        file_info_list = []
        if files and files[0].filename:
            if chat_request.model not in MULTIMODAL_MODELS:
                raise HTTPException(
                    status_code=400,
                    detail="File upload is not supported for this model"
                )
            
            for file in files:
                await validate_file(file)
                file_data, file_type = await process_file_to_base64(file)
                file_data_list.append(file_data)
                file_types.append(file_type)
                file_names.append(file.filename)
                file_info_list.append({
                    "type": file_type,
                    "name": file.filename,
                    "data": file_data
                })

        # 사용자 메시지 저장 (chat.py 방식과 동일하게)
        if chat_request.messages:
            last_message = chat_request.messages[-1]
            user_message = ChatMessageCreate(
                content=last_message["content"],
                role="user",
                room_id=chat_id,  # chat.py와 동일하게 room_id 사용
                files=[{
                    "type": file_type,
                    "name": file_name,
                    "data": file_data
                } for file_data, file_type, file_name in zip(file_data_list, file_types, file_names)] if file_data_list else None
            )
            # 프로젝트 채팅 메시지 저장
            crud_project.create_chat_message(db, project_id=project_id, chat_id=chat_id, obj_in=user_message)

        # 스트리밍 응답 생성
        formatted_messages = [
            {"role": msg["role"], "content": msg["content"]} 
            for msg in chat_request.messages
        ]
        
        return StreamingResponse(
            generate_gemini_stream_response(
                request=request,
                messages=formatted_messages,
                model=chat_request.model,
                room_id=chat_id,
                db=db,
                user_id=current_user.id,
                project_id=project_id,
                project_type=project.type,
                file_data_list=file_data_list,
                file_types=file_types,
                file_names=[f.filename for f in files] if files else None
            ),
            media_type="text/event-stream"
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process chat: {str(e)}"
        )

@router.delete("/{project_id}/chats/{chat_id}")
def delete_project_chat(
    *,
    db: Session = Depends(deps.get_db),
    project_id: str,
    chat_id: str,
) -> Any:
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    chat = crud_project.get_chat(db=db, project_id=project_id, chat_id=chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    db.delete(chat)
    db.commit()
    
    return {"message": "Chat deleted successfully"}

# 프로젝트 목록 조회
@router.get("/", response_model=List[Dict[str, Any]])
def get_projects(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """사용자의 프로젝트 목록을 조회합니다."""
    projects = crud_project.get_multi_by_user(db=db, user_id=current_user.id)
    return projects

# 특정 프로젝트 조회
@router.get("/{project_id}")
def get_project(
    project_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """특정 프로젝트를 조회합니다."""
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return project.to_dict(include_chats=True)

# 프로젝트 생성
@router.post("/")
def create_project(
    project: ProjectCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """새 프로젝트를 생성합니다."""
    created_project = crud_project.create(db=db, obj_in=project, user_id=current_user.id)
    return created_project.to_dict(include_chats=True)

# 프로젝트 수정
@router.patch("/{project_id}")
def update_project(
    project_id: str,
    project: ProjectUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """프로젝트를 수정합니다."""
    db_project = crud_project.get(db=db, id=project_id)
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")
    if db_project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    updated_project = crud_project.update(db=db, db_obj=db_project, obj_in=project)
    return updated_project.to_dict(include_chats=True)

# 프롬프트 개선 API
@router.post("/{project_id}/improve-prompt")
async def improve_prompt(
    project_id: str,
    original_prompt: str = Form(...),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """사용자 프롬프트를 AI가 개선하여 반환합니다."""
    try:
        # 프로젝트 존재 확인
        project = crud_project.get(db=db, id=project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")

        # Gemini 2.0 Flash-Lite 클라이언트 초기화
        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        # 프롬프트 개선을 위한 시스템 프롬프트
        improvement_prompt = """당신은 프롬프트 최적화 전문가입니다. 사용자가 제공한 원본 프롬프트를 분석하고, 더 명확하고 효과적인 프롬프트로 개선해주세요.

## 개선 원칙:
1. **명확성**: 모호한 표현을 구체적으로 개선
2. **구조화**: 요청사항을 논리적으로 정리
3. **맥락 제공**: 필요한 배경 정보 추가
4. **구체성**: 추상적 요청을 구체적으로 변환
5. **실행 가능성**: AI가 수행할 수 있는 형태로 조정

## 개선 방법:
- 핵심 의도는 유지하면서 표현 방식 개선
- 단계별 요청이 필요한 경우 순서 명시
- 예시나 형식이 필요한 경우 구체적으로 제시
- 너무 길어지지 않도록 간결하게 유지

사용자의 원본 프롬프트를 개선된 버전으로만 응답해주세요. 설명이나 부가 내용 없이 개선된 프롬프트만 제공하세요."""

        # 개선 요청 메시지 구성 (Gemini API v2.5 형식)
        content_text = f"다음 프롬프트를 개선해주세요:\n\n{original_prompt}"

        # Gemini 2.0 Flash-Lite로 프롬프트 개선 요청
        response = client.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=[content_text],
            config=types.GenerateContentConfig(
                system_instruction=improvement_prompt,
                temperature=0.3,
                max_output_tokens=2048
            )
        )

        if not response.text:
            raise HTTPException(status_code=500, detail="Failed to improve prompt")

        improved_prompt = response.text.strip()
        
        return {
            "original_prompt": original_prompt,
            "improved_prompt": improved_prompt,
            "status": "success"
        }

    except Exception as e:
        logger.error(f"프롬프트 개선 실패: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"프롬프트 개선에 실패했습니다: {str(e)}"
        )

# 프로젝트 삭제
@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """프로젝트를 삭제합니다."""
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    crud_project.remove(db=db, id=project_id)
    return {"message": "Project deleted successfully"}

# 프로젝트 채팅방 목록 조회
@router.get("/{project_id}/chats")
def get_project_chats(
    project_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """프로젝트의 채팅방 목록을 조회합니다."""
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return crud_project.get_project_chats(db=db, project_id=project_id, owner_id=current_user.id)

# 프로젝트 채팅방 생성
@router.post("/{project_id}/chats")
def create_project_chat(
    project_id: str,
    chat: dict,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """프로젝트에 새 채팅방을 생성합니다."""
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    from app.schemas.project import ProjectChatCreate
    
    # 이름이 없거나 비어있으면 "새 채팅"으로 설정
    if not chat.get("name") or chat.get("name").strip() == "":
        chat["name"] = "새 채팅"
    
    chat_data = ProjectChatCreate(**chat)
    return crud_project.create_chat(db=db, project_id=project_id, obj_in=chat_data, owner_id=current_user.id)

async def generate_project_chat_room_name(first_message: str) -> str:
    """프로젝트 채팅방 전용 AI 기반 제목 생성"""
    try:
        # 빈 메시지 처리
        if not first_message or len(first_message.strip()) == 0:
            return "프로젝트 채팅"
        
        # 간단한 fallback 먼저 생성 (AI 실패 시 사용)
        words = first_message.strip().split()
        fallback_title = " ".join(words[:3]) if len(words) >= 3 else " ".join(words)
        if len(fallback_title) > 20:
            fallback_title = fallback_title[:17] + "..."
        
        # Gemini 클라이언트 확인
        from app.api.api_v1.endpoints.chat import get_gemini_client
        from google.genai import types
        
        client = get_gemini_client()
        if not client:
            logger.info("Gemini client not available, using fallback")
            return fallback_title
        
        # 채팅방 제목 생성 프롬프트
        prompt_template = """Generate a concise and descriptive title in Korean for this chat conversation based on the AI response content.

Requirements:
- Use 2-10 Korean words only
- No emojis or special characters
- Capture the main topic or purpose
- Be specific and informative
- Return only JSON format

Examples:
{{"title": "파이썬 기초 학습"}}
{{"title": "레시피 추천"}}
{{"title": "프로그래밍 질문"}}
{{"title": "일반 대화"}}
{{"title": "인사"}}

AI Response Content: {message}

Generate title as JSON:"""

        # 메시지 길이 제한 (토큰 절약)
        limited_message = first_message[:300] if len(first_message) > 300 else first_message
        
        # 프롬프트 생성
        prompt = prompt_template.format(message=limited_message)
        
        logger.info(f"Generating AI title for project chat: '{limited_message[:50]}...'")
        
        # Gemini API 호출
        try:
            logger.info(f"Calling Gemini API for project chat with model: gemini-2.0-flash-lite")
            response = client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=50
                )
            )
            
            # 응답 텍스트 추출
            response_text = None
            
            if hasattr(response, 'candidates') and response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]
                
                if hasattr(candidate, 'content') and candidate.content:
                    content = candidate.content
                    
                    if hasattr(content, 'parts') and content.parts and len(content.parts) > 0:
                        for part in content.parts:
                            if hasattr(part, 'text') and part.text:
                                response_text = part.text
                                break
            
            elif hasattr(response, 'text') and response.text:
                response_text = response.text
            
            # 응답 텍스트가 있으면 JSON 파싱 시도
            if response_text:
                try:
                    import json
                    import re
                    
                    # 마크다운 코드 블록 제거
                    text = response_text.strip()
                    if text.startswith('```'):
                        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
                        if json_match:
                            text = json_match.group(1).strip()
                    
                    # JSON 파싱
                    result = json.loads(text)
                    if 'title' in result and result['title']:
                        ai_title = result['title'].strip()
                        if len(ai_title) <= 25:
                            logger.info(f"Successfully generated project chat AI title: '{ai_title}'")
                            return ai_title
                        else:
                            logger.info(f"Project chat AI title too long: '{ai_title}'")
                except json.JSONDecodeError as e:
                    logger.debug(f"Project chat JSON decode error: {e}")
                except Exception as e:
                    logger.debug(f"Project chat JSON parsing error: {e}")
            
        except Exception as api_error:
            logger.info(f"Project chat Gemini API error: {api_error}")
        
        # AI 생성 실패 시 fallback 사용
        logger.info(f"Using fallback title for project chat: '{fallback_title}'")
        return fallback_title
        
    except Exception as e:
        logger.error(f"Project chat room name generation error: {e}", exc_info=True)
        return "프로젝트 채팅"

# 프로젝트 채팅방 이름 생성
@router.post("/{project_id}/chats/{chat_id}/generate-name")
async def generate_project_chat_name(
    project_id: str,
    chat_id: str,
    message_content: str = Form(...),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """첫 번째 메시지를 기반으로 프로젝트 채팅방 이름을 생성하고 업데이트합니다."""
    
    # 프로젝트 및 채팅방 소유권 확인
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    try:
        logger.info(f"generate_project_chat_name called - project_id: {project_id}, chat_id: {chat_id}, message: {message_content[:50]}...")
        
        # 프로젝트 채팅방 확인
        project_chat = crud_project.get_chat(db=db, project_id=project_id, chat_id=chat_id)
        if project_chat:
            current_name = getattr(project_chat, 'name', None)
            current_name_str = str(current_name) if current_name is not None else ""
            logger.info(f"Found project chat: {chat_id}, current name: '{current_name_str}'")
            
            # "새 채팅"인 경우에만 제목 생성
            if current_name_str and current_name_str.strip() != "" and current_name_str != "새 채팅":
                logger.info(f"Project chat already has a name: '{current_name_str}'")
                return {
                    "project_id": project_id,
                    "chat_id": chat_id,
                    "generated_name": current_name_str,
                    "message": "Chat already has a name"
                }
        else:
            logger.info(f"Project chat not found: {chat_id} - may not be created yet")
        
        # 프로젝트 채팅방 이름 생성
        generated_name = await generate_project_chat_room_name(message_content)
        logger.info(f"AI generated name for project chat: '{generated_name}'")
        
        # 채팅방 이름 업데이트
        from app.schemas.project import ProjectChatCreate
        chat_update = ProjectChatCreate(name=generated_name)
        
        try:
            logger.info(f"Attempting to update project chat - project_id: {project_id}, chat_id: {chat_id}, update: {chat_update}")
            updated_chat = crud_project.update_chat(
                db=db, 
                project_id=project_id, 
                chat_id=chat_id, 
                obj_in=chat_update, 
                owner_id=current_user.id
            )
            logger.info(f"Project chat name updated successfully: '{generated_name}'")
            
            return {
                "project_id": project_id,
                "chat_id": chat_id,
                "generated_name": generated_name,
                "updated_chat": updated_chat
            }
        except Exception as update_error:
            logger.info(f"Project chat update failed: {update_error} - chat_id: {chat_id}, error type: {type(update_error)}")
            # 채팅방 업데이트에 실패해도 생성된 이름은 반환
            return {
                "project_id": project_id,
                "chat_id": chat_id,
                "generated_name": generated_name,
                "message": "Chat name generated but room not found - may not be created yet"
            }
        
    except Exception as e:
        logger.error(f"Project chat name generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate chat name")

# 프로젝트 채팅방 수정
@router.patch("/{project_id}/chats/{chat_id}")
def update_project_chat(
    project_id: str,
    chat_id: str,
    chat: dict,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """프로젝트 채팅방을 수정합니다."""
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    from app.schemas.chat import ChatUpdate
    chat_data = ChatUpdate(**chat)
    return crud_project.update_chat_by_id(db=db, project_id=project_id, chat_id=chat_id, obj_in=chat_data)

# 프로젝트 채팅방 메시지 조회
@router.get("/{project_id}/chats/{chat_id}/messages")
def get_project_chat_messages(
    project_id: str,
    chat_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """프로젝트 채팅방의 메시지를 조회합니다."""
    project = crud_project.get(db=db, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    messages = crud_project.get_chat_messages(db=db, project_id=project_id, chat_id=chat_id)
    return {"messages": messages}

# 프로젝트별 컨텍스트 캐싱 기능
@router.post("/{project_id}/cache")
async def create_project_context_cache(
    project_id: str,
    content: str = Form(...),
    model: str = Form(...),
    ttl: int = Form(3600),  # 기본 1시간
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트별 컨텍스트 캐시 생성"""
    try:
        # 프로젝트 소유권 확인
        project = crud_project.get(db=db, id=project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        # 프로젝트별 시스템 프롬프트 적용
        system_instruction = BRIEF_SYSTEM_PROMPT
        if project.type == "assignment":
            system_instruction += "\n\n" + ASSIGNMENT_PROMPT
        elif project.type == "record":
            system_instruction += "\n\n" + RECORD_PROMPT
        
        # 캐시 생성
        cache = client.caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                display_name=f"project_{project_id}_cache_{int(time.time())}",
                system_instruction=system_instruction,
                contents=[content],
                ttl=f"{ttl}s"
            )
        )
        
        return {
            "cache_name": cache.name,
            "project_id": project_id,
            "ttl": ttl,
            "message": "Project cache created successfully"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create project cache: {str(e)}")

@router.get("/{project_id}/cache")
async def list_project_context_caches(
    project_id: str,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트별 컨텍스트 캐시 목록 조회"""
    try:
        # 프로젝트 소유권 확인
        project = crud_project.get(db=db, id=project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        caches = []
        for cache in client.caches.list():
            if cache.display_name and cache.display_name.startswith(f"project_{project_id}_cache_"):
                caches.append({
                    "name": cache.name,
                    "display_name": cache.display_name,
                    "model": cache.model,
                    "create_time": cache.create_time.isoformat() if hasattr(cache, 'create_time') and cache.create_time else None,
                    "expire_time": cache.expire_time.isoformat() if hasattr(cache, 'expire_time') and cache.expire_time else None
                })
        
        return {"caches": caches, "project_id": project_id}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list project caches: {str(e)}")

@router.delete("/{project_id}/cache/{cache_name}")
async def delete_project_context_cache(
    project_id: str,
    cache_name: str,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트별 컨텍스트 캐시 삭제"""
    try:
        # 프로젝트 소유권 확인
        project = crud_project.get(db=db, id=project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        client.caches.delete(cache_name)
        
        return {"message": "Project cache deleted successfully", "project_id": project_id}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete project cache: {str(e)}")

# 프로젝트별 임베딩 기능
@router.post("/{project_id}/embeddings")
async def create_project_embeddings(
    project_id: str,
    texts: List[str] = Form(...),
    model: str = Form("text-embedding-004"),
    task_type: str = Form("SEMANTIC_SIMILARITY"),
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트별 텍스트 임베딩 생성"""
    try:
        # 프로젝트 소유권 확인
        project = crud_project.get(db=db, id=project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        embeddings = []
        for text in texts:
            result = client.models.embed_content(
                model=model,
                contents=text,
                config=types.EmbedContentConfig(task_type=task_type)
            )
            embeddings.append({
                "text": text,
                "embedding": result.embeddings[0] if result.embeddings else []
            })
        
        return {
            "embeddings": embeddings,
            "project_id": project_id,
            "project_type": project.type
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create project embeddings: {str(e)}")

# 프로젝트별 프롬프트 생성 기능
@router.post("/{project_id}/generate-prompt")
async def generate_project_prompt(
    project_id: str,
    category: str = Form(...),
    task_description: str = Form(...),
    style: str = Form("친근한"),
    complexity: str = Form("중간"),
    output_format: str = Form("자유형식"),
    include_examples: bool = Form(True),
    include_constraints: bool = Form(False),
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트별 맞춤형 AI 프롬프트 생성기"""
    try:
        # 프로젝트 소유권 확인
        project = crud_project.get(db=db, id=project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        # 프로젝트 타입에 따른 특화된 카테고리 지시
        project_specific_instructions = {
            "assignment": "수행평가와 과제 해결에 특화된 프롬프트를 생성합니다. 평가 기준 충족과 창의적 접근을 모두 고려합니다.",
            "record": "생기부 작성에 특화된 프롬프트를 생성합니다. 교육부 기재요령 준수와 차별화 포인트를 동시에 고려합니다.",
            "general": "일반적인 학습 목적에 최적화된 프롬프트를 생성합니다."
        }
        
        # 카테고리별 전문 시스템 지시 생성
        category_instructions = {
            "학습": "교육 및 학습 최적화 프롬프트 전문가로서, 학습자의 이해도를 높이고 단계적 학습을 유도하는 프롬프트를 생성합니다.",
            "창작": "창의적 콘텐츠 생성 전문가로서, 상상력을 자극하고 독창적인 결과를 도출하는 프롬프트를 생성합니다.",
            "분석": "데이터 분석 및 논리적 사고 전문가로서, 체계적이고 객관적인 분석을 유도하는 프롬프트를 생성합니다.",
            "번역": "다국어 번역 전문가로서, 문맥과 뉘앙스를 정확히 전달하는 번역 프롬프트를 생성합니다.",
            "코딩": "소프트웨어 개발 전문가로서, 효율적이고 안전한 코드 작성을 유도하는 프롬프트를 생성합니다.",
            "비즈니스": "비즈니스 전략 및 의사결정 전문가로서, 실용적이고 결과 지향적인 프롬프트를 생성합니다.",
            "일반": "범용 프롬프트 엔지니어링 전문가로서, 다양한 상황에 적용 가능한 효과적인 프롬프트를 생성합니다."
        }
        
        system_instruction = f"""
        당신은 {category_instructions.get(category, category_instructions["일반"])}
        
        프로젝트 특화 요구사항: {project_specific_instructions.get(project.type, project_specific_instructions["general"])}
        
        프롬프트 생성 원칙:
        1. 명확한 지시사항과 구체적인 기대 결과 포함
        2. 프로젝트 타입({project.type})에 최적화된 접근 방식
        3. 사용자의 의도를 정확히 파악하고 최적의 결과 도출
        4. 교육적 가치와 실용성의 균형
        
        응답 형식:
        - 프롬프트 제목 (프로젝트 타입 반영)
        - 메인 프롬프트 (즉시 사용 가능한 완성 형태)
        - 프로젝트별 특화 팁
        - 응용 및 변형 제안
        """
        
        user_request = f"""
        다음 조건에 맞는 {project.type} 프로젝트 전용 프롬프트를 생성해주세요:
        
        📋 **프로젝트 정보**
        - 프로젝트명: {project.name}
        - 프로젝트 타입: {project.type}
        - 카테고리: {category}
        - 작업 설명: {task_description}
        
        📌 **스타일 설정**
        - 스타일: {style}
        - 복잡도: {complexity}
        - 출력 형식: {output_format}
        - 예시 포함: {'예' if include_examples else '아니오'}
        - 제약사항 포함: {'예' if include_constraints else '아니오'}
        
        생성된 프롬프트는 {project.type} 프로젝트의 특성을 반영하여 최적화해주세요.
        """
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[user_request],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.8,
                max_output_tokens=4000,
                tools=[
                    types.Tool(google_search=types.GoogleSearch()),
                    types.Tool(code_execution=types.ToolCodeExecution())
                ]
            )
        )
        
        return {
            "generated_prompt": response.text,
            "project_id": project_id,
            "project_name": project.name,
            "project_type": project.type,
            "category": category,
            "task_description": task_description,
            "settings": {
                "style": style,
                "complexity": complexity,
                "output_format": output_format,
                "include_examples": include_examples,
                "include_constraints": include_constraints
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate project prompt: {str(e)}")

# 프로젝트별 웹 검색 기능
@router.post("/{project_id}/chats/{chat_id}/search")
async def search_project_web(
    project_id: str,
    chat_id: str,
    request: Request,
    query: str = Form(...),
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트 채팅에서 Google 검색을 사용한 웹 검색 (스트리밍)"""
    try:
        # 프로젝트 소유권 확인
        project = crud_project.get(db=db, id=project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        # 사용자 검색 질문을 DB에 저장
        user_message = ChatMessageCreate(
            content=f"🔍 검색: {query}",
            role="user",
            room_id=chat_id
        )
        crud_project.create_chat_message(db, project_id=project_id, chat_id=chat_id, obj_in=user_message)
        
        async def generate_project_search_stream():
            try:
                client = get_gemini_client()
                if not client:
                    yield f"data: {json.dumps({'error': 'Gemini client not available'})}\n\n"
                    return
                
                # 프로젝트별 시스템 프롬프트 적용
                system_instruction = BRIEF_SYSTEM_PROMPT
                if project.type == "assignment":
                    system_instruction += "\n\n" + ASSIGNMENT_PROMPT
                elif project.type == "record":
                    system_instruction += "\n\n" + RECORD_PROMPT
                
                system_instruction += f"""
                
                현재 프로젝트 정보:
                - 프로젝트명: {project.name}
                - 프로젝트 타입: {project.type}
                - 설명: {project.description or '없음'}
                
                검색 시 프로젝트 맥락을 고려하여 결과를 제공하세요.
                """
                
                # 프로젝트 사용자 정의 시스템 지시사항 추가
                if project.system_instruction and project.system_instruction.strip():
                    system_instruction += "\n\n## 추가 지시사항\n" + project.system_instruction.strip()
                
                # 검색 도구 설정
                tools = [
                    types.Tool(google_search=types.GoogleSearch()),
                    types.Tool(code_execution=types.ToolCodeExecution())
                ]
                
                # 생성 설정
                generation_config = types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
                    max_output_tokens=3000,
                    tools=tools,
                    thinking_config=types.ThinkingConfig(
                        thinking_budget=8192,
                        include_thoughts=True
                    )
                )
                
                # 스트리밍 검색 실행
                response = client.models.generate_content_stream(
                    model="gemini-2.5-flash",
                    contents=[f"프로젝트 '{project.name}' 관련하여 다음에 대해 검색해주세요: {query}"],
                    config=generation_config
                )
                
                accumulated_content = ""
                accumulated_reasoning = ""
                citations = []
                web_search_queries = []
                citations_sent = set()
                search_completed = False
                is_disconnected = False
                
                for chunk in response:
                    if await request.is_disconnected():
                        is_disconnected = True
                        break
                        
                    if chunk.candidates and len(chunk.candidates) > 0:
                        candidate = chunk.candidates[0]
                        
                        # 콘텐츠 처리
                        if candidate.content and candidate.content.parts:
                            for part in candidate.content.parts:
                                if hasattr(part, 'thought') and part.thought:
                                    accumulated_reasoning += part.text
                                    try:
                                        yield f"data: {json.dumps({'reasoning_content': part.text})}\n\n"
                                    except (ConnectionError, BrokenPipeError, GeneratorExit):
                                        return
                                elif part.text:
                                    accumulated_content += part.text
                                    try:
                                        yield f"data: {json.dumps({'content': part.text})}\n\n"
                                    except (ConnectionError, BrokenPipeError, GeneratorExit):
                                        return
                        
                        # 그라운딩 메타데이터 처리
                        if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                            grounding = candidate.grounding_metadata
                            
                            if hasattr(grounding, 'web_search_queries') and grounding.web_search_queries:
                                web_search_queries.extend(grounding.web_search_queries)
                            
                            if hasattr(grounding, 'grounding_chunks') and grounding.grounding_chunks:
                                new_citations = []
                                for chunk_info in grounding.grounding_chunks:
                                    if hasattr(chunk_info, 'web') and chunk_info.web:
                                        citation_url = chunk_info.web.uri
                                        
                                        # Mixed Content 문제 방지: HTTP URL을 HTTPS로 변환
                                        if citation_url.startswith('http://'):
                                            citation_url = citation_url.replace('http://', 'https://', 1)
                                        
                                        if citation_url not in citations_sent:
                                            citation = {
                                                "url": citation_url,
                                                "title": chunk_info.web.title if hasattr(chunk_info.web, 'title') else ""
                                            }
                                            citations.append(citation)
                                            new_citations.append(citation)
                                            citations_sent.add(citation_url)
                                
                                if new_citations:
                                    try:
                                        yield f"data: {json.dumps({'citations': new_citations})}\n\n"
                                    except (ConnectionError, BrokenPipeError, GeneratorExit):
                                        return
                
                if is_disconnected:
                    return
                
                search_completed = True
                
                if web_search_queries:
                    try:
                        yield f"data: {json.dumps({'search_queries': web_search_queries})}\n\n"
                    except (ConnectionError, BrokenPipeError, GeneratorExit):
                        return
                
            except Exception as e:
                search_completed = False
                try:
                    yield f"data: {json.dumps({'error': f'Project search failed: {str(e)}'})}\n\n"
                except (ConnectionError, BrokenPipeError, GeneratorExit):
                    return
            
            # 검색이 정상적으로 완료된 경우에만 DB에 저장
            if search_completed and accumulated_content:
                ai_message = ChatMessageCreate(
                    content=accumulated_content,
                    role="assistant",
                    room_id=chat_id,
                    reasoning_content=accumulated_reasoning if accumulated_reasoning else None,
                    citations=citations if citations else None
                )
                crud_project.create_chat_message(db, project_id=project_id, chat_id=chat_id, obj_in=ai_message)
        
        return StreamingResponse(
            generate_project_search_stream(),
            media_type="text/plain"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Project search failed: {str(e)}")

# 프로젝트별 통계 조회 기능
@router.get("/{project_id}/stats/token-usage")
async def get_project_token_usage(
    project_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트별 토큰 사용량 조회"""
    try:
        # 프로젝트 소유권 확인
        project = crud_project.get(db=db, id=project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        # KST 시간 문자열을 datetime으로 변환
        start_dt = None
        end_dt = None
        
        if start_date:
            # "YYYY-MM-DD HH:MM:SS" 형식의 KST 시간을 파싱
            start_dt = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
        if end_date:
            # "YYYY-MM-DD HH:MM:SS" 형식의 KST 시간을 파싱
            end_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
        
        # 각 채팅방별 토큰 사용량 합계
        total_usage = crud_stats.get_token_usage(
            db=db,
            start_date=start_dt,
            end_date=end_dt,
            user_id=current_user.id
        )
        
        return {
            "project_id": project_id,
            "project_name": project.name,
            "project_type": project.type,
            "token_usage": total_usage,
            "period": {
                "start_date": start_date,
                "end_date": end_date
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get project token usage: {str(e)}")

@router.get("/{project_id}/stats/chat-usage")
async def get_project_chat_usage(
    project_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트별 채팅 사용량 조회"""
    try:
        # 프로젝트 소유권 확인
        project = crud_project.get(db=db, id=project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        # KST 시간 문자열을 datetime으로 변환
        start_dt = None
        end_dt = None
        
        if start_date:
            # "YYYY-MM-DD HH:MM:SS" 형식의 KST 시간을 파싱
            start_dt = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
        if end_date:
            # "YYYY-MM-DD HH:MM:SS" 형식의 KST 시간을 파싱
            end_dt = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
        
        # 프로젝트별 채팅 통계 조회
        chat_stats = crud_stats.get_chat_statistics(
            db=db,
            start_date=start_dt,
            end_date=end_dt,
            user_id=current_user.id
        )
        
        return {
            "project_id": project_id,
            "project_name": project.name,
            "project_type": project.type,
            "chat_statistics": chat_stats,
            "period": {
                "start_date": start_date,
                "end_date": end_date
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get project chat usage: {str(e)}")

# 프로젝트별 컨텍스트 캐시 유틸리티 함수
async def get_or_create_project_context_cache(
    client,
    project: Project,
    model: str,
    cache_name: str,
    ttl: int = 7200
) -> Optional[str]:
    """프로젝트별 컨텍스트 캐시를 가져오거나 생성합니다."""
    try:
        # 기존 캐시 확인
        for cache in client.caches.list():
            if cache.display_name == cache_name and cache.model == model:
                # 캐시가 만료되지 않았는지 확인
                if hasattr(cache, 'expire_time') and cache.expire_time and cache.expire_time > datetime.now(timezone.utc):
                    logger.info(f"Using existing project cache: {cache_name}")
                    return cache.name
        
        # 프로젝트별 시스템 프롬프트 구성
        system_instruction = BRIEF_SYSTEM_PROMPT
        if project.type == "assignment":
            system_instruction += "\n\n" + ASSIGNMENT_PROMPT
        elif project.type == "record":
            system_instruction += "\n\n" + RECORD_PROMPT
        
        # 새 캐시 생성 (빈 contents 문제 해결)
        logger.info(f"Creating new project cache: {cache_name}")
        cache = client.caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                display_name=cache_name,
                system_instruction=system_instruction,
                contents=["프로젝트 컨텍스트 캐시"],  # 빈 배열 대신 최소 콘텐츠 제공
                ttl=f"{ttl}s"
            )
        )
        return cache.name
    except Exception as e:
        logger.error(f"Project cache creation error: {e}", exc_info=True)
        return None 

# 프로젝트별 파일 업로드 및 관리 API
@router.post("/{project_id}/files/upload")
async def upload_project_file(
    project_id: str,
    files: List[UploadFile] = File(...),
    description: Optional[str] = Form(None),
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트에 파일 업로드 및 임베딩 생성"""
    # 타임아웃 설정 (120초)
    UPLOAD_TIMEOUT = 120
    
    try:
        # 타임아웃 설정으로 전체 업로드 프로세스 제한
        async with asyncio.timeout(UPLOAD_TIMEOUT):
            # 프로젝트 소유권 확인
            project = crud_project.get(db=db, id=project_id)
            if not project or project.user_id != current_user.id:
                raise HTTPException(status_code=403, detail="Not enough permissions")
            
            client = get_gemini_client()
            if not client:
                raise HTTPException(status_code=500, detail="Gemini client not available")
            
            uploaded_files = []
            
            for file in files:
                # 파일 유효성 검사
                if not await validate_file(file):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid file: {file.filename}"
                    )
                
                # Gemini File API로 업로드
                try:
                    # 파일을 메모리에서 읽기
                    file_content = await file.read()
                    
                    # 파일 크기 재검증
                    if len(file_content) > MAX_FILE_SIZE:
                        raise HTTPException(
                            status_code=400,
                            detail=f"File {file.filename} is too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"
                        )
                    
                    # Gemini File API 제한 확인 및 처리
                    if len(file_content) > GEMINI_INLINE_DATA_LIMIT:
                        logger.warning(f"Warning: File {file.filename} ({len(file_content)} bytes) exceeds Gemini inline data limit. Using File API instead.")
                        # 큰 파일은 File API를 통해 처리 (이미 현재 구현)
                    
                    # File API를 사용하여 업로드
                    uploaded_file = client.files.upload(
                        file=io.BytesIO(file_content),
                        config=dict(
                            mime_type=file.content_type,
                            display_name=f"project_{project_id}_{file.filename}"
                        )
                    )
                    
                    # 파일이 처리될 때까지 대기 (최대 60초로 증가)
                    max_wait_time = 60
                    wait_time = 0
                    while uploaded_file.state.name == 'PROCESSING' and wait_time < max_wait_time:
                        await asyncio.sleep(2)
                        wait_time += 2
                        try:
                            uploaded_file = client.files.get(name=uploaded_file.name)
                        except Exception as e:
                            logger.error(f"Error checking file status: {e}", exc_info=True)
                            break
                    
                    # 처리 상태 확인
                    if uploaded_file.state.name != 'ACTIVE':
                        logger.warning(f"Warning: File {file.filename} is in state {uploaded_file.state.name}")
                    
                    # file.name에서 'files/' 제거 (clean_file_id 정의)
                    clean_file_id = uploaded_file.name.replace("files/", "") if uploaded_file.name.startswith("files/") else uploaded_file.name
                    
                    # 텍스트 추출 및 임베딩 생성 (개선된 방식)
                    extracted_text = ""
                    embeddings = []
                    embedding_data_list = []  # 항상 초기화
                
                try:
                    # 파일이 활성 상태일 때만 텍스트 추출
                    if uploaded_file.state.name == 'ACTIVE':
                        # PDF 파일 처리 (강화된 방식)
                        if file.content_type == "application/pdf":
                            # 다중 시도 방식으로 PDF 텍스트 추출
                            extract_attempts = [
                                # 1차 시도: 기본 텍스트 추출
                                {
                                    "prompt": "이 PDF 문서의 모든 텍스트를 정확히 추출해주세요. 표, 그래프, 수식, 도표의 내용도 포함해서 최대한 자세히 추출해주세요. 텍스트가 없거나 추출할 수 없는 경우 '텍스트 없음'이라고 답변해주세요.",
                                    "max_tokens": 8000
                                },
                                # 2차 시도: 이미지 기반 OCR (스캔 문서 대응)
                                {
                                    "prompt": "이 문서를 스캔된 이미지로 인식하여 모든 텍스트를 OCR로 추출해주세요. 수식, 표, 그래프의 내용도 포함해서 텍스트로 변환해주세요. 한국어와 영어 모두 정확히 인식해주세요. 읽을 수 없는 부분은 [읽을 수 없음]으로 표시하세요.",
                                    "max_tokens": 8000
                                },
                                # 3차 시도: 구조화된 추출
                                {
                                    "prompt": "이 문서를 다음과 같이 구조화하여 텍스트를 추출해주세요:\n\n[제목]\n[본문 내용]\n[표/그래프 내용]\n[수식]\n[기타 정보]\n\n각 섹션별로 내용을 체계적으로 추출하고, 내용이 없는 섹션은 '없음'으로 표시하세요.",
                                    "max_tokens": 8000
                                },
                                # 4차 시도: 이미지 분석 모드
                                {
                                    "prompt": "이 문서를 이미지 분석 모드로 처리해주세요. 텍스트, 이미지, 도형, 표를 모두 설명하고 포함된 모든 텍스트를 추출해주세요. 시각적 요소도 텍스트로 설명해주세요.",
                                    "max_tokens": 8000
                                }
                            ]
                            
                            for attempt_idx, attempt in enumerate(extract_attempts):
                                try:
                                    logger.info(f"PDF 텍스트 추출 시도 {attempt_idx + 1}/{len(extract_attempts)}: {file.filename}")
                                    
                                    extract_response = client.models.generate_content(
                                        model="gemini-2.5-flash",
                                        contents=[
                                            uploaded_file,
                                            attempt["prompt"]
                                        ],
                                        config=types.GenerateContentConfig(
                                            temperature=0,
                                            max_output_tokens=attempt["max_tokens"]
                                        )
                                    )
                                    
                                    if extract_response and hasattr(extract_response, 'text') and extract_response.text:
                                        extracted_text = extract_response.text[:12000]  # 최대 12000자로 증가
                                        if len(extracted_text.strip()) > 100:  # 최소 100자 이상
                                            logger.info(f"PDF 텍스트 추출 성공 (시도 {attempt_idx + 1}): {len(extracted_text)}자")
                                            break
                                    else:
                                        logger.warning(f"PDF 텍스트 추출 실패 (시도 {attempt_idx + 1}): 응답이 비어있음")
                                        
                                except Exception as e:
                                    logger.error(f"PDF 텍스트 추출 시도 {attempt_idx + 1} 실패: {e}", exc_info=True)
                                    continue
                            
                            # 모든 시도 실패 시 폴백
                            if not extracted_text or len(extracted_text.strip()) < 50:
                                # 파일 메타데이터 기반 기본 정보 생성
                                extracted_text = f"""
[파일 정보]
파일명: {file.filename}
파일 타입: PDF 문서
상태: 텍스트 추출 실패
처리 시간: {datetime.now().isoformat()}

[알림]
이 PDF 문서는 다음 중 하나의 이유로 텍스트 추출이 어렵습니다:
1. 스캔된 이미지 형태의 PDF
2. 복잡한 레이아웃 구조
3. 암호화된 PDF
4. 손글씨 또는 특수 폰트 사용
5. 그래픽 위주의 문서

[대안]
- 다른 PDF 뷰어에서 텍스트 복사 후 텍스트 파일로 업로드
- 이미지로 스크린샷 후 이미지 파일로 업로드
- 파일을 다시 PDF로 내보내기 시도
                                """.strip()
                                logger.warning(f"PDF 텍스트 추출 완전 실패 - 기본 정보 생성: {file.filename}")
                                
                        # 일반 텍스트 파일 처리
                        elif file.content_type in ["text/plain"] or file.content_type.startswith("text/"):
                            try:
                                extract_response = client.models.generate_content(
                                    model="gemini-2.5-flash",
                                    contents=[
                                        uploaded_file,
                                        "이 텍스트 파일의 내용을 완전히 추출해주세요."
                                    ],
                                    config=types.GenerateContentConfig(
                                        temperature=0,
                                        max_output_tokens=8000
                                    )
                                )
                                
                                if extract_response and hasattr(extract_response, 'text') and extract_response.text:
                                    extracted_text = extract_response.text[:10000]
                                else:
                                    extracted_text = "텍스트 파일 추출 실패: 응답이 비어있습니다."
                                    
                            except Exception as e:
                                extracted_text = f"텍스트 파일 추출 실패: {str(e)}"
                                logger.error(f"텍스트 파일 추출 실패: {file.filename} - {e}", exc_info=True)
                                
                        # 이미지 파일 처리 (강화된 OCR)
                        elif file.content_type.startswith("image/"):
                            # 다중 시도 방식으로 이미지 OCR
                            ocr_attempts = [
                                # 1차 시도: 기본 OCR
                                {
                                    "prompt": "이 이미지에서 모든 텍스트를 정확히 추출해주세요. 한국어와 영어 모두 인식하고, 표, 그래프, 도표의 내용도 포함해주세요.",
                                    "max_tokens": 4000
                                },
                                # 2차 시도: 구조화된 OCR
                                {
                                    "prompt": "이 이미지를 자세히 분석하여 텍스트를 구조화해서 추출해주세요. 제목, 본문, 표, 그래프 등을 구분하여 텍스트로 변환해주세요.",
                                    "max_tokens": 4000
                                },
                                # 3차 시도: 수식 및 기호 포함 OCR
                                {
                                    "prompt": "이 이미지에서 텍스트, 수식, 기호, 표를 모두 추출해주세요. 특히 수학 기호나 특수 문자도 정확히 인식해주세요.",
                                    "max_tokens": 4000
                                }
                            ]
                            
                            for attempt_idx, attempt in enumerate(ocr_attempts):
                                try:
                                    logger.info(f"이미지 OCR 시도 {attempt_idx + 1}/{len(ocr_attempts)}: {file.filename}")
                                    
                                    extract_response = client.models.generate_content(
                                        model="gemini-2.5-flash",
                                        contents=[
                                            uploaded_file,
                                            attempt["prompt"]
                                        ],
                                        config=types.GenerateContentConfig(
                                            temperature=0,
                                            max_output_tokens=attempt["max_tokens"]
                                        )
                                    )
                                    
                                    if extract_response and hasattr(extract_response, 'text') and extract_response.text:
                                        extracted_text = extract_response.text[:10000]
                                        if len(extracted_text.strip()) > 50:  # 최소 50자 이상
                                            logger.info(f"이미지 OCR 성공 (시도 {attempt_idx + 1}): {len(extracted_text)}자")
                                            break
                                    else:
                                        logger.warning(f"이미지 OCR 실패 (시도 {attempt_idx + 1}): 응답이 비어있음")
                                        
                                except Exception as e:
                                    logger.error(f"이미지 OCR 시도 {attempt_idx + 1} 실패: {e}", exc_info=True)
                                    continue
                            
                            # 모든 시도 실패 시 폴백
                            if not extracted_text or len(extracted_text.strip()) < 20:
                                # 이미지 메타데이터 기반 기본 정보 생성
                                extracted_text = f"""
[이미지 정보]
파일명: {file.filename}
파일 타입: {file.content_type}
상태: OCR 텍스트 추출 실패
처리 시간: {datetime.now().isoformat()}

[알림]
이 이미지에서 텍스트 추출이 어려운 이유:
1. 텍스트가 없는 순수 이미지
2. 손글씨나 특수 폰트 사용
3. 이미지 품질이 낮음 (해상도, 흐림)
4. 복잡한 배경이나 노이즈
5. 기울어지거나 왜곡된 텍스트

[대안]
- 이미지 품질을 높여서 다시 업로드
- 텍스트 부분만 크롭해서 업로드
- 텍스트를 직접 타이핑해서 텍스트 파일로 업로드
                                """.strip()
                                logger.warning(f"이미지 OCR 완전 실패 - 기본 정보 생성: {file.filename}")
                        
                        # 워드 문서 처리
                        elif file.content_type in [
                            'application/msword',
                            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                        ]:
                            try:
                                extract_response = client.models.generate_content(
                                    model="gemini-2.5-flash",
                                    contents=[
                                        uploaded_file,
                                        "이 워드 문서의 모든 텍스트를 추출해주세요. 표, 그래프, 이미지 설명도 포함해서 완전히 추출해주세요."
                                    ],
                                    config=types.GenerateContentConfig(
                                        temperature=0,
                                        max_output_tokens=8000
                                    )
                                )
                                
                                if extract_response and hasattr(extract_response, 'text') and extract_response.text:
                                    extracted_text = extract_response.text[:10000]
                                else:
                                    extracted_text = "워드 문서 추출 실패: 응답이 비어있습니다."
                                    
                            except Exception as e:
                                extracted_text = f"워드 문서 추출 실패: {str(e)}"
                                logger.error(f"워드 문서 추출 실패: {file.filename} - {e}", exc_info=True)
                        
                        # 추출된 텍스트가 유효한 경우 임베딩 생성
                        if (extracted_text and len(extracted_text.strip()) > 30 and 
                            not any(fail_text in extracted_text for fail_text in [
                                "추출 실패", "OCR 실패", "응답이 비어있습니다"
                            ])):
                            
                            # 텍스트를 청크로 분할 (개선된 방식)
                            chunk_size = 1000  # 청크 크기 조정
                            overlap = 100      # 중복 범위 조정
                            text_chunks = []
                            
                            # 문단 단위로 먼저 분할
                            paragraphs = extracted_text.split('\n\n')
                            current_chunk = ""
                            
                            for paragraph in paragraphs:
                                if len(current_chunk) + len(paragraph) <= chunk_size:
                                    current_chunk += paragraph + "\n\n"
                                else:
                                    if current_chunk.strip():
                                        text_chunks.append(current_chunk.strip())
                                    current_chunk = paragraph + "\n\n"
                            
                            if current_chunk.strip():
                                text_chunks.append(current_chunk.strip())
                            
                            # 청크가 너무 큰 경우 강제 분할
                            final_chunks = []
                            for chunk in text_chunks:
                                if len(chunk) > chunk_size:
                                    for i in range(0, len(chunk), chunk_size - overlap):
                                        sub_chunk = chunk[i:i + chunk_size]
                                        if sub_chunk.strip():
                                            final_chunks.append(sub_chunk.strip())
                                else:
                                    final_chunks.append(chunk)
                            
                            logger.info(f"텍스트 청크 생성 완료: {len(final_chunks)}개 청크")
                            
                            # 임베딩 생성 (병렬 처리 고려)
                            for i, chunk in enumerate(final_chunks):
                                if len(chunk.strip()) < 20:  # 너무 짧은 청크는 제외
                                    continue
                                    
                                try:
                                    embed_result = client.models.embed_content(
                                        model="text-embedding-004",
                                        contents=chunk,
                                        config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT")
                                    )
                                    
                                    if embed_result.embeddings:
                                        # 임베딩 벡터 추출
                                        embedding_vector = (
                                            embed_result.embeddings[0].values 
                                            if hasattr(embed_result.embeddings[0], 'values') 
                                            else list(embed_result.embeddings[0])
                                        )
                                        
                                        # 데이터베이스 저장용 데이터 준비
                                        embedding_data_list.append({
                                            "project_id": project_id,
                                            "file_id": clean_file_id,
                                            "file_name": file.filename,
                                            "chunk_index": i,
                                            "chunk_text": chunk,
                                            "embedding_vector": embedding_vector,
                                            "embedding_model": "text-embedding-004",
                                            "task_type": "RETRIEVAL_DOCUMENT",
                                            "chunk_size": len(chunk),
                                            "similarity_threshold": 0.75
                                        })
                                        
                                        # 기존 형식도 유지 (하위 호환성)
                                        embeddings.append({
                                            "chunk_index": i,
                                            "text": chunk,
                                            "embedding": embed_result.embeddings[0],
                                            "size": len(chunk)
                                        })
                                        
                                except Exception as e:
                                    logger.error(f"임베딩 생성 실패 (청크 {i}): {e}", exc_info=True)
                                    continue
                            
                            logger.info(f"임베딩 생성 완료: {len(embedding_data_list)}개 임베딩")
                        
                        else:
                            logger.warning(f"텍스트 추출 결과가 임베딩 생성에 부적합: {file.filename}")
                    
                    else:
                        logger.warning(f"파일이 ACTIVE 상태가 아님: {file.filename} (상태: {uploaded_file.state.name})")
                        extracted_text = f"파일 처리 대기 중: {uploaded_file.state.name}"
                        
                except Exception as e:
                    logger.error(f"파일 처리 중 오류 발생: {file.filename} - {e}", exc_info=True)
                    extracted_text = f"파일 처리 실패: {str(e)}"
                
                # 데이터베이스에 임베딩 저장
                if embedding_data_list:
                    try:
                        embedding_creates = [ProjectEmbeddingCreate(**data) for data in embedding_data_list]
                        saved_embeddings = crud_embedding.batch_create_embeddings(db, embedding_creates)
                        logger.info(f"데이터베이스에 저장된 임베딩: {len(saved_embeddings)}개 (파일: {file.filename})")
                    except Exception as e:
                        logger.error(f"임베딩 데이터베이스 저장 실패: {e}", exc_info=True)
                else:
                    logger.warning(f"저장할 임베딩이 없음: {file.filename}")
                
                # 파일 정보 저장 (임베딩 정보 포함)
                file_info = {
                    "file_id": clean_file_id,
                    "original_name": file.filename,
                    "mime_type": file.content_type,
                    "size": len(file_content),
                    "uri": uploaded_file.uri,
                    "state": uploaded_file.state.name,
                    "upload_time": datetime.now().isoformat(),
                    "description": description,
                    "extracted_text": extracted_text,
                    "processing_status": "completed" if uploaded_file.state.name == 'ACTIVE' else "processing",
                    "embeddings": embeddings if embeddings else [],
                    "embedding_stats": {
                        "chunks_count": len(embeddings),
                        "total_chars": sum(chunk["size"] for chunk in embeddings) if embeddings else 0,
                        "embedding_model": "text-embedding-004",
                        "has_embeddings": len(embeddings) > 0
                    }
                }
                
                uploaded_files.append(file_info)
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error uploading file {file.filename}: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to upload file {file.filename}: {str(e)}"
                )
        
        return {
            "project_id": project_id,
            "uploaded_files": uploaded_files,
            "total_files": len(uploaded_files),
            "message": f"Successfully uploaded {len(uploaded_files)} files"
        }
    
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=408, 
            detail="파일 업로드 시간이 초과되었습니다. 다시 시도해주세요."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload files: {str(e)}")

@router.get("/{project_id}/files")
async def list_project_files(
    project_id: str,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트에 업로드된 파일 목록 조회"""
    try:
        # 프로젝트 소유권 확인
        project = crud_project.get(db=db, id=project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        # 프로젝트 관련 파일들 조회
        project_files = []
        for file in client.files.list():
            if file.display_name and file.display_name.startswith(f"project_{project_id}_"):
                # file.name에서 'files/' 제거 (Gemini API에서 files/file_id 형태로 반환됨)
                clean_file_id = file.name.replace("files/", "") if file.name.startswith("files/") else file.name
                
                file_info = {
                    "file_id": clean_file_id,
                    "display_name": file.display_name,
                    "original_name": file.display_name.replace(f"project_{project_id}_", ""),
                    "uri": file.uri,
                    "state": file.state.name,
                    "create_time": file.create_time.isoformat() if hasattr(file, 'create_time') and file.create_time else None,
                    "expire_time": file.expire_time.isoformat() if hasattr(file, 'expire_time') and file.expire_time else None
                }
                project_files.append(file_info)
        
        return {
            "project_id": project_id,
            "files": project_files,
            "total_count": len(project_files)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list project files: {str(e)}")

@router.delete("/{project_id}/files/{file_id}")
async def delete_project_file(
    project_id: str,
    file_id: str,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트 파일 삭제"""
    try:
        # 프로젝트 소유권 확인
        project = crud_project.get(db=db, id=project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        # Gemini API는 files/file_id 형태를 기대하므로 files/ 접두사 추가
        full_file_id = f"files/{file_id}" if not file_id.startswith("files/") else file_id
        
        # 관련 임베딩 먼저 삭제
        try:
            deleted_embeddings = crud_embedding.delete_by_file(db, project_id, file_id)
            logger.info(f"Deleted {deleted_embeddings} embeddings for file {file_id}")
        except Exception as e:
            logger.error(f"Failed to delete embeddings for file {file_id}: {e}", exc_info=True)
        
        # 파일 삭제
        try:
            client.files.delete(name=full_file_id)
        except Exception as e:
            logger.error(f"Failed to delete file {full_file_id}: {e}", exc_info=True)
            # 파일이 이미 삭제되었거나 존재하지 않는 경우도 성공으로 처리
            pass
        
        return {
            "message": "File deleted successfully",
            "project_id": project_id,
            "file_id": file_id
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")

# 프로젝트별 지식베이스 검색 API
@router.post("/{project_id}/knowledge/search")
async def search_project_knowledge(
    project_id: str,
    query: str = Form(...),
    top_k: int = Form(5),
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트 업로드 파일들에서 관련 정보 검색"""
    try:
        # 프로젝트 소유권 확인
        project = crud_project.get(db=db, id=project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        # geminiapiupdate 참고: 쿼리 임베딩 생성 시 RETRIEVAL_QUERY 태스크 타입 사용
        query_embed_result = client.models.embed_content(
            model="text-embedding-004",
            contents=query,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
        )
        
        if not query_embed_result.embeddings:
            raise HTTPException(status_code=500, detail="Failed to generate query embedding")
        
        # 임베딩 벡터 추출
        query_embedding = query_embed_result.embeddings[0].values if hasattr(query_embed_result.embeddings[0], 'values') else list(query_embed_result.embeddings[0])
        
        # 데이터베이스에서 유사도 기반 검색 수행 (임계값 낮춤)
        try:
            logger.info(f"🔍 지식베이스 검색 시작: '{query}'")
            logger.info(f"   프로젝트 ID: {project_id}")
            logger.info(f"   요청 결과 수: {top_k}")
            
            similar_embeddings = crud_embedding.search_similar(
                db=db,
                project_id=project_id,
                query_embedding=query_embedding,
                top_k=top_k,
                threshold=0.4  # 임계값을 0.75에서 0.4로 낮춤
            )
            
            logger.info(f"   검색된 임베딩 수: {len(similar_embeddings)}")
            
            # 검색 결과를 적절한 형태로 변환
            top_chunks = []
            for i, result in enumerate(similar_embeddings):
                top_chunks.append({
                    "text": result["content"],
                    "similarity": result["similarity"],
                    "source_file": result["file_name"],
                    "chunk_index": result["chunk_index"]
                })
                logger.info(f"   [{i+1}] 유사도: {result['similarity']:.3f}, 파일: {result['file_name']}")
                
        except Exception as e:
            logger.error(f"❌ 지식베이스 검색 오류: {e}", exc_info=True)
            # 디버깅을 위한 추가 정보
            all_embeddings = crud_embedding.get_by_project(db, project_id)
            logger.debug(f"   전체 임베딩 개수: {len(all_embeddings)}")
            if all_embeddings:
                logger.debug(f"   파일 목록: {list(set(e.file_name for e in all_embeddings))}")
            # 폴백: 빈 결과 반환
            top_chunks = []
        
        # 검색 결과 생성
        search_results = []
        if top_chunks:
            # 관련 청크들을 하나의 컨텍스트로 결합
            combined_context = "\n\n".join([
                f"[{chunk['source_file']}] {chunk['text']}"
                for chunk in top_chunks
            ])
            
            # AI를 사용하여 답변 생성
            search_response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    f"""
                    다음은 업로드된 파일들에서 추출한 관련 정보입니다:
                    
                    {combined_context}
                    
                    위 정보를 바탕으로 다음 질문에 답변해주세요:
                    질문: {query}
                    
                    답변 형식:
                    1. 핵심 내용 요약
                    2. 구체적인 답변
                    3. 출처 및 참고사항
                    
                    관련 정보가 부족한 경우 "제공된 자료에서 충분한 정보를 찾을 수 없습니다"라고 답변해주세요.
                    """
                ],
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=2000
                )
            )
            
            search_results.append({
                "content": search_response.text,
                "relevance_score": max(chunk["similarity"] for chunk in top_chunks),
                "source_chunks": len(top_chunks),
                "source_files": list(set(chunk["source_file"] for chunk in top_chunks))
            })
        
        return {
            "project_id": project_id,
            "query": query,
            "results": search_results,
            "total_results": len(search_results),
            "embedding_stats": crud_embedding.get_embedding_stats(db, project_id)  # 임베딩 통계 추가
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search knowledge: {str(e)}")

# 임베딩 통계 조회 API 추가
@router.get("/{project_id}/embeddings/stats")
async def get_project_embedding_stats(
    project_id: str,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트 임베딩 통계 조회"""
    try:
        # 프로젝트 소유권 확인
        project = crud_project.get(db=db, id=project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        # 임베딩 통계 조회
        stats = crud_embedding.get_embedding_stats(db, project_id)
        
        # 최근 임베딩 정보 조회
        recent_embeddings = crud_embedding.get_by_project(db, project_id)
        
        # 파일별 통계
        file_stats = {}
        for embedding in recent_embeddings:
            file_name = embedding.file_name
            if file_name not in file_stats:
                file_stats[file_name] = {
                    "chunks": 0,
                    "total_chars": 0,
                    "embedding_model": embedding.embedding_model,
                    "task_type": embedding.task_type
                }
            file_stats[file_name]["chunks"] += 1
            file_stats[file_name]["total_chars"] += embedding.chunk_size
        
        return {
            "project_id": project_id,
            "project_name": project.name,
            "embedding_stats": stats,
            "file_stats": file_stats,
            "embedding_model": "text-embedding-004",
            "supported_task_types": ["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"],
            "threshold": 0.75
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get embedding stats: {str(e)}")

# 임베딩 재생성 API 추가
@router.post("/{project_id}/embeddings/regenerate")
async def regenerate_project_embeddings(
    project_id: str,
    file_id: Optional[str] = None,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db)
):
    """프로젝트 임베딩 재생성 (특정 파일 또는 전체)"""
    try:
        # 프로젝트 소유권 확인
        project = crud_project.get(db=db, id=project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")
        
        if file_id:
            # 특정 파일의 임베딩만 재생성
            deleted_count = crud_embedding.delete_by_file(db, project_id, file_id)
            message = f"Regenerated embeddings for file {file_id} (deleted {deleted_count} old embeddings)"
        else:
            # 전체 프로젝트 임베딩 재생성
            deleted_count = crud_embedding.delete_by_project(db, project_id)
            message = f"Regenerated all project embeddings (deleted {deleted_count} old embeddings)"
        
        return {
            "project_id": project_id,
            "message": message,
            "deleted_embeddings": deleted_count,
            "note": "파일을 다시 업로드하여 새로운 임베딩을 생성해주세요."
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to regenerate embeddings: {str(e)}")

# 향상된 프로젝트 채팅에서 파일 컨텍스트 활용
async def generate_gemini_stream_response_with_files(
    messages: list,
    model: str,
    room_id: str,
    db: Session,
    user_id: str,
    project_id: str,
    project_type: Optional[str] = None,
    file_data_list: Optional[List[str]] = None,
    file_types: Optional[List[str]] = None,
    file_names: Optional[List[str]] = None
) -> AsyncGenerator[str, None]:
    """파일 컨텍스트를 활용한 프로젝트 채팅 응답 생성"""
    try:
        client = get_gemini_client()
        if not client:
            raise HTTPException(status_code=500, detail="Gemini client not available")

        # 프로젝트 정보 가져오기
        project = crud_project.get(db=db, id=project_id)
        
        # 프로젝트별 시스템 프롬프트 구성
        system_prompt = BRIEF_SYSTEM_PROMPT
        if project_type == "assignment":
            system_prompt += "\n\n" + ASSIGNMENT_PROMPT
        elif project_type == "record":
            system_prompt += "\n\n" + RECORD_PROMPT
            
        # 프로젝트 사용자 정의 시스템 지시사항 추가
        if project and project.system_instruction and project.system_instruction.strip():
            system_prompt += "\n\n## 추가 지시사항\n" + project.system_instruction.strip()

        # 프로젝트 업로드 파일들을 컨텍스트에 추가
        project_files = []
        try:
            for file in client.files.list():
                if file.display_name and file.display_name.startswith(f"project_{project_id}_"):
                    if file.state.name == "ACTIVE":
                        project_files.append(file)
            
            if project_files:
                system_prompt += f"""
                
                ## 📁 프로젝트 참고 자료
                이 프로젝트에는 다음 파일들이 업로드되어 있습니다:
                {', '.join([f.display_name.replace(f'project_{project_id}_', '') for f in project_files])}
                
                사용자의 질문과 관련이 있다면 이 파일들의 내용을 참고하여 답변해주세요.
                """
        except Exception as e:
            logger.error(f"Failed to load project files: {e}", exc_info=True)

        # 메시지 유효성 검사 및 처리
        valid_messages = []
        for msg in messages[-15:]:  # 최근 15개만 
            if msg.get("content") and msg["content"].strip():
                valid_messages.append(msg)

        if len(valid_messages) == 0:
            raise HTTPException(status_code=400, detail="No valid message content found")

        # 컨텐츠 구성
        contents = []
        
        # 프로젝트 파일들을 컨텍스트에 추가 (최대 3개)
        for file in project_files[:3]:
            contents.append(file)
        
        # 업로드된 파일들 처리
        if file_data_list and file_types and file_names:
            for file_data, file_type, file_name in zip(file_data_list, file_types, file_names):
                if file_type.startswith("image/"):
                    contents.append(
                        types.Part.from_bytes(
                            data=base64.b64decode(file_data),
                            mime_type=file_type
                        )
                    )
                elif file_type == "application/pdf":
                    contents.append(
                        types.Part.from_bytes(
                            data=base64.b64decode(file_data),
                            mime_type=file_type
                        )
                    )

        # 대화 내용 추가
        conversation_text = ""
        for message in valid_messages:
            role_text = "Human" if message["role"] == "user" else "Assistant"
            conversation_text += f"{role_text}: {message['content']}\n"

        contents.append(conversation_text)

        # 도구 설정
        tools = [
            types.Tool(google_search=types.GoogleSearch()),
            types.Tool(code_execution=types.ToolCodeExecution())
        ]

        # 생성 설정
        generation_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.7,
            top_p=0.95,
            max_output_tokens=8192,
            tools=tools,
            thinking_config=types.ThinkingConfig(
                thinking_budget=16384,
                include_thoughts=True
            )
        )

        # 토큰 계산
        input_token_count = count_tokens_with_tiktoken(conversation_text, model)
        input_tokens = input_token_count.get("input_tokens", 0)

        # 스트리밍 응답 생성
        accumulated_content = ""
        accumulated_reasoning = ""
        thought_time = 0.0
        citations = []
        citations_sent = set()
        new_citations = []

        try:
            response = client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=generation_config
            )

            start_time = time.time()
            
            for chunk in response:
                if chunk.candidates and len(chunk.candidates) > 0:
                    candidate = chunk.candidates[0]
                    
                    # 콘텐츠 파트 처리
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, 'thought') and part.thought:
                                accumulated_reasoning += part.text
                                thought_time = time.time() - start_time
                                yield f"data: {json.dumps({'reasoning_content': part.text, 'thought_time': thought_time})}\n\n"
                            elif part.text:
                                accumulated_content += part.text
                                yield f"data: {json.dumps({'content': part.text})}\n\n"

                    # 그라운딩 메타데이터 처리
                    if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                        grounding = candidate.grounding_metadata
                        
                        if hasattr(grounding, 'grounding_chunks') and grounding.grounding_chunks:
                            for chunk_info in grounding.grounding_chunks:
                                if hasattr(chunk_info, 'web') and chunk_info.web:
                                    citation_url = chunk_info.web.uri
                                    if citation_url not in citations_sent:
                                        citation = {
                                            "url": citation_url,
                                            "title": chunk_info.web.title if hasattr(chunk_info.web, 'title') else ""
                                        }
                                        citations.append(citation)
                                        new_citations.append(citation)
                                        citations_sent.add(citation_url)
                            
                            if new_citations:
                                try:
                                    yield f"data: {json.dumps({'citations': new_citations})}\n\n"
                                    new_citations = []  # 전송 후 초기화
                                except (ConnectionError, BrokenPipeError, GeneratorExit):
                                    return

            # 출력 토큰 계산
            output_token_count = count_tokens_with_tiktoken(accumulated_content, model)
            output_tokens = output_token_count.get("input_tokens", 0)
            
            # 사고 토큰 계산
            thinking_tokens = 0
            if accumulated_reasoning:
                thinking_token_count = count_tokens_with_tiktoken(accumulated_reasoning, model)
                thinking_tokens = thinking_token_count.get("input_tokens", 0)

            # 토큰 사용량 저장 (KST 시간으로 저장)
            from pytz import timezone
            kst = timezone('Asia/Seoul')
            crud_stats.create_token_usage(
                db=db,
                user_id=user_id,
                room_id=room_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens + thinking_tokens,
                timestamp=datetime.now(kst),
                chat_type=f"project_{project_type}" if project_type else None
            )

            # AI 응답 메시지 저장
            if accumulated_content:
                message_create = ChatMessageCreate(
                    content=accumulated_content,
                    role="assistant",
                    room_id=room_id,
                    reasoning_content=accumulated_reasoning if accumulated_reasoning else None,
                    thought_time=thought_time if thought_time > 0 else None,
                    citations=citations if citations else None
                )
                crud_project.create_chat_message(db, project_id=project_id, chat_id=room_id, obj_in=message_create)

        except Exception as api_error:
            error_message = f"Gemini API Error: {str(api_error)}"
            yield f"data: {json.dumps({'error': error_message})}\n\n"

    except Exception as e:
        error_message = f"Enhanced Stream Generation Error: {str(e)}"
        yield f"data: {json.dumps({'error': error_message})}\n\n" 