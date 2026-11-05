# 개발 진행 기록

## 2026-11-05 — 채점·Teach-back·평가 로컬 및 실제 Groq 통합 검증

- 기존 questions.generate/grade, teachback.respond, evaluation.evaluate/calculate_report 및 Pydantic 스키마를 확인하고 재사용. 기존 비즈니스 로직·Upstage·캐시·시간 계산·FastAPI·YAML은 변경하지 않음.
- learning_smoke.py와 test_learning_flow.py 추가. 기존 영어 문법 가상 PDF와 backend_context.json의 확정 개념 1개·기준 2개 사용. SourceChunk 텍스트가 실제 PDF 페이지와 일치하는지 검사. UUID는 미리 배정한 테스트 식별자이며 실제 백엔드 DB 저장·확정을 검증한 것이 아님.
- 외부 호출 없는 실행에서 객관식 정답/오답, 단답형 정확/정규화 일치, 의미 판정에는 모델이 필요하다는 경계 확인. explained/partial/omission/error/unverified의 25가지 기준 조합에서 weighted-v1·평가 불가 분모 제외·분모 0의 null과 ID 연결 확인. 로컬 53개 통과, Ruff 통과. reports/learning-integration-offline-20261105.json은 requests_sent=0, live=false, success=false, offline_passed_live_not_run으로 기록. 실제 AI 응답 성공으로 표시하지 않음.
- 실제 실행기는 최대 3회(문제 생성→Teach-back 첫 질문→평가) 제한과 첫 실패 중단·단계별 HTTP/사용량·미실행 단계 기록을 구현. 생성 문제는 같은 실행 메모리에서 Python 채점으로 전달. 실패/정상 원문·문제·정답·대화·원본 식별자는 보고서/터미널에 기록하지 않음. MockTransport 테스트의 성공/중간 503 중단은 실행기 검증일 뿐 실제 모델 성공이 아님.
- 사용자 최대 3회 승인 후 실제 Groq qwen/qwen3.8-27b strict 호출 3회 실행, 모두 HTTP 200. easy 객관식 1개·단답형 1개 생성→같은 메모리 객체의 객관식 정답/오답 및 단답형 정확/정규화 일치 Python 채점→Teach-back 첫 질문→해당 대화의 체크리스트 평가 통과. 실제 판정 explained 1개/omission 1개, weighted_score=1.0/assessable_count=2/coverage=0.5. 평가 근거/버전/기준 ID와 입력 컨텍스트 불변 검사 통과. 실패 단계/자동 재시도/추가 호출 없음.
- 단계별 사용량: 생성 입력1335/출력768/합계2103, Teach-back 입력992/출력25/합계1017, 평가 입력1025/출력607/합계1632. 총 입력3352/출력1400/합계4752토큰. reports/learning-integration-live-20261105.json에 단계별 상태·HTTP·사용량·체크 결과만 저장. 원문/문제/정답/해설/대화/원본 ID는 저장하지 않음.
- 단답형 의미 채점의 실제 LLM 호출, Teach-back 3회 전체 대화·최종 답변, 상태 5종의 실제 AI 판정 정확도는 이번 최소 실행 범위에 포함하지 않음. 5상태의 계산 검증과 이번 실제 평가에서 관측된 2상태를 구분. 실제 백엔드 DB·HTTP 통합과 다양한 사용자 설명의 판정 품질도 별도 검증 필요.

## 2026-11-05 — 문제 생성 진단 보완 및 승인된 Groq 1회 성공

- 기존 question-generation-verified-20261105.json의 HTTP 400/json_validate_failed를 확인. failed_generation이 저장되지 않아 당시 위반 필드·원인을 소급 확정할 수 없음. Groq 공식 structured-outputs 문서에서 해당 Qwen 모델의 strict 지원을 확인. 기존 전송 스키마는 2개 배열 제약과 단일 정답 객체 형태이며 명백한 프롬프트 모순은 확인되지 않음.
- question_smoke.py만 보완: 실제 전송 스키마·해시·strict/모델 일치·토큰/추론 설정을 확인. 공급자의 failed_generation 및 200 응답 본문은 메모리에서만 JSON/JSON Schema/Pydantic/기존 최종 문제 검증을 수행. 보고서에는 오류 위치·유형 또는 통과 여부만 보존하고 원문·원본 오류 메시지·정상 문제 본문도 저장하지 않음. 임의 추가 키는 <field>로 숨김. 기존 보고서를 변경하거나 원문을 소급 복원하지 않음.
- 사용자 승인 후 기존 확정 테스트 개념으로 정확히 1회 호출. qwen/qwen3.8-27b, json_schema/strict=true, max_completion_tokens=4096, 추론 옵션 미전송. HTTP 200, easy 객관식 1개·단답형 1개, wire/Pydantic/최종 개수·유형·정답·보기·난이도·자료 근거 검증 통과. 2.410초, 입력 2007/출력 933/합계 2940토큰. reports/question-generation-diagnostic-20261105.json. 자동 재시도/추가 호출/자료 재추출 없음.
- 문제 생성 스키마·프롬프트·공개 DTO·YAML은 변경하지 않음. 같은 구조로 성공했으므로 지난 400을 특정 스키마 결함으로 단정하지 않으며 매번 성공한다고 보장하지 않음. 이번 결과의 구조·관계·인용 검증과 정답/해설 의미 전체의 정확성은 구분.
- 대안 검토: A(Strict 유지/전송 단순화)는 현재 성공으로 추가 변경 불필요. B(strict=false)는 검증 보장 감소, C(json_object)는 스키마 준수 보장 없음과 질문 전용 전송 변경 필요, D(유형별 분리)는 최소 2호출과 병합 필요. 자동 fallback은 추가하지 않음.
- 로컬 관련 테스트 65개 및 FastAPI/YAML 계약 테스트 26개, 합계 91개 통과. 기존 Starlette 경고 유지. Ruff check/format 통과. test_question_probe.py에 400 failed_generation 및 200 invalid completion의 원문/비밀/임의 키 비노출·오류 진단·호출 1회 제한·유효 혼합 문제·최종 계약 거부 회귀 검사 추가.
- Upstage/캐시/학습 시간/Teach-back/평가/모델 라우터/일반 Groq 클라이언트는 수정하지 않음. 실제 채점→Teach-back→평가 통합 호출은 미실행. 개인정보를 포함하지 않는 재현 가능한 통합 테스트 컨텍스트와 별도 호출 예산·승인이 필요.

## 2026-11-04 — items 누락 응답과 strict 설정 적용

- 사용자 수동 응답 `items: missing; <field>: extra_forbidden` 확인. 필수 최상위 items 없이 선언되지 않은 키를 반환한 모델 출력이며 정확한 추가 키는 비공개 보호 정책상 해당 오류에서 노출되지 않음.
- 실제 .env 설정을 확인하니 이전 400 회피 조치로 GROQ_STRICT_OUTPUTS=false가 유지돼 best-effort 요청 상태였음. 객체 union 호환성 수정 후에도 이 설정을 적용하지 않은 문제를 확인.
- 키 등 다른 설정을 출력/변경하지 않고 .env의 GROQ_STRICT_OUTPUTS=true만 설정. 생성 프롬프트에 최상위 items 하나 및 item 필수 필드를 명시. 기존 요청 JSON/공개 응답/단일 nullable 정답 전송 구조는 유지.
- strict 전송 스키마→MockTransport 응답→원래 정답 DTO 복원 전체 경로 회귀 테스트 추가. 전체 199개 통과(10.32초), 관련 Ruff 통과. 외부 API 호출 없음. 디스크 strict=true 및 사용자 개발 서버의 reload된 PID 확인. 수정 후 실제 Groq 생성 성공은 여전히 미검증.

