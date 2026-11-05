# Learning AI — AI 기능 모듈 및 내부 FastAPI API

학습 서비스의 AI 기능을 구현한 **Python 프로젝트**입니다. 기본 문서 인식은 **Upstage Document Parse Enhanced + OCR Force**이고, 개념 분석·문제 생성·채점·Teach-back·이해도 평가 기능을 포함합니다. GeminiClient/GroqClient/ModelRouter는 학습용 LLM 연결을 위해 유지하며 **운영 LLM은 미정**입니다.

현재 `src/ai/api.py`에 **로컬 실행·독립 서비스 연동용 FastAPI 내부 API**가 구현되어 있습니다. 다만 **AI 서버를 별도로 배포할지, Python 메인 백엔드에 AI 모듈을 직접 통합할지는 아직 결정하지 않았습니다.** 어느 방식이든 메인 백엔드의 실제 DB·Job 연동은 완료되지 않았습니다.

> 공개 API 명세 `swagger-api-final.yaml`은 **1.3.0-backend-proposal(백엔드 제안안)** 기준이며, 최종 합의된 운영 계약이 아닙니다. 독립적인 AI 개념 설명 기능은 현재 구현 범위에서 제외되어 있으며, YAML에 남은 관련 경로는 계약 정리가 필요합니다.

## 현재 구현·검증 상태

| 항목 | 상태 |
|---|---|
| PDF/TXT/PNG/JPEG 인식 및 문서 캐시 | 구현, Upstage 실제 호출 검증 |
| 개념·체크리스트 초안 분석 | 구현, 다양한 실제 자료에 대한 품질 검증 필요 |
| 확정 개념 기반 문제 생성 | 구현, Groq Strict JSON 실제 성공 |
| 객관식·단순 단답형 채점 | 구현, 통합 실행에서 검증 |
| Teach-back AI 질문 | 구현, **실제 질문 1회 검증** (전체 3회 대화는 미검증) |
| 체크리스트 기반 이해도 평가 | 구현, 실제 호출 및 Python 점수 계산 검증 |
| 하루 권장 공부 시간 계산 | Python 함수 구현, 내부 HTTP 경로·공개 계약 미확정 |
| 메인 백엔드 DB·Job·배포 | 미연동·미완료 |

**2026-11-05 학습 통합 검증:** 확정 개념 및 SourceChunk 일치 → easy 객관식 1개·단답형 1개 생성 → 로컬 채점 → Teach-back 질문 1회 → 이해도 평가를 한 실행에서 확인했습니다. **Groq 실제 호출 3회 모두 HTTP 200, 재시도 0회**, 입력 3,352 + 출력 1,400 = 총 4,752토큰이었습니다. 평가 결과는 explained 1개·omission 1개로 `weighted-v1` 커버리지 **0.5**였으며, 계산 로직은 로컬에서 별도로 검증했습니다. 해당 실행과 관련된 로컬 테스트 53개 및 Ruff 검사도 통과했습니다. 이는 **1개 시나리오의 연결 성공**이지, 모델 답변의 의미적 정확도나 운영 안정성 전체를 보증하지는 않습니다.

통합 실행기는 `src/ai/learning_smoke.py`, 테스트는 `tests/test_learning_flow.py`이며 개인 자료·문제·정답·대화 원문은 보고서에 저장하지 않습니다. 실행 보고서 `reports/learning-integration-live-20261105.json`은 **로컬 전용**이며 Git에 포함되지 않습니다.

## 설치와 실행

Python 3.12를 사용합니다. **기존 작업 폴더**의 `.env`·`.venv`는 그대로 두고, **새로 저장소를 내려받은 환경**에서는 아래 절차로 생성합니다.

```powershell
# 새 환경에서만
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
# .env가 없을 때만 복사
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
```

`.env`의 `AI_SERVER_API_KEY`를 설정한 뒤 서버를 실행합니다. 문서 인식에는 `UPSTAGE_API_KEY`, LLM 호출에는 아래 모델·인증 설정이 추가로 필요합니다.

```powershell
.\.venv\Scripts\python.exe -m ai
```

