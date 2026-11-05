# 백엔드 연결 메모 — 1.3.0

기준은 swagger-api-final.yaml(info.version=1.3.0-backend-proposal)입니다. 원문은 수정하지 않았습니다. 아래 내부 처리 계약은 AI 파트 제안이며 실제 백엔드 연결 완료를 뜻하지 않습니다.

## 공개 계약과 처리 경계

| 공개 백엔드 작업 | AI 처리 | 백엔드 책임 |
|---|---|---|
| materials complete/units/concepts | 추출·분석 → draft | 보관·청크/단원/개념/버전/기준 ID·원자 저장/확정 |
| learning-explanations | 현 기획에서 제외, AI 처리 없음 | 원본 YAML에 남은 공개 계약은 별도 정리 협의 |
| question-sets | questions.generate | unit 관계, set/question ID·ordinal, 비공개 정답 저장 |
| question attempts | questions.grade | 제출 권한·Job·이력/집계 |
| teachback messages/final-answer | teachback.respond | 세션·이력·질문 수·성공 원자 저장 |
| complete/report | evaluation.evaluate | report/action/item ID·저장·weakness 집계 |
| publications | tagging.suggest | 최종 키워드 검사·공개 동의·스냅샷·검색 |
| study-plans/today | 없음 | 일정·D-day·진도·오늘 할 일·재조정 |

추출 결과 chunk_drafts에는 ordinal/page_number/text만 있습니다. 백엔드가 ID를 배정하고 SourceChunk(id, material_id, material_name, page_number, text)를 분석에 전달해야 합니다. 단원/개념/체크리스트는 draft로 반환하며 모든 DB ID는 백엔드가 배정합니다. 청크 ID 배정·저장·Job fencing 시점은 협의가 필요합니다.

후속 StudyContext는 ConfirmedConcept(concept_id, unit_id, material_id, version)과 chunks입니다. version은 YAML ConceptVersion의 전체 스냅샷입니다. 과거 confirmed 버전(is_current=false)도 허용하고 draft는 거부합니다. AI는 UUID v4·관계·중복·기준 순서·근거 ID/메타데이터/인용을 검사하지만 DB 소유권·ready 상태는 확인할 수 없습니다. 백엔드가 검증한 입력만 서버 간 인증으로 보내야 합니다.

## DTO 호환

- StoredQuestion: question + 비공개 correct_answer/explanation/accepted_answers/arithmetic_expression. question에는 정답이 없습니다. 백엔드 ID 공급 후 public_question()으로 공개 Question을 만듭니다.
- QuestionResult: is_correct/feedback/correct_answer/explanation/evidence. 판정 불가는 false로 위조하지 않고 INVALID_OUTPUT으로 실패합니다. 객관식·정규화 답안 일치는 모델을 호출하지 않습니다.
- 평가: 저장 전 본문을 반환합니다. 백엔드가 report_id/session_id/action_id/criterion별 report_item_id/version_no를 주면 session_report()로 공개 SessionReport를 만듭니다. weighted-v1은 Python 재계산, 모든 기준 결과 정확히 1개입니다.
- 키워드 제안: trim+NFKC+lowercase 후 중복 제거해 최대 5개. 사용자 publication 입력의 중복을 제거해 성공시키는 정책이 아닙니다. 공개 DUPLICATE_KEYWORD 검사는 백엔드가 유지합니다.
- Teach-back: 일반 질문 최대 3회. final_answer=true는 질문 수=3과 교대 이력을 검증하고 추가 AI 호출 없이 마지막 사용자 내용을 반환합니다. complete 생략 허용·상태 전이·영구 저장은 백엔드 담당입니다.

tests/test_contract.py는 SourceEvidence/ConceptVersion/Question/QuestionResult/SessionReport를 실제 YAML로 검증합니다. AI가 공개 202/Accepted/Job를 복제하지는 않습니다.

## 모델·BYOK

운영 모델과 실제 백엔드 허용목록은 제공되지 않았습니다. AI_MODEL_ALLOWLIST를 백엔드 /ai/models의 같은 ID·활성 상태에 맞춰야 합니다. provider-qualified 접두사를 검증하고 제공자 실제 모델명은 model 값입니다. 예제의 gemini: 명명은 개발 예시이며 실제 백엔드의 규칙을 확정한 것이 아닙니다.

X-AI-API-Key는 서버 인증, X-AI-Key는 요청별 BYOK입니다. BYOK는 본문/멱등 데이터/응답/전역 사용자 캐시에 넣지 않습니다. HTTPS 종료·신뢰 프록시는 배포 책임입니다. AES-GCM·15분 TTL·키 재입력·Job retry/restart는 백엔드 시스템을 사용해야 합니다.