## 2026-11-04 — 승인된 추가 1회로 strict 거부 원인 확인 및 전송 스키마 수정

- 사용자가 추가 1회 진단을 승인. question_smoke --live --strict로 정확히 1요청 실행, HTTP 400/invalid_request_error/response_format 확인. 공급자 오류는 `/properties/items/items/anyOf`에서 공통 required key accepted_answers가 다른 variant에도 존재하여 `keyset_required_overlap`로 객체 union을 구분하지 못한다는 내용. reports/question-generation-strict-diagnostic.json. 이 승인의 추가 호출 없음.
- 두 StoredQuestion 객체를 anyOf로 나누던 전송 스키마를 단일 GenerationItem/GenerationAnswer 형태로 통합. 정답 전송 객체는 type/selected_option_ids/text를 사용하고 비사용 필드는 null. 응답 수신 후 불필요한 null 필드를 제거하되 충돌 값은 거부하고 기존 StoredQuestion/정답/근거 검증을 다시 적용. 기존 공개 DTO/백엔드 YAML은 변경하지 않음.
- 요청 개수 minItems/maxItems·난이도·허용 유형 제약 유지. strict 변환 결과에 객체 anyOf가 남지 않고 nullable 원시/배열 분기만 존재함을 로컬 검증. 응답 정답 필드는 기존 객관식(type/selected_option_ids), 단답형(type/text)으로 정확히 복원됨. 잘못된 보기 ID를 허용하지 않음.
- Groq의 schema-only HTTP 400(response_format, invalid JSON schema prefix)은 한정된 상세 사유를 키 마스킹 후 반환하도록 개선. 일반 오류 원본/자료 전문은 노출하지 않음. 기본 strict 설정은 아직 false인 opt-in으로 유지하며 자동 fallback/재시도 없음.
- 로컬 테스트 198개 통과. 수정된 스키마의 실제 Groq 생성 성공은 아직 미검증(승인된 1회는 거부 원인 확인에 사용). 실패 진단을 모델 생성 성공으로 표시하지 않음.

## 2026-11-04 — 문제 개수 제약 및 strict 출력 호환성 진단

- 사용자에게 요청 개수 불일치 오류가 계속 발생. 기존 QuestionBatch의 minItems=1/maxItems=20은 요청 count=2를 강제하지 않았음을 확인.
- 기존 공개 DTO를 유지하고 요청별 전송 스키마에 정확한 minItems/maxItems, 난이도 literal, 유형별 보기/정답 구조를 반영. Python 유형·근거·정답 검증은 유지하며 잘못된 결과를 잘라내거나 채워 성공으로 만들지 않음. 개수 오류에는 요청/실제 개수 표시.
- Groq 공식 문서에서 qwen/qwen3.8-27b의 strict 지원 및 required/closed-object 조건을 확인. 원본 Pydantic 모델을 수정하지 않는 전송용 변환 함수 추가. 선언된 property 이름은 보존하고 선택 기본값/format annotation만 제외, discriminated union을 anyOf로 변환. UUID/도메인 제약은 로컬에서 계속 검사.
- 사용자가 승인한 Groq 최대 1회 직접 테스트 실행: strict=true 요청이 HTTP 400으로 거부됨(0.463초). 실제 문제 생성 성공을 주장하지 않음. 기존 클라이언트가 상세 오류를 보존하지 않아 구체적 거부 조건은 아직 미확인. reports/question-generation-live.json. 추가 호출 중단.
- 다른 기능에 영향을 주지 않도록 GROQ_STRICT_OUTPUTS 기본값을 false로 되돌리고 명시적 opt-in으로 남김. no-fallback/no-retry 유지. 상세 공급자 오류 및 실패 응답을 키 마스킹 후 비공개 보고서로 보존하는 1회 제한 question_smoke.py 추가. CLI 표준 출력에는 내용/키를 출력하지 않음.
- 로컬 테스트 196개 통과(12.86초). 정확한 스키마 개수/required 객체/정답 유형 연결/원본 스키마 불변/속성명 보존/400 상세 수집·키 비노출 검사 포함. 실제 출력 품질 문제는 미해결이며 추가 유료 진단은 사용자 별도 1회 승인 대기.

## 2026-11-04 — VS Code 터미널에서 직접 개발 서버 실행하도록 정리

- 사용자 터미널에 로그가 보이지 않는 원인 확인: 도구가 별도로 실행한 PID 2832의 서버였음. /health 및 /docs는 실제 200으로 정상 실행 중이었지만 로그는 사용자 터미널이 아닌 도구 세션으로 전달됨.
- 해당 프로젝트 실행 경로를 확인하고 도구가 시작한 서버만 종료. 8000번 LISTENING 없음 확인. 사용자 터미널에서 직접 실행할 수 있도록 이후 별도 서버를 다시 띄우지 않음.
- README에 uvicorn --reload --reload-dir src 개발 명령과 요청이 없을 때 로그가 출력되지 않는 정상 동작 안내. 외부 AI 호출/생성 테스트 없음.

## 2026-11-04 — 개발 서버 외부 접속 제한 수정

- 사용자 Groq network request failed 보고 후 확인. 직전 재시작한 PID 20716이 도구의 제한된 네트워크 환경에 있어 WinError 10013으로 외부 HTTPS 연결이 차단됐음. 이는 API 키/문제 생성 JSON 검증 오류가 아니었음.
- 키 없는 Groq models GET으로 제한 밖에서 HTTP 401 응답을 확인(생성 요청 없음). 프로젝트 실행 경로 확인 후 해당 서버만 종료하고 외부 API 접속 가능한 환경에서 재시작(PID 2832).
- 재시작한 FastAPI의 /health 200, /internal/models/validate-key를 통한 실제 Groq 모델 메타데이터 접근 200/valid=true 확인. 키/자료는 로그로 출력하지 않음. 유료 생성 요청 0회. 문제 생성은 사용자 동일 요청으로 별도 확인 필요.

## 2026-11-04 — 이전 오류 문구를 반환하던 개발 서버 재시작

- 사용자 응답이 계속 구버전 `Provider response is not valid JSON for the schema.` 문구여서 실행 상태 확인. 소스에는 해당 문자열이 없고, 현재 Python import는 상세 필드 오류를 반환함을 오프라인 확인.
- 8000번 서버 PID 23044는 15:35 시작, base.py 진단 변경은 15:38로 서버가 수정 전 코드를 유지 중이었음. 프로젝트 Python 실행 경로를 확인한 뒤 해당 프로세스만 종료하고 최신 코드로 재시작(PID 20716).
- /health 정상, /docs 200 확인. 실제 LLM 재호출·추가 과금 없음. 이제 사용자는 서버를 다시 켤 필요 없이 Swagger 새로고침 후 같은 요청을 실행할 수 있음. 이는 진단 코드 적용 확인이며 문제 생성 모델의 응답 품질 해결을 입증한 것은 아님.

## 2026-11-04 — 생성 응답 JSON/스키마 오류의 안전한 상세 진단