활성화는 필수가 아닙니다. Linux는 `.venv/bin/python`을 사용합니다. 운영 의존성은 `requirements.txt`, 개발은 `requirements-dev.txt`, 재현 버전은 `requirements.lock.txt`입니다. `.env`에는 각자 발급받은 키를 입력하며 **커밋하지 않습니다.**

- 상태: http://127.0.0.1:8000/health
- 문서: http://127.0.0.1:8000/docs
- 로컬 기본 HOST/PORT는 `127.0.0.1:8000`. 외부 노출 여부와 HOST/PORT는 배포 구조가 확정된 뒤 결정
- `AI_SERVER_API_KEY`가 비어 있으면 시작하지 않음

코드를 수정하면서 테스트할 때는 **VS Code의 프로젝트 터미널에서** 다음 명령을 실행합니다. 파일 변경 시 재시작하고 요청 로그가 해당 터미널에 표시됩니다. 이미 실행 중인 서버가 있으면 먼저 Ctrl+C로 종료하세요.

```powershell
.\.venv\Scripts\python.exe -m uvicorn ai.api:app --reload --reload-dir src --host 127.0.0.1 --port 8000
```

요청이 없을 때 로그가 계속 출력되지 않는 것은 정상입니다. `/docs`를 새로고침하면 `GET /docs ... 200` 같은 접근 로그가 표시됩니다. FastAPI 실행은 **독립 배포 확정**을 의미하지 않습니다.

## 환경변수와 인증

`.env.example`을 참고하고 기존 `.env`에 필요한 항목만 추가합니다.

```dotenv
AI_SERVER_API_KEY=서버인증키
UPSTAGE_API_KEY=Upstage에서_발급받은_키
UPSTAGE_DOCUMENT_MODEL=document-parse
UPSTAGE_TIMEOUT_SECONDS=120
DOCUMENT_CACHE_DIR=.cache/document-parse
```

| 항목 | 역할 |
|---|---|
| `X-AI-API-Key` | 모든 내부 API의 서버 인증 |
| `UPSTAGE_API_KEY` | 서버의 PDF/이미지 인식용 키 |
| `X-AI-Key` | 학습용 LLM 요청의 제공자 BYOK |
| `model_id` | 학습용 LLM 허용목록 키. 문서 인식에는 불필요 |

학습용 LLM은 `AI_MODEL_ALLOWLIST`, `AI_LIVE_ENABLED`를 사용합니다. LLM 호출이 필요한 HTTP 요청에는 명시적인 `model_id`가 필요하며, 이 값이 `AI_MODEL_ROUTES`의 역할별 설정보다 우선합니다. 예시 모델 ID는 `groq:qwen/qwen3.8-27b`입니다. HTTP 학습 요청에서 서버 개발용 키로 대체하지 않습니다. Upstage는 LLM ModelRouter에 추가하지 않았습니다.