키 검증은 메타데이터 조회만 수행합니다. 안전한 검증이 불가능하면 KEY_VALIDATION_UNAVAILABLE이고 생성을 몰래 호출하지 않습니다. 무료 잔여 한도는 확인하지 못합니다. 생성 타임아웃은 최대 60초, 자동 재시도 없음. 호출 이후 결과 불명·fencing·저장은 백엔드 Job에서 판단해야 합니다.

## 별도 제안: 하루 권장 공부 시간

현재 YAML에는 없는 기능입니다. 기존 계획/오늘 응답을 수정하지 않았고 내부 HTTP 경로도 추가하지 않았습니다. 우선 study_time.estimate_study_time(StudyTimeRequest)로만 제공합니다.

추가할 요청 필드 제안:
- exam_date, today(Asia/Seoul 날짜)
- concepts[]: concept_version_id, name, remaining_criteria(0~50), remaining_questions, review_cycles
- review_criteria: 선택, 기본 남은 기준 수. 이미 학습했지만 복습할 기준 수를 별도 전달 가능
- weakness: 기존 진도/오답에서 얻는 0~1 값. 시간 입력·초기 진단은 추가하지 않음

응답 제안:
- estimate=true, remaining_days, total_minutes, recommended_daily_minutes
- concepts[]: 버전 ID, learning/question/review/total_minutes, priority
- assumptions[], priority_guidance

초기 계산: 남은 기준×6분, 문제×3분, 복습 기준×횟수×2분. 학습/복습에는 (1+0.5×weakness)를 곱합니다. 시험 전 남은 일수(최소 1)로 나눈 올림을 권장 분으로 반환합니다. 180분/일 초과는 범위·우선순위 조정 안내입니다. 오늘/지난 시험도 오늘 기준 추정량을 반환합니다. 학습 능력 진단이나 완료 보장이 아니며 실제 측정으로 보정할 계수입니다.

협의: 응답 필드 추가 또는 별도 엔드포인트 여부, 문제/복습 수의 입력 근거, 추정 계수, 과부하 표시 기준. 승인 전 기존 YAML에는 넣지 않습니다.

## 음성과 미확정 사항

현재 음성 계약은 browser STT → 사용자 확인 텍스트이며 원음 미저장입니다. 서버 STT/TTS는 구현하지 않았습니다. 향후 변경은 별도 계약·제공자·비용·동의 범위가 필요합니다.

실제 내부 요청, 청크 배정/저장, model_id 허용목록, TLS/키 전달, Job 결과 불명 처리, 실제 강의자료 평가가 미확정입니다. 로컬 기능 검증과 백엔드 연결 완료는 별개입니다.


## Upstage Document Parse integration (2026-11-04)


`swagger-api-final.yaml` 1.3.0 원본은 수정하지 않았습니다. 업로드 제한은 PDF/TXT/PNG/JPEG, 20MiB, PDF 200페이지입니다. 공개 `/question-sets`, `/study-plans`, `/today`, Job/저장/사용자 인증은 메인 백엔드가 계속 관리합니다.

## 문서 인식 결과 저장

- 기존 내부 `/internal/materials/extract`에 원본 bytes와 Content-Type을 전송합니다. 선택적으로 `filename`, 실제 백엔드 `material_id`를 query로 전달합니다. Upstage 키는 서버 환경변수이며 사용자 LLM BYOK와 다릅니다.
- `document.pages`와 `structured_pages`를 자료의 인식 버전별로 저장합니다. 후자는 요소 순서·분류·Markdown·HTML·원문 텍스트·좌표를 보존합니다. 표는 HTML의 행/열 관계를 유지하고, 수식은 공급자 Markdown/LaTeX를 그대로 보존합니다.
- `recognition`의 source_sha256, requested_model, actual_models, mode, ocr, status, 가격 기준과 인식 설정을 저장하는 필드 협의가 필요합니다. `estimated_cost_usd`는 문서 전체의 공개 단가 기준 추정치이며 캐시 요청의 실제 과금액이 아닙니다.
- `ready_for_analysis`는 **시각 해석을 제외한 텍스트 근거**를 분석에 전달할 수 있는지 뜻합니다. `review_required_pages`가 있어도 안전한 텍스트 청크는 제공될 수 있습니다. `visual_interpretation=true`인 figure/chart 설명은 기본 청크에 넣지 않습니다. 원본 그림은 material/page/coordinates로 찾아 검토하며, 그림을 학습 근거로 승인하는 절차는 별도 협의가 필요합니다.
- `partial` 또는 비어 있는/깨진/과대 요소가 있으면 분석용 청크를 반환하지 않습니다. 인식 일부 누락을 완료로 저장하지 마세요. 인식 성공도 원문과의 완전 일치를 보장하지 않습니다.