- 수동 문제 생성에서 포괄적인 `Provider response is not valid JSON for the schema.` 보고. 이전 응답 원문은 저장되지 않아 실제 JSON 구문 문제인지 필드/타입/도메인 제약 문제인지 확정할 수 없음.
- 공통 validate_json에서 json_invalid와 스키마 검증 실패를 분리. 선언된 필드 경로와 오류 코드 최대 5개만 노출하며 입력 값/원문/validator context/임의 JSON 속성명은 노출하지 않음. 문제의 보기 개수·중복 보기·단답형 보기 비움·정답 유형/보기 연결 제약에 명시적 오류 코드 부여. 검증 기준 완화/가짜 성공/자동 재시도 없음.
- 비공개 입력과 악성 속성명 비노출 및 문제 도메인 오류 상세 경로 회귀 테스트 추가. 전체 192개 통과(6.32초), 관련 Ruff 검사 통과. 실제 모델 재호출은 실행하지 않았으며 현재 변경은 원인 진단 개선이지 해당 모델 응답의 원인 해결을 입증한 것은 아님.

## 2026-11-04 — 문제 생성의 유형 누락 진단

- 사용자 수동 테스트에서 `Generated questions omit a requested question type.` 발생. 입력은 count=2, 객관식/단답형 두 유형이므로 한 유형씩 필요하지만 반환 결과가 한 유형만 포함했다는 검증 오류. 당시 원본 응답은 보관되지 않아 어느 유형인지는 확정 불가.
- questions.py에서 Python으로 문제별 question_type_plan 및 유형별 개수를 계산해 기존 생성 요청에 전달. 기존 Pydantic 정답 구조와 다른 correct_option_id 지시를 실제 selected_option_ids/text 구조로 바로잡음. 유형 누락 검증은 유지하고 오류에 빠진 유형과 반환 유형별 개수 표시. 자동 유료 재시도 없음.
- 정상 혼합 유형/누락 유형·1회 호출 회귀 테스트 추가. 전체 188개 통과(5.93초), 관련 Ruff 검사 통과. 실제 Groq 재호출 및 실제 개선 효과는 미검증. 동일 수동 요청 JSON을 서버 재시작 후 재사용할 수 있음.

## 2026-11-04 — 기획에서 제외한 별도 개념 설명 기능 정리

- 사용자 확인에 따라 AI가 사용자에게 개념을 설명하는 독립 기능을 제거. `/internal/explanations/generate`를 FastAPI/OpenAPI에서 제외하고 404를 확인. 사용자 설명을 받는 Teach-back과 문제의 정답 해설은 유지.
- 사용처 확인 후 `src/ai/explanation.py`, ExplainRequest/LearningExplanationContent 및 해당 모델 역할·전용 Markdown 검증 코드를 정리. 기존 개발 runner/테스트/README/백엔드 연결 메모에서도 해당 활성 기능 제거. 일반 인증·BYOK·오류 매핑 테스트는 Teach-back 경로로 옮겨 유지.
- 기존 수동 JSON 보고서는 사용자 테스트 자료이므로 삭제하지 않음. 이 파일에 포함된 확정 컨텍스트는 문제·Teach-back 테스트에 재사용할 수 있지만 이전 설명 API는 더 이상 제공하지 않음.
- 원본 백엔드 YAML은 임의 변경하지 않았으며 남아 있는 learning-explanations 공개 계약은 별도 정리 협의 대상으로 문서화. 파일 SHA256 유지.
- 로컬 테스트 186개 통과(8.94초), Ruff check/format 통과. 외부 API 호출 없음. 서버 재시작 후 Swagger 목록에서 제거 적용.

## 2026-11-04 — 수동 개념 분석의 빈 결과 진단

- 사용자가 Groq 개념 분석에서 `Analysis is empty or exceeds unit/concept contract limits.` 오류를 보고. 이 메시지는 빈 결과와 합산 개수 초과를 함께 처리하므로 당시 응답 원문 없이 정확한 반환값은 확정 불가.
- 코드 점검에서 초안 분석에도 공통 프롬프트의 immutable confirmed version 지시가 붙는 것을 발견. `make_prompt(source_only=True)`를 추가하여 분석 단계에서만 원본 청크를 사용하도록 분리. 설명·문제·Teach-back·평가의 기존 공통 지시는 기본값으로 유지.
- 분석 프롬프트에 제목/분류/예시·어휘 표/수식 목록도 학습 내용이라는 점과, 해당 구조에서 확인되는 개념만 추출하고 정의/규칙을 보충하지 말라는 지시 추가. 특정 교재의 고정 개념/가짜 결과는 추가하지 않음.
- 빈 결과(units=[])와 실제 단원/개념 개수 초과 오류를 분리. 빈 응답을 성공으로 바꾸거나 자동 유료 재시도하지 않음.
- 로컬 회귀 테스트 193개 통과. 실제 Groq 재호출은 실행하지 않았으며, 프롬프트 수정이 실제 빈 응답을 해결했는지는 미검증. 서버 재시작 후 동일 요청으로 확인 필요.

## 2026-11-04 — Upstage 문서 인식 기본 경로 및 학습 기능 연결