문제 생성은 요청별 개수·난이도·허용 유형·정답 구조를 확인하고, 반환된 결과를 기존 Pydantic/최종 계약 검증에 통과시킵니다. `GROQ_STRICT_OUTPUTS`의 **기본 설정은 기존 코드 기준 false**이며, Strict 모드(`json_schema`, `strict=true`)는 별도 실제 요청으로 검증했습니다. 과거 동일 계열 요청에서 HTTP 400 `json_validate_failed`가 발생했지만 **2026-11-05에는 동일한 Strict 스키마를 유지한 문제 생성 호출이 HTTP 200으로 성공**했습니다. 따라서 이전 실패의 정확한 원인을 특정하거나 재발 가능성이 없다고 단정하지 않습니다. [Groq Structured Outputs 문서](https://console.groq.com/docs/structured-outputs)

## 문서 인식

`POST /internal/materials/extract`는 **원본 bytes**를 받습니다(multipart 아님). `/docs`에서 Content-Type 선택 후 파일을 전송합니다. 지원 형식은 **PDF/TXT/PNG/JPEG**, 최대 **20MiB·PDF 200페이지**입니다. WEBP 등 계약 밖 형식은 거부합니다.

```powershell
curl.exe -X POST "http://127.0.0.1:8000/internal/materials/extract?filename=lesson.pdf" -H "X-AI-API-Key: 서버인증키" -H "Content-Type: application/pdf" --data-binary "@lesson.pdf"
```

- PDF/PNG/JPEG: `https://api.upstage.ai/v1/document-digitization`, 설정 모델, `mode=enhanced`, `ocr=force`, JSON 문자열 배열 `output_formats=["markdown","html","text"]`, 좌표 포함
- TXT: UTF-8/UTF-8 BOM, BOM UTF-16, CP949 직접 해독. 원문과 page_number=1 유지. API 호출 없음
- `filename`, 실제 백엔드 `material_id`는 선택 query. AI가 DB ID를 발급하지 않음
- 구버전 `ocr_pdf`/`max_ocr_pages`는 Upstage 동작에 영향 없음. `ocr_pages`는 거부하므로 페이지 선택은 PDF를 나눠 전송

100페이지 초과 PDF는 최대 100페이지씩 동기 분할하고 원본 페이지 번호를 복원합니다. 다중 페이지 표는 합치지 않고 연속 가능성만 표시합니다. 장문 호출은 기존 백엔드 Job/프록시 타임아웃에 맞춰 실행해야 합니다. [공식 요청/응답](https://console.upstage.ai/api/parse/document-parsing), [모델·한도](https://console.upstage.ai/docs/models/document-parse)

`document-parse` 별칭은 갱신될 수 있습니다. `UPSTAGE_DOCUMENT_MODEL=document-parse-260930`처럼 snapshot을 지정할 수 있고 실제 모델은 `recognition.actual_models`에 기록됩니다.

| 응답 필드 | 의미 |
|---|---|
| `document.pages` | 원본 페이지별 Markdown/텍스트. TXT는 원문 그대로 |
| `structured_pages` | 요소 분류·순서·Markdown·HTML·텍스트·좌표·상태 |
| `recognition` | 해시·요청/실제 모델·설정·상태·캐시·요청 수·비용 추정 |
| `review_required_pages`, `warnings` | 누락·시각 정보 등 확인 필요 사항 |
| `ready_for_analysis`, `chunk_drafts` | 원문 텍스트 분석 준비 여부와 ID 없는 청크 초안 |

그림/차트의 모델 설명은 `visual_interpretation=true`로 표시하고 기본 학습 청크에서 제외합니다. 그림 검토 페이지가 있어도 나머지 텍스트를 분석할 수 있습니다. 페이지 누락·깨짐·과대 요소는 청크를 반환하지 않습니다. 표는 HTML 행/열 구조, 수식은 공급자 Markdown/LaTeX를 유지합니다. 공급자 HTML은 렌더러 정책에 맞춰 처리해야 합니다.

## 재사용·비용·오류

파일 해시와 모델/설정/인증 범위별 결과를 `DOCUMENT_CACHE_DIR`에 저장해 재시작 후에도 재사용합니다. 인식 내용은 저장하지만 원본 파일과 키는 저장하지 않습니다. `.cache/`는 Git에서 제외하며 보관 기간·용량·삭제는 배포 시 백엔드 정책과 맞춰야 합니다.

자동 재시도는 없습니다. 이전 문서 인식의 실패·불명 상태가 기록된 동일 요청은 **409 DOCUMENT_PROCESSING_STATE**로 자동 재호출을 제한합니다. 공급자의 처리·과금 여부를 보장하지 않으며, 키 누락 등 외부 호출 전 실패까지 모두 409가 되는 것은 아닙니다. 기존 백엔드 Job이 이전 요청/청구 가능성을 확인한 뒤 `retry_failed=true`로 미완료/검토 필요 부분을 명시적으로 다시 처리할 수 있습니다. 정상 묶음은 재사용합니다. 강제 종료 후 남은 잠금 파일의 해제 및 필드 제안은 [백엔드 연결 메모](docs/backend-integration.md)를 참고하세요.

`estimated_cost_usd`는 문서 전체의 **예상 비용**이며 실제 청구·할인·크레딧·재처리와 다를 수 있습니다. 캐시 적중은 `requests_sent=0`입니다. **실제 단가는 호출 전 [Upstage 공식 가격](https://www.upstage.ai/pricing/api)에서 확인하세요.**

내부 HTTP 오류: 서버 인증 헤더(`X-AI-API-Key`) 누락·불일치 401, 잘못된 입력/제공자 인증 422, 중복·불명 요청 409, 한도 429, 제공자 장애 502/503, 타임아웃 504. LLM 호출이 필요한 요청에서 `X-AI-Key`가 누락되면 422, 문서 인식용 `UPSTAGE_API_KEY`가 미설정이면 503입니다. `AI_SERVER_API_KEY`가 비어 있으면 서버가 시작하지 않습니다. 제공자 원본 오류 본문·키·개인 자료 전문은 로그에 출력하지 않습니다.

## 기존 학습 기능 연결

인식 → 백엔드 청크 저장/ID 배정 → 개념 draft 분석 → 사용자 확인/버전 확정 → 문제·Teach-back·평가 순서입니다. AI가 사용자에게 개념을 설명하는 별도 기능은 현재 범위에서 제외했습니다.

**책임 경계:** 메인 백엔드는 사용자 권한·자료 원본·DB ID·확정 개념 버전·비공개 정답/해설·세션 이력·Job 상태를 관리합니다. AI 코드는 제공받은 확정 컨텍스트와 근거를 처리해 결과를 돌려주며 DB ID를 임의 생성하거나 실제 사용자 DB에 접근하지 않습니다. 실제 운영에서는 ID 소유권과 자료 권한을 백엔드가 검증해야 합니다.

`material.bind_source_chunks(extraction, material_id=..., material_name=..., chunk_ids=[실제 저장 ID])`는 초안을 기존 `SourceChunk`로 연결합니다. HTTP 연동은 같은 ordinal/page/text를 직접 매핑합니다. 기존 StudyContext의 confirmed version/checklist와 SourceEvidence를 사용하며 draft는 후속 기능에서 거부합니다.

| 내부 경로 | 처리 |
|---|---|
| GET /internal/models | LLM 허용목록 |
| POST /internal/models/validate-key | LLM 메타데이터 접근 검사 |
| POST /internal/materials/extract | Upstage 인식 / TXT 직접 읽기 |
| POST /internal/materials/analyze | 단원·개념·체크리스트·근거·난이도/중요도 임시 추정 |
| POST /internal/questions/generate | 공개 `/question-sets` 작업의 기존 내부 처리 함수 |
| POST /internal/questions/grade | 객관식/단답형 평가 |
| POST /internal/teachback/respond | 기존 세 페르소나·최대 3질문·최종 답변 |
| POST /internal/evaluations/generate | 기존 weighted-v1 |
| POST /internal/keywords/suggest | 키워드 최대 5개 |

공개 `/questions/generate`를 다시 만들지 않았습니다. 문제 1~20개, easy/medium/hard, 객관식·단답형, 비공개 정답·해설 구조를 유지합니다. Teach-back 프롬프트/페르소나와 weighted-v1(explained 1, partial 0.5, omission/error 0, unverified 분모 제외)도 유지합니다. 수학 검증은 제한된 산술식만 지원하며 대수·증명이나 문서 인식의 완전성을 보장하지 않습니다.

권장 시간은 `study_time.estimate_context_workload(context, exam_date=..., today=..., progress=선택값)`로 계산합니다. 하루 가능 시간이나 초기 진단은 요구하지 않습니다. 초기 기준은 항목 학습 6분, 문제 3분, Teach-back 5분, 항목 복습 2분입니다. 난이도·취약도를 반영하고 총 시간을 시험 전 남은 날짜로 나눠 올림합니다. 반환하는 assumptions를 함께 표시하세요. `/study-plans`, `/today`, DB·Job·일정 저장은 구현하지 않습니다. 임시 추정 필드의 저장/공개 계약은 [연결 메모](docs/backend-integration.md)에서 협의 항목으로 정리했습니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp=reports/pytest-local
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
```

pytest는 외부 API를 호출하지 않습니다. HTTP 경계는 명시적인 응답 fixture/MockTransport로 검사합니다. 실제 파일 디코딩·청크/인용·산술·weighted-v1·공부 시간·로컬 HTTP 서버·YAML DTO 호환성도 검증합니다. 선택적 로컬 OCR 진단 테스트는 Tesseract 설치 시 실행됩니다. 서버 기본 경로에는 Tesseract가 필요하지 않습니다.

실제 Upstage 테스트는 아래처럼 별도 실행하며 **유료 요청이 발생할 수 있습니다.** 기본 가상 자료만 사용하고 PDF 2페이지+PNG/JPEG 각 1장, 최대 4페이지/3요청이며 첫 오류에서 중단합니다. 캐시가 있으면 재호출하지 않습니다.

```powershell
# fixture가 없을 때만 생성
.\.venv\Scripts\python.exe tests/fixtures/create_parse_pdf.py
.\.venv\Scripts\python.exe -m ai.parse_smoke --live
```

로컬 실행 결과 예시는 `reports/upstage-live.json`에 있으며 이 폴더는 `.gitignore`로 제외됩니다. 응답 모델 `document-parse-260930`으로 PDF/PNG/JPEG와 한글 TXT를 검증했습니다. 한국어·영어·표 행/열·기본 수식·페이지 매핑을 확인했으나, 그래프 설명에 원본에 없는 일요일 해석이 발견돼 시각 정보는 검토 필요입니다. 해당 해석은 학습 청크에서 제외합니다. 모든 문서나 복잡한 수식의 정확도를 검증한 것은 아닙니다.

기존 `ai.groq_smoke`, `ai.smoke`는 명시적인 LLM 개발용 probe로 유지합니다. 해당 제공자의 별도 사용량이 발생하며 Upstage로 자동 전환하지 않습니다. 이전 테스트 결과와 작업 이력은 [docs/progress.md](docs/progress.md)에 있습니다.

문제 생성만 최대 1회 직접 진단하려면 다음 명령을 사용합니다. **유료 요청**이며 자동 재시도하지 않습니다. `--strict`를 빼면 기본 best-effort 모드를 검사합니다. 실패 진단은 오류 위치·유형과 전송 설정 등을 중심으로 기록하며 **실패 출력 원문·정상 문제 본문·공급자 원본 오류 메시지·개인 자료·키는 새 진단 보고서에 저장하지 않습니다.**

아래 `reports/manual-question-request.json`은 **개인이 준비해야 하는 비공개 테스트 입력 경로**입니다. GitHub에 올라간 저장소만으로 자동 제공되는 파일이 아닙니다.

```powershell
.\.venv\Scripts\python.exe -m ai.question_smoke --live --strict --request reports/manual-question-request.json
```

## 백엔드 통합·배포 결정

두 가지 연결 방식 중 팀에서 합의한 방식을 선택합니다.

- **독립 AI 서비스:** 메인 백엔드가 현재 `/internal/*` FastAPI API를 서버 간 인증으로 호출. 별도 AI 실행 환경, 접근 제한, 타임아웃·캐시 정책이 필요합니다.
- **Python 백엔드에 직접 통합:** 메인 백엔드가 `src/ai/`의 비즈니스 로직을 Python 함수로 사용. 별도 AI FastAPI 프로세스는 필수가 아니지만 메인 백엔드 쪽 호출·오류 처리·Job/Worker 연결이 필요합니다. **메인 백엔드가 다른 언어라면 이 방식을 그대로 적용할 수 없습니다.**

현재 **배포 방식, 운영 LLM, 운영 플랫폼은 미확정**이고 실제 배포/Docker 설정은 하지 않았습니다. 메인 백엔드와 확정할 우선 항목은 ID 발급·청크/버전 저장 순서, 정답·해설 비공개 저장, 세션 이력, Job 재시도·타임아웃, 모델 ID·BYOK 키 전달, 인식 메타데이터 보관, 공부 시간 계산의 호출 방법입니다. 상세 내용은 [백엔드 연결 메모](docs/backend-integration.md)를 참고하세요.

## 남은 검증

- 의미 기반 단답형 채점의 실제 LLM 응답 및 판정 정확도
- Teach-back 최대 3회 전체 대화·최종 답변 처리
- 다양한 설명·실제 학습자료에 대한 평가 품질 검토
- 실제 메인 백엔드의 DB ID·Job·인증·상태 전이 연결

**저장소 보안:** `.env`, `.cache/`, `reports/`, 가상환경, 실제 개인 학습자료를 Git에 올리지 않습니다. 실제 API 키는 README·로그·테스트 코드에 포함하지 않습니다.