## 실제 청크 ID와 확정 버전

1. 백엔드가 `chunk_drafts`를 순서대로 저장하고 실제 chunk UUID를 발급합니다. AI는 material/chunk/concept/version ID를 발급하지 않습니다.
2. Python 연동은 `material.bind_source_chunks(extraction, material_id=..., material_name=..., chunk_ids=[실제 저장 ID])`를 사용할 수 있습니다. HTTP 연동은 동일한 ordinal/page/text를 기존 `SourceChunk`에 투영합니다. `SourceEvidence` 구조는 그대로입니다.
3. 기존 `/internal/materials/analyze`로 저장된 `SourceChunk`를 보내 draft 단원/개념을 생성합니다. 페이지 사이의 표/개념을 임의로 합치지 않고, 같은 단원의 개념을 분석 결과에서 근거와 함께 통합합니다.
4. 사용자 확인 후 백엔드가 immutable confirmed version/checklist를 저장합니다. 기존 `StudyContext`로 문제 세트·Teach-back·weighted-v1 평가를 실행합니다. 미확정 개념은 거부합니다.

DraftConcept의 `estimated_difficulty`(easy/medium/hard 또는 null), `estimated_importance`(0~1 또는 null)는 **내부 임시 추정 필드**입니다. 공개 ConceptVersion에 이 값을 저장/노출할지는 계약 변경 제안이며 이번에 YAML에 추가하지 않았습니다.

## 중복 인식과 기존 Job 정책

동일 파일 해시+MIME+요청 모델+enhanced/force+출력 형식+정규화 버전+인증 범위로 캐시를 구분합니다. 서버 재시작 후에도 `DOCUMENT_CACHE_DIR`에서 성공/검토 필요 결과를 재사용합니다. 원본 파일은 저장하지 않고 인식 결과만 저장합니다. 캐시 보관·삭제 정책과 디스크 용량은 배포 시 백엔드 정책과 합의해야 합니다.

네트워크 오류/타임아웃/실패 이후 같은 요청은 자동 재호출하지 않으며 409 `DOCUMENT_PROCESSING_STATE`로 막습니다. 기존 Job이 이전 청구/처리 상태를 확인한 뒤 `retry_failed=true`를 명시해야 미완료 또는 검토 필요 부분을 다시 처리합니다. 이미 정상 처리된 100페이지 묶음은 재사용합니다. 프로세스 강제 종료로 `request.lock`이 남으면 실행 중 요청이 없음을 확인한 뒤 해당 캐시 폴더의 잠금 파일만 운영자가 해제해야 합니다. 무조건 삭제/재시도하지 마세요.

100페이지 초과 PDF는 최대 100페이지씩 동기 분할합니다. 101페이지의 첫 묶음은 원본 1~100, 두 번째는 원본 101로 복원합니다. 경계의 표는 합치지 않고 연속 가능성만 표시합니다. PDF 전체 원본 페이지 연결은 유지하지만 100/101페이지에 걸친 복잡한 표의 완전 자동 통합은 검증하지 않았습니다. 장문 처리는 기존 백엔드 Job 및 프록시 타임아웃에 맞춰 호출해야 하며 AI 서버에 Job API를 추가하지 않았습니다.

## 하루 권장 공부 시간

`study_time.estimate_context_workload(context, exam_date=..., today=..., progress=선택값)`은 확정 버전 체크리스트를 기존 계산 함수에 연결합니다. progress는 기존 `TimeConcept` 목록이며 실제 남은 항목·문제 수·복습·취약도와 선택적 difficulty/importance/teachback_sessions를 전달합니다. 일일 공부 가능 시간이나 초기 진단은 필요하지 않습니다.

초기 기준은 항목 학습 6분, 문제 3분, Teach-back 회차 5분, 항목별 복습 2분입니다. 난이도 배수 easy 0.75/medium 1/hard 1.5, 취약도 배수는 학습/복습에 `1+0.5*weakness`를 적용합니다. 중요도는 우선순위에 사용합니다. 입력이 없으면 모든 확정 항목 미학습·개념당 문제 2개/Teach-back 1회/복습 1회로 추정합니다. 단원 저장이나 날짜별 작업 생성은 하지 않습니다.

기존 StudyTimeEstimate에 teachback_minutes, difficulty/importance 및 추정 근거를 백엔드가 어떻게 저장/노출할지 합의가 필요합니다. 하루 권장 시간은 총 남은 분량을 시험 전 남은 날짜로 나눈 올림값입니다. 시험 당일/지난 시험은 분모 1로 처리하고 별도 안내를 반환합니다. 이는 초기 추정이며 학습 완료 약속이나 실력 진단이 아닙니다.