- 기존 코드/호출 경로/계약을 먼저 점검. 백엔드 YAML의 PDF/TXT/PNG/JPEG·20MiB·PDF200페이지 제한을 확인했고 AI 서버의 10MiB 및 WEBP 허용을 수정. 공개 YAML SHA256 `08a205482df8c7013becdf44f052e3228a1da0eb9b7193aa36f8582f848d5221` 유지.
- `document_parse.py` 추가: 고정 HTTPS Upstage REST, model 환경변수, enhanced/force, JSON 문자열 배열 output_formats, HTML/Markdown/text·좌표 정규화. 실제 snapshot·페이지·요소 순서·분류·표 HTML·수식·시각 해석 플래그 보존. 100페이지씩 동기 분할하고 원본 번호 복원. 추정 가격 $0.03/page(2026-11-04 공식 공개 Enhanced 단가, VAT/실제 청구 차이 명시).
- 영속 캐시/요청 중복 방지: 파일 해시+MIME+요청 모델+enhanced/force+출력+정규화 버전+인증 범위. 정상/부분 결과 재사용, 실패/불명 상태 자동 재호출 거부(409). backend retry_failed 명시 시 정상 묶음 재사용 후 미완료 묶음 처리. DB/Job/큐/자동 재시도 없음. 원본/키는 캐시에 저장하지 않고 인식 결과는 `.cache/`에 보관. 프로세스 중단 잠금 해제는 운영 확인 후 수행.
- `material.py` 기본 extract를 PDF/PNG/JPEG Upstage + TXT 직접 해독으로 통합. 기존 로컬 PDF/OCR은 진단용으로만 유지. TXT는 UTF-8/BOM UTF-16/CP949, 원문/청크 부분문자열 보존. 표/수식을 임의로 나누지 않고 페이지별 요소 청크 생성. figure/chart 모델 해석은 표시하고 기본 학습 청크에서 제외. 누락/깨짐/과대 요소는 분석 준비 완료로 표시하지 않음.
- 실제 백엔드 material_id/chunk_ids를 받는 bind_source_chunks 인터페이스 추가. AI의 DB ID 발급 없음. analyze는 페이지를 섞거나 구조 청크를 자르지 않음. draft 난이도/중요도 추정 필드 추가. 기존 confirmed 버전·SourceEvidence·문제 1~20개·페르소나·3질문·weighted-v1 유지. 설명/문제/Teach-back/평가 프롬프트 및 ModelRouter/GeminiClient/GroqClient는 변경하지 않음.
- `study_time.py`에 확정 컨텍스트→학습량 계산 연결. 난이도 배수/중요도 우선순위/Teach-back 시간 추가, 기존 기본값 결과 유지. criteria 6분·문제 3분·Teach-back 5분·복습 2분 초기 추정 기준 명시. 하루 가능 시간/진단 요구 없음. 기존 study-plans/today/DB/일정 API 추가 없음.
- FastAPI extract는 서버 인증 + 서버 UPSTAGE_API_KEY를 사용. LLM 모델/BYOK와 과거 OCR 옵션을 Swagger에서 숨김. 형식과 크기 검증은 외부 호출 전 수행. 초기 키 누락은 외부 요청 0회로 기록했고, 사용자 저장 완료 후 제한 검증 재개.
- 실제 통합: 직접 만든 가상 한국어/영어·표·수식·차트 PDF 2페이지 + 첫 페이지 PNG/JPEG 각 1장. 총 3요청/4페이지, 모델 document-parse-260930, enhanced/force. 한국어·영어·표 셀 관계(영어3/수학2)·x+2=5 및 x=3·페이지 매핑 확인. TXT는 원문 일치 및 외부 호출 없음. 가격 추정 합계 $0.12(VAT 제외), 실제 청구액 미확인. `reports/upstage-live.json`.
- 시각 품질 문제를 숨기지 않음: 차트의 Mon/Tue/Wed 증가를 설명하면서 공급자 해석에 원문에 없는 일요일 집중 주장이 포함됨. chart/figure를 모델 해석으로 분류했고 해당 내용이 학습용 청크에 포함되지 않음을 확인. API/텍스트 테스트 성공과 시각 내용 완전 검증을 구분. 그래프 의미 전체가 정확하다고 보고하지 않음.
- 실제 캐시→FastAPI 검증: 같은 실제 결과를 이용해 200, cache_hit=true, 요청 0회, 텍스트 청크2개, 그래프 검토 페이지[2]. 테스트에서 _request를 강제로 차단했으므로 추가 과금 없음. 비공개 캐시 읽기는 실행 샌드박스 권한 제한으로 정상 사용자 권한에서 확인. `reports/upstage-fastapi.json`.
- 기존 학습 기능과 인식 데이터 연결은 명시적 HTTP/LLM 응답 fixture로 검증. 기존 백엔드 실제 연결이나 실제 학습 LLM의 설명/문제/평가 품질 검증을 완료했다는 뜻은 아님. 기존 Gemini/Groq 개발 runner가 Upstage를 몰래 호출하지 않도록 명시적 vision probe로 유지.
- 추가 파일: document_parse.py, parse_smoke.py, test_document_parse.py, test_recognition_learning.py, fixtures/create_parse_pdf.py 및 document_parse.pdf. 수정: material/api/config/models/study_time/pdf(크기 제한), 기존 smoke runner, 관련 테스트, .env.example/.gitignore/pyproject, README, 기존 backend-integration.md. 새 패키지/DB/Job/Docker/배포 설정 없음. `.env` 키와 가상환경/설치 메타데이터 유지.
- 남은 협의/검증: 인식 결과와 임시 난이도/중요도/시간 필드 저장 계약, 실제 청크·확정 버전 DB 연결, 캐시 보관/잠금 운영 정책, 시각 해석 승인, 실제 대형 문서 및 다양한 자료. 101페이지 분할/부분 실패 재개는 로컬 MockTransport 검증이며 실제 101페이지 유료 호출은 실행하지 않음. README는 실행·테스트 중심, 상세 계약 제안은 기존 docs/backend-integration.md에 통합.
- 최종 검증: pytest **191개 통과(7.39초)**, 기존 Starlette TestClient 경고 1개. Ruff check/format 및 pip check 통과. 테스트용 임시 경로는 reports/ 아래로 지정해 기존 Windows 임시 폴더 권한 문제를 피함.

## 2026-11-04 — 1부 05장 PDF의 422 및 반복 처리 시간 개선

- 사용자 지정 `성문기초영문법자습서1부05장.pdf`(343458 bytes, 9페이지)를 다운로드 폴더에서 확인. 원본 변경/외부 업로드 없음.
- 원인: 기존에는 페이지마다 300dpi OCR을 PSM 3/6 두 번 실행한 뒤, 한 줄이라도 신뢰도가 낮으면 문서 전체를 422로 거부. 첫 페이지 두 레이아웃의 전사 결과가 동일했으며 합계 6.845초 측정.
- `_ocr_page`는 300dpi를 유지하고 회색조와 OMP_THREAD_LIMIT=1 적용. 200dpi도 비교했으나 인식 신뢰도가 떨어져 기본값에 적용하지 않음. 스레드 제한만으로 유의한 속도 향상을 주장하지 않음. 기본 경로는 OCR 대상 페이지당 한 번만 실행하며, 원문이 8줄 미만인 경우 PSM 6, 나머지 PSM 3 사용. 자동 이중 호출 제거.
- PDF HTTP 추출은 품질 미해결이어도 200으로 결과와 경고 반환. `ready_for_analysis=false`, `review_required_pages`, 페이지별 `extraction_quality[].ocr_text`로 검토 상태/후보를 명시. 문서가 검토 대상이면 `chunk_drafts=[]`로 유지해 분석용 데이터로 자동 전달하지 않음. 텍스트층 없는 스캔의 저품질 OCR은 `local_tesseract_review` 미리보기로 반환. 엄격한 독립 `extract_pdf()`의 거부 동작은 유지. 신뢰도 기준을 낮추지 않음.
- FastAPI에서 동일 파일+OCR 옵션의 결과를 최대 2개, 300초 동안 메모리 재사용. 만료/옵션 변경/서버 재시작 시 재처리. 디스크 캐시 없음. 검토 필요 결과도 정상으로 승격하지 않음. 인증 확인 후 캐시 조회.
- 실제 교재 전체를 FastAPI TestClient로 1회 처리: 200, 50.634초, 검토 필요 1~9페이지, 청크 0개, 외부 AI 호출 0회. 최초 문서 전체 OCR은 여전히 시간이 걸리며 즉시 처리로 해결됐다고 주장하지 않음. `reports/chapter05-fastapi.json`.
- 실제 교재 첫 페이지를 같은 FastAPI 인스턴스에서 반복 요청: 최초 5.601초, 캐시 적중 0.012초, 둘 다 200/검토 필요 상태. 전체 9페이지 재요청 시간을 이 수치로 주장하지 않음. `reports/chapter05-cache.json`.
- 전체 로컬 테스트 169개 통과(10.71초), 기존 TestClient deprecation 경고 1개. 캐시 재사용/만료/옵션 분리 및 검토 결과의 청크 차단 테스트 포함. README 변경. 다른 AI 기능/모델 라우터/공개 YAML 미변경.
- 한계: 이 교재의 한국어 인식 정확도는 개선 완료되지 않음. 결과를 직접 검토할 수 있게 했으며 신뢰도 미달 페이지의 개념 분석은 아직 진행하면 안 됨.

## 2026-11-03 — PDF 로컬 OCR 및 품질 검사

- 변경: `pdf.py`에 PyMuPDF 선추출, 깨진 문자/빈 텍스트/과도한 공백/이미지/윤곽 글자 의심 검사와 Tesseract `kor+eng` 선택적 OCR 추가. 한국어가 없다는 이유만으로 영어 PDF를 오류로 취급하지 않음. 완전히 빈 페이지는 OCR하지 않고 번호 유지.
- 페이지당 300dpi, PSM 3/6 각 1회, 프로세스당 60초, 렌더 3천만 픽셀, 기본 5페이지/최대 10페이지 예산. 예산 초과 시 OCR 전 중단. TSV 좌표로 한국어 단어 간격을 복원하고 전체 평균과 긴 줄의 평균 중 최솟값으로 신뢰도 검사.
- 원문/OCR을 합치지 않고 선택. 원문 단어 커버리지, 한국어 증가, 수식 기호 및 식의 숫자/변수 보존, 중복/분절, 신뢰도 검사. 품질 미해결은 422로 청크 생성 전 중단. 휴리스틱이며 모든 누락/잘못된 인식을 검출할 수는 없음. 직접 제공되는 분석 청크의 검토/출처 연결은 백엔드 책임으로 유지.
- `material.py`의 외부 PDF vision OCR 함수를 제거하고 로컬 경로로 통합. `api.py`의 PDF 분기에서는 ModelRouter/제공자 키/외부 API를 사용하지 않음. 기존 이미지 입력 AI OCR, 다른 기능/프롬프트/모델 라우터/공개 YAML은 유지. `ocr_pdf`는 호환용, `ocr_pages`는 추가 검사 대상으로 유지. 다른 페이지의 자동 품질 검사를 해제하는 옵션이 아님.
- Tesseract 5.5.0과 kor/eng 설치 확인. 기본 언어 데이터의 인식 부족을 확인하고 공식 tessdata_best kor/eng를 프로젝트 `.tessdata/`에 다운로드하여 사용. 해당 데이터와 보고서는 gitignore 처리. 새 Python 의존성 없음. README에 새 환경 설치/데이터/비교 명령 기록.
- 테스트 자료 `tests/fixtures/local_ocr.pdf` 및 생성기 추가: 정상 한영/수식 텍스트, 동일 내용 스캔, 영어만 남은 텍스트층+이미지, 단순 한영/수식 스캔 총 4페이지. 글꼴 subset 저장. `tests/check_pdf_extraction.py`는 원문/OCR 후보/선택/페이지/한글 수/품질 상태를 외부 API 없이 보고.
- 실제 정상 추출: 1페이지 원문 167자 완전 보존, OCR 0회. 4페이지 단순 스캔은 한글 `기초 수학`, 영문 `English and Math`, `x + 2 = 5`, `x = 3` 복원, 신뢰도 77.27로 통과. 공백 차이를 제외한 내용은 확인.
- 실제 어려운 한국어 스캔: 2/3페이지에서 한글 54자 복원(원본 59자). 공백 제외 문자 오류율 0.056. `나타냅니다`가 영문처럼 인식되는 오류 등으로 신뢰도 62.24, 정상 완료 처리하지 않고 분석 차단. 낮은 품질을 숨기거나 LLM으로 교정하지 않음. `reports/local-ocr-comparison.json` 참조.
- 사용자 교재 PDF 첫 페이지만 로컬 검증: 일반 추출 한글 0자 → OCR 후보 한글 278자. 신뢰도 52.83으로 거부. 정확한 교재 정답 전사본이 없어 CER/정확도는 산정하지 않음. `reports/local-ocr-textbook-page1.json` 참조. 교재 원본은 변경하지 않았고 외부 업로드/AI 호출 0회.
- 로컬 검증: 전체 pytest 167개 통과, 기존 TestClient deprecation 경고 1개. 샌드박스의 기본 임시 폴더 접근 오류를 피하기 위해 `--basetemp=reports/pytest-local-ocr-final-02 -p no:cacheprovider` 사용. Ruff 및 pip check 통과. 공개 YAML SHA256 기존 `08a205482df8c7013becdf44f052e3228a1da0eb9b7193aa36f8582f848d5221` 유지.
- 남은 한계: 복잡한 교재의 모든 한글/단/표/발음기호/수식 복원은 완료되지 않음. 현재는 로컬 OCR 후보와 미해결 상태를 명확히 제공하고 부정확한 원문을 정상으로 간주하지 않음. 실제 LLM 분석 호출은 이번 요청 범위에서 실행하지 않음.

## 2026-11-03 — Groq 실제 제한 테스트

- 사용자 키 설정 후 실행. 최초 샌드박스 네트워크 실패 후 외부 네트워크에서 실행했으며, 생성 요청은 총 3회로 종료. 추가 생성/재시도 없음.
- 모델 접근 확인 성공. 한국어 연결 응답 `연결 테스트 확인`을 JSON Schema 요청과 기존 Pydantic 검증으로 확인.
- 가상 한국어 문법 PDF의 첫 페이지 이미지만 OCR 호출. 평서문·의문문·부정문 설명 및 영어 예문 전사 성공. OCR 응답도 기존 스키마 검증 통과. 전체 PDF/사용자 자료 미전송.
- 개념 추출 실패: `InvalidResponseError: Analysis is empty or exceeds unit/concept contract limits.` 응답은 JSON/Pydantic 검증 후 analyze의 비어 있음/개수 제한 검사에서 거부됨. 생성량 7토큰으로 빈 분석 가능성이 있으나 원문 응답을 저장하지 않아 정확한 내용은 확정 불가. HTTP 429/502/503이나 타임아웃 오류는 발생하지 않음.
- 사용량 합계 prompt 2472 / completion 108 / total 2580 tokens. 실제 응답/단계/사용량은 `reports/groq-development.json`에 기록. 전체 통합 테스트 성공으로 표시하지 않음.
- 실제 Groq JSON Schema/Pydantic 호환성은 연결·OCR에서 확인, 개념 추출의 유효한 결과는 미확인. 기존 프롬프트/스키마를 유지하며 추가 유료 요청 없이 중단. 운영 모델 미확정.

## 2026-11-03 — GroqCloud 개발용 클라이언트 추가

- 요청 모델 qwen/qwen3.8-27b를 Groq 공식 모델/vision/structured-output/OpenAI 호환 문서에서 확인. Preview 모델의 문서상 이미지·JSON Schema 지원과 계정별 실제 접근 권한은 구분. 운영 모델은 미확정.
- 추가: src/ai/clients/groq.py, src/ai/groq_smoke.py, tests/test_groq.py, tests/fixtures/create_groq_pdf.py 및 groq_korean.pdf. 기존 GeminiClient/FastAPI/AI 기능/프롬프트/도메인 Pydantic 스키마 유지.
- 연결: config.py의 GROQ_API_KEY(SecretStr)/GROQ_MODEL 및 groq provider 추가. 기존 ModelRouter 인터페이스 유지하고 build_router/request_router에 GroqClient 등록. .env의 기존 키·Gemini 허용목록을 보존하고 개발용 groq:qwen/qwen3.8-27b 항목과 빈 GROQ_API_KEY 추가. 기본 운영 모델/자동 대체는 지정하지 않음.
- 전송: 기존 HTTPX로 고정 HTTPS OpenAI 호환 Chat endpoint 사용, 새 SDK/의존성 없음. model/messages/max_completion_tokens/response_format만 전송. JSON Schema best-effort(strict:false)로 기존 선택 필드/스키마를 유지하고 기존 Pydantic strict 검증. API의 strict constrained decoding 보장을 주장하지 않음. logprobs/logit_bias/top_logprobs/messages.name/n/Responses 전용 파라미터 미전송.
- 오류: 429 RateLimitError, 502 ProviderBadGatewayError, 503 ProviderServiceUnavailableError, 네트워크/HTTP 타임아웃 RequestTimeoutError를 구분. 내부 API에서도 별도 상태/코드로 반환. 무과금 키 검증은 GET models 메타데이터 조회만 수행. HTTPX 재시도 0, 리디렉션 거부, 요청 예산 소진 시 호출 전 거부. 키 및 원본 공급자 오류 본문은 로그/응답에 출력하지 않음.
- 테스트 러너: 한국어 생성 1회 → 가상 한영 문법 PDF 첫 페이지 렌더링/OCR 1회 → 해당 전사문 개념 추출 1회(총 최대 3회). 전체 PDF 미전송, 첫 실패/누락 키/제공자 잔여 한도 0에서 중단. 보고서에 단계별 입력/출력/성공 여부/생성 수/사용량/한도 기록. 키·이미지 bytes는 제외.
- 로컬 결과: pytest **162개 통과(9.86초)**. Groq MockTransport의 최소 파라미터/이미지 형식/실제 기존 OCRText·AnalysisPart 스키마 왕복/잘못된 JSON·타입/모델 조회/키 보호·BYOK·예산/429·502·503·타임아웃·무재시도 및 기존 기능 회귀 검사 포함. Ruff check/format 검사 통과, pip check 통과. 기존 Starlette TestClient HTTPX deprecation 경고 1건.
- 실제 결과: GROQ_API_KEY가 .env/환경변수에 없음을 확인. python -m ai.groq_smoke --live는 blocked_missing_key, success=false, requests_sent=0으로 종료. 모델 계정 접근·한국어 생성·한국어 OCR·실제 Groq JSON Schema/개념 추출은 모두 미실행이며 성공을 주장하지 않음. reports/groq-development.json에 이유/미실행 단계를 기록.
- 자료: 직접 만든 2페이지 한국어/영어 문법 PDF의 첫 페이지에 한국어 62글자와 평서문/의문문/부정문이 존재함을 로컬 확인. 두 번째 페이지는 전송하지 않는 테스트 구조. 사용자 자습서나 다른 개인 자료는 외부로 보내지 않음.
- YAML SHA256: 08a205482df8c7013becdf44f052e3228a1da0eb9b7193aa36f8582f848d5221 (작업 전후 동일). 공개 백엔드 YAML 변경 없음. README/.env.example에 Groq 키·모델 ID·UI BYOK·제한 테스트 사용법 추가.
- 남은 작업: 사용자가 로컬 GROQ_API_KEY를 설정하면 기존 승인 범위에서 제한된 실제 테스트를 실행하고 모델 계정 접근/JSON Schema/한국어 OCR/개념 근거 결과를 보고. 외부 오류나 미지원 결과는 자동 우회·반복 호출하지 않음.

## 2026-11-03 — OCR 미실행 결과 표시 수정

- 사용자 응답의 method=pdf_with_vision_ocr 및 모든 페이지 미처리 경고 분석. ocr_pdf=true지만 모든 페이지에 영문 텍스트가 있어 실제 OCR 대상은 0개였음. 원인은 모델 출력이 아니라 미실행에도 OCR method/경고를 붙인 코드 오류.
- material.py: 실제 OCR이 없으면 method=pdf_text와 명시적 미실행 경고 반환. ocr_processed_pages/ocr_model_calls 추가, 실제 처리 집합으로 이미지 누락 경고 구성. OCR 프롬프트에 한국어/영어 원어 보존과 번역·한국어 생략 금지 명시.
- 테스트: 미실행 시 모델 호출 0회·잘못된 OCR 표시 없음, 실제 선택 페이지·이미지 호출 수 검증 추가. pytest 132개 통과(4.57초), Ruff 통과. 기존 TestClient 경고 1건. 외부 모델 호출/사용자 PDF 전송 없음. 서버 재시작 필요.

## 2026-11-03 — 한국어 누락 PDF 진단·페이지 지정 OCR

- 사용자 PDF와 붙여넣은 추출 응답 비교. 원본 첫 페이지를 로컬 렌더링해 한국어가 표시됨을 확인했으나 12페이지 모두 일반 텍스트 추출의 한글 수는 0. 영문 텍스트와 이미지가 함께 있어 기존의 빈 페이지 OCR 조건으로는 누락을 복구할 수 없었음.
- material.py와 api.py에 ocr_pages 선택 추가. ocr_pdf=true와 명시적 페이지 목록으로 텍스트가 있는 페이지도 OCR 가능. 페이지 번호·중복·페이지 예산을 호출 전에 검증하며 비선택 페이지는 기존 텍스트 유지. PDF OCR 렌더링 해상도 개선과 빈 OCR 응답 거부, 이미지가 있는 비OCR 페이지의 누락 가능성 경고 추가.
- tests/test_material_inputs.py/test_api.py에 혼합 PDF·페이지 지정·잘못된 번호·명시 동의·HTTP 쿼리 전달 회귀 검사 추가. README 사용법 업데이트.
- 결과: pytest 131개 통과(3.90초), Ruff 검사 통과. 기존 Starlette TestClient 경고 1건. 사용자 PDF를 외부 모델로 보내거나 실제 OCR을 실행하지 않았으며 실제 한국어 인식 성공은 미검증.
- 사용: 서버 재시작 후 extract에서 ocr_pdf=true, ocr_pages=[1], max_ocr_pages=1로 먼저 첫 페이지를 지정. 실제 실행 시 별도 제공자 키·모델이 필요하며 페이지 이미지가 외부로 전송되고 사용량 발생 가능.

## 2026-11-03 — OpenAPI 1.3.0 반영

- 기준: swagger-api-final.yaml(info.version=1.3.0-backend-proposal)과 첨부 요청 분석. 원본 YAML·기획서·.env·.venv 보존. 코드/로컬 검증 완료와 실제 모델/백엔드 연결 미완료를 구분.
- 구조: 기존 GeminiClient/ModelRouter/LLMClient/PDF/산술 코드 재사용. services.py/prompts.py를 기능별 모듈로 나누고 각 프롬프트를 같은 파일에 배치. planning.py와 일정/추천 경로 제거. 권장 공부 시간만 독립 Python 계산 함수로 제공.
- 신규: material.py, explanation.py, questions.py, teachback.py, evaluation.py, tagging.py, study_time.py, context.py, clients/optional.py; tests/test_contract.py, test_material_inputs.py, test_providers.py, fixtures/backend_context.json; requirements-dev.txt, docs/backend-integration.md.
- 수정: models.py/config.py/router.py/api.py/clients/base.py/clients/gemini.py/grading.py/smoke.py, 기존 유효한 foundation/logic/services/API/server 테스트와 conftest.py, requirements.txt/requirements.lock.txt/pyproject.toml/.env.example/README.md 및 본 기록. test_pdf.py와 fixture 생성기·가상 PDF 유지.
- 삭제: src/ai/services.py, prompts.py, planning.py와 사용하지 않는 이전 데이터 구조. 실제 설치용 .egg-info/PKG-INFO는 유지하고 editable 설치를 0.3.0으로 갱신. 런타임/개발 의존성 분리. OpenAI·Anthropic SDK는 설치하지 않음.
- 자료: PDF/TXT/PNG/JPEG/WEBP, 페이지·청크 초안, backend 제공 청크 ID, 단원/개념/요약/기준/키워드 draft, 장문 분할·호출 예산·배열 상한 구현. 스캔 PDF OCR은 명시적 플래그와 페이지 예산에서만 수행. ID와 버전 확정/DB는 백엔드 담당.
- 설명/문제/채점: 과거 confirmed 버전 허용·draft 거부, UUID v4·관계·근거 ID/자료명/페이지/인용 검증. LearningExplanationContent 및 본문 인용 검증, 공개 Question의 정답 분리, QuestionResult 호환. 불확실한 판정을 false로 위조하지 않고 오류 처리. 제한된 안전 산술 검증 유지.
- 대화/평가: curious_beginner/confused_friend/exam_candidate, ko/en, 이력과 질문 수 일치·최대 3회. final_answer는 추가 AI 호출 없이 반환하고 저장은 백엔드 담당. 평가 프롬프트 분리, 사용자 발언만 판단, 기준별 정확히 1개. weighted-v1: explained1/partial0.5/omission·error0/unverified 제외, coverage=round(score/count,4), 분모 0이면 null. 백엔드 ID 공급 후 SessionReport 투영.
- 키워드/시간: trim+NFKC+lowercase, 최대 5개 제안/중복 제거. 공개 입력 중복 오류·검색 서버는 백엔드 담당. 시간 계산은 기준/문제/복습 추정과 권장 분/일·가정·우선순위 안내이며 일정 생성이 아님. 기존 YAML 수정 없이 추가 필드 제안을 별도 연결 메모에 기록.
- 모델/키: 운영 모델 미확정, 빈 허용목록은 생성 거부. provider-qualified ID·고정 endpoint·역할별 선택·이미지 지원 검증. OpenAI/Anthropic lazy SDK 및 native schema 연결 코드/로컬 요청 형태 검사만 수행. X-AI-API-Key 서버 인증과 X-AI-Key 요청별 BYOK 분리. HTTP 요청은 개발용 환경변수 키로 대체하지 않고 요청 완료 후 클라이언트를 닫음. 키를 본문/응답/로그/보고서에 기록하지 않음. 비생성 메타데이터 검증이 불가능하면 KEY_VALIDATION_UNAVAILABLE. TTL 암호화/Job/retry/restart는 백엔드 영역.
- 최종 로컬 결과: **pytest 124개 통과(5.29초)**, Ruff check 통과, format --check 36개 파일 통과, pip check 통과. 실제 PDF/이미지 디코딩·OCR 예산·인용·산술·weighted-v1·공부 시간·제공자 연결 형태·내부 API/실제 Uvicorn HTTP 검사 포함. SourceEvidence/ConceptVersion/LearningExplanationContent/Question/QuestionResult/SessionReport를 원본 YAML로 직접 검증. 기존 Starlette TestClient HTTPX deprecation 경고 1건 유지.
- 실제 파일: 기존 기획서 PDF 8페이지/9539문자 로컬 추출 성공. 학습용 강의자료라고 가정하거나 외부에 보내지 않음. 가상 영어 문법 PDF와 사전 배정 테스트 ID 스냅샷은 실제 백엔드 DB 확정 자료가 아님.
- 실제 API 승인: 처음에는 이전 호출 보류 지시 때문에 자동 승인 검토가 생성/이미지 전송을 거부. 이후 사용자가 “실제 Gemini 테스트 재개 승인 · 최대 8회”를 명시적으로 선택해 동일한 제한 테스트 재실행.
- 실제 모델 결과: 개발용 Gemini 메타데이터 조회 성공. 실행 중에만 개발용 gemini:gemini-3.8-flash 허용목록 지정(운영/백엔드 허용목록 확정 아님). 모델 조회·PDF 추출 후 첫 이미지 OCR 생성 **1회에서 HTTP 503**으로 중단. 자동 재시도/모델 대체 없음. reports/live-1.3.json에 입력·출력·실패 기록. 후속 분석/설명/문제/대화/평가/키워드 실제 생성은 미실행. 실패 요청 토큰/비용은 알 수 없음. OpenAI/Anthropic 실제 호출 없음.
- 해결: 잘못된 이미지 형식의 PyMuPDF 예외 처리, pytest 캐시/임시 폴더 권한, Windows 파이프 한글 인코딩/명령 길이 제한, weighted-v1 반올림·완료 개념 복습 시간 검사.
- 미완료/협의: 실제 모델 전체 성공·내용 정확성(503 해소 후 검증), 실제 강의자료 평가, backend 내부 요청/허용목록/청크·저장 ID 매핑/Job fencing·결과 불명 처리. DTO 검증을 백엔드 통합 완료로 주장하지 않음.
- 다음: docs/backend-integration.md의 내부 입력·키·ID·권장 시간 필드 합의 후 실제 자료와 선택 모델로 제한된 검증. 외부 배포·Docker·새 음성 서버는 진행하지 않음.

## 2026-11-02 — 필수 기능 구현 및 FastAPI 연결

- 범위: 기존 GeminiClient/ModelRouter 재사용. 최신 기획 A~G의 독립 Python 기능과 FastAPI 연결 구현. 실제 배포·Docker·DB·사용자/구독 관리는 제외.
- 실제 Gemini 호출: 사용자가 “실제 호출은 보류하고 코드·로컬 테스트 진행”을 선택하여 이번 작업에서 0회 실행. 실제 모델의 생성 품질·전체 워크플로 성공은 미검증이다. 이전 연결 검증(모델 조회 성공, 생성 503/504)과 구분한다.
- 구현: PDF 페이지별 추출/장문 분할, 단원/개념/체크리스트/키워드 분석, 인용 페이지·문구 검증, 사용자 확정 StudyContext, 자료/보충 내용 구분 설명, 지정 개수·종류·난이도 문제 생성, 객관식/정확 일치 단답형 Python 채점 및 표현이 다른 단답형 LLM 평가, 제한된 안전 산술 일치 검사, ko/en·학생 유형·대화 기록·최대 3질문 Teach-back, 체크리스트별 이해도 판단과 Python 점수/커버리지, 진도·취약점 기반 D-day 계획/오늘 할 일, 문제 태그/유사도 추천.
- API: /health와 /docs, 기능별 POST 경로 10개. X-AI-API-Key 서버 간 인증, 빈 키 시작 거부, 입력 크기·동시 요청 제한, Pydantic 요청/응답, 공급자/타임아웃/할당량 오류 처리. HOST/PORT 지원. 사업 로직은 services.py에 두고 api.py와 분리.
- 신규 소스: src/ai/models.py, prompts.py, pdf.py, grading.py, planning.py, services.py, api.py, __main__.py.
- 수정: src/ai/config.py, router.py, errors.py, __init__.py, clients/gemini.py, smoke.py, tests/test_foundation.py, requirements.txt, requirements.lock.txt, pyproject.toml, .gitignore, .env.example, .vscode/settings.json, README.md, 본 기록. 포맷 도구가 관련 Python 파일 서식도 정리.
- 신규 테스트/자료: tests/conftest.py, test_pdf.py, test_logic.py, test_services.py, test_api.py, test_server.py, tests/fixtures/create_pdf.py, english_grammar.pdf(공유 가능한 가상 영어 문법 2페이지).
- 삭제: 미사용 clients/mock.py·openai.py·audio.py, 빈 services/adapters 계층의 __init__.py, 연결 예제 전용 schemas/__init__.py와 해당 빈 폴더/잔여 캐시. 이전 docs/integration.md 내용은 README에 통합. OpenAI는 가짜 구현을 두지 않고 LLMClient를 등록할 수 있는 경계 유지.
- 유지: .venv와 실제 사용 중인 src/hackathon_ai.egg-info/PKG-INFO 등은 삭제하지 않고 editable 설치를 0.2.0으로 갱신. .python·의존성·자동 생성 캐시는 .gitignore로 관리하고 VS Code에서 숨김. 원본 swagger-api.yaml과 기획서 PDF 유지.
- 보안 설정: 기존 Gemini 키 유지, 로컬 .env에 별도 서버 인증 키 생성(값 출력 없음). 기존 출력 한도 256은 실제 기능 출력용 4096으로 변경. 실제 호출 허용 여부는 기존 설정 유지; 자동 테스트와 로컬 서버 자식 프로세스는 호출을 차단한다.
- 설치: PyMuPDF 1.28.2, FastAPI 0.162.0, Uvicorn 0.54.0 추가. HTTPX는 기존 SDK 전이 의존성에서 코드가 직접 사용하는 의존성으로 명시. 전체 버전은 requirements.lock.txt에 기록.
- 최종 검증: pytest **94개 통과, 5.06초**, Ruff check 통과, format --check 대상 26개 파일 정렬 확인, pip check 통과. 테스트는 실제 PDF/순수 계산/근거 검증과 테스트 전용 공급자 응답을 이용한 서비스·API 계약 검증을 포함하며 Gemini 성공을 모사한 제품 시연은 없다.
- 실제 로컬 HTTP: Uvicorn을 임시 포트로 실행하여 health/docs, 인증 거부, PDF 추출, 채점, 계획 및 공급자 호출 차단을 검증하고 프로세스 종료. Gemini 호출 0회.
- 해결한 오류: PDF 청크 경계 공백 손실(페이지 텍스트 strip 비활성화), pytest 캐시/임시 폴더 접근 권한, 서로 다른 단원의 동일 개념명 충돌, 중복/누락 평가 항목, 존재하지 않는 인용/사용자 발언, 한 응답에 복수 학생 질문, 출력 토큰 부족·요청 예산 소진 처리.
- 알려진 경고: 현재 Starlette TestClient는 HTTPX 사용 deprecation 경고 1건 출력. 실행 실패가 아니며 제거 목적으로 HTTP 클라이언트 패키지를 추가하지 않음.
- 제한: OCR/음성 제외. 수학은 계산식과 정답의 산술 일치만 검증하며 문제 해석·대수·증명은 미지원. 인용의 실제 존재와 별개로 의미 타당성은 실제 모델 품질 검증이 필요. OpenAI 실제 제공자 구현은 향후 교체 시 추가.
- 실제 호출 재개 시: AI Studio Free tier/잔여 한도 확인 후 python -m ai.smoke --live --confirm-free-tier --max-calls 8 실행. 단계별 입력/출력/성공/요청수/토큰 사용량을 reports/live.json에 기록하고 첫 실패에 중단. 이번에는 이 보고서를 성공한 것처럼 생성하지 않음.
- 배포 전: 실제 Gemini 워크플로 검증, 메인 백엔드 확정 개념·대화 저장 및 서버 인증 연동, HTTPS/접근 제한·운영 로그·공유 요청 제한·비용 관측. swagger의 daily_minutes 계약 충돌은 메인 백엔드에서 합의 필요.


## 2026-11-02 (Asia/Seoul)

- 실제 연결 테스트: gemini-3.8-flash 모델 메타데이터 조회 성공. 키 값은 출력하지 않음.
- 발견 및 수정: response_schema에 전달한 Pydantic의 additionalProperties가 additional_properties로 변환되어 HTTP 400 발생. response_json_schema=schema.model_json_schema()로 변경하고 회귀 검증 수정.
- 변경 파일: src/ai/clients/gemini.py, tests/test_foundation.py, docs/progress.md.
- 검증: pytest 29개 통과, Ruff check 및 format --check 통과.
- 실제 생성 결과: 수정 후 HTTP 503, 최종 재확인에서 HTTP 504 반환. 짧은 JSON 생성 성공은 아직 확인하지 못함. 이전 실행 1회는 세션 종료로 결과 회수 불가.
- 남은 문제: 모델 조회 성공만으로 실제 생성 가능 여부를 확정할 수 없음. 공급자 오류가 해소된 뒤 동일 명령으로 재확인 필요. 모델이나 결제 설정은 변경하지 않음.
- 다음 작업: 서비스 상태가 회복되면 python -m ai.smoke --live 재확인. 이후 텍스트 PDF 분석 구현.

## 2026-11-01 (Asia/Seoul)

- 범위: 첫 단계 Python 개발 기반. AI 서비스 상세 구현은 제외.
- 환경: Windows PowerShell, 기존 3.14/3.10 확인. 프로젝트 내부 .python에 CPython 3.12.13 설치. 시스템 PATH·레지스트리 변경 없음.
- 구현: LLMClient, GeminiClient, MockClient, OpenAIClient 확장 지점, 7개 역할 ModelRouter, 환경변수 설정, Pydantic JSON 검증, 타임아웃·할당량·접근 오류 처리, 음성 Protocol, 기본 Mock/명시적 실제 연결 CLI.
- 생성 파일: 루트 설정(.gitignore, .python-version, .env.example, pyproject.toml, requirements.txt, requirements.lock.txt), .vscode/settings.json, src/ai 하위 패키지·클라이언트·설정·라우터·스키마·CLI, tests/test_foundation.py, README.md, docs/integration.md, 본 문서. .venv/.python/.uv-cache는 Git 제외.
- 해결: PowerShell 프로필 실행 정책 오류를 피하기 위해 프로필 없이 실행하고 가상환경 Python을 직접 사용. uv 미지원 --no-modify-path를 제거하고 --no-bin/--no-registry 사용.
- 모델: 공식 문서에서 gemini-3.8-flash와 Standard Free tier 제공 확인. 계정별 권한·한도는 미확인.
- 테스트 결과: pytest 29개 통과(0.92초), Ruff check 통과, Ruff format --check 18개 파일 통과, Mock CLI 성공, pip check 통과. --live는 기본 비활성 설정에서 ConfigurationError로 차단됨을 확인(실제 API 요청 없음).
- 설치 버전: google-genai 2.34.0, pydantic 2.14.2, python-dotenv 1.2.4, pytest 9.2.0, ruff 0.17.3. 전체 전이 의존성은 requirements.lock.txt에 고정.
- 추가 해결: 한글 문서 저장 인코딩을 UTF-8로 수정. Ruff에서 .python/.uv-cache/.venv 제외 설정 추가. 키가 비어 있는 .env 생성, 실제 호출 기본 차단.
- 남은 문제: API 키 미설정으로 실제 접근·생성 검증 보류. OpenAI 실제 구현과 PDF/도메인 기능은 다음 단계. Swagger daily_minutes 필수 조건은 최신 기획과 충돌하며 계약 합의 필요.
- 다음 작업: 텍스트 PDF 분석과 근거 페이지 검증, 구조화된 사용자 검토용 결과.

### 생성 파일 전체 목록 (개발 도구 설치 파일·캐시 제외)

- `.env`
- `.env.example`
- `.gitignore`
- `.python-version`
- `.vscode/settings.json`
- `README.md`
- `docs/integration.md`
- `docs/progress.md`
- `pyproject.toml`
- `requirements.lock.txt`
- `requirements.txt`
- `src/ai/__init__.py`
- `src/ai/adapters/__init__.py`
- `src/ai/clients/__init__.py`
- `src/ai/clients/audio.py`
- `src/ai/clients/base.py`
- `src/ai/clients/gemini.py`
- `src/ai/clients/mock.py`
- `src/ai/clients/openai.py`
- `src/ai/config.py`
- `src/ai/errors.py`
- `src/ai/router.py`
- `src/ai/schemas/__init__.py`
- `src/ai/services/__init__.py`
- `src/ai/smoke.py`
- `tests/test_foundation.py`


## 2026-11-03 - Local validate-key configuration fix

- Empty AI_MODEL_ALLOWLIST caused MODEL_NOT_ALLOWED (422).
- Added gemini:gemini-3.8-flash to the local development allowlist; existing secrets preserved.
- Verified Settings.target_for locally. No provider call. Server restart required.
- This does not select a production model or confirm a backend deployment catalog.
