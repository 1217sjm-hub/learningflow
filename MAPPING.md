# JSON / localStorage → SQLite 매핑

브라우저에 흩어진 저장값을 DB 정본으로 옮기기 위한 대응표.

## localStorage 키

| 브라우저 키 | 형태 | DB 테이블 | 비고 |
|-------------|------|-----------|------|
| `lf_course_lib_v1` | `{ folders, courses }` | `course_folders` + `courses` + `weeks` | 폴더·과정·주차 목록 정본 |
| `lf_setup_draft` | draft v3 객체 | `unit_setups` (+ case 초안) | 마지막 활성 차시 |
| `lf_unit_draft_{unitId}` | draft 객체 | `unit_setups` | 주차(unit)별 초안 |
| `lf_course_vars_{hash}` | vars 객체 | `unit_setups.vars_json` | 톤·실행설정 등 |
| `lf_course_rules_{hash}` | 문자열 | `unit_setups.course_prompt` | 과정별 프롬프트 본문 |
| `lf_ai_rules` | 문자열 | `prompt_versions` | 공통 프롬프트 |
| `lf_ai_key` / `lf_ai_model` | 문자열 | **저장 안 함** | 서버 env로만 |
| `lf_active_session` | 세션 | 임시 — Run 작업 중 상태 | DB 정본 아님 |
| IndexedDB `heavy` / `heavy_{unitId}` | paras/scenes | `unit_setups.source_paras_json` + Run/Scene | 용량 큼 |

## 과정 라이브러리 객체 → 테이블

```text
folder.id / name / sort / parentId → course_folders
course.id            → courses.id
course.vendor        → courses.vendor
course.course        → courses.name
course.edu           → courses.edu_type
course.target        → courses.target
course.weekCount     → courses.week_count
course.folderId      → courses.folder_id
course.units[i].id   → weeks.id
course.units[i].week → weeks.week_no
course.units[i].session → weeks.session_no
course.units[i].unit → weeks.label
course.units[i].unit_title → weeks.title
course.units[i].week_title → weeks.week_title
```

## 과정 공통 셋팅 (페이지 구성·톤) → 정규 테이블

```text
sharedSetup.vars / course_rules / manual
  → course_setups (course_id 1:1)
sharedSetup.pageRows[]
  → course_page_rows (course_id 1:N, sort_order)
```

API 응답의 `sharedSetup` 은 위 테이블을 조립한 호환 객체입니다.
레거시 `courses.overrides_json.sharedSetup` 은 기동 시 한 번 이관한 뒤 제거합니다.

## 차시 draft → unit_setups (레거시·로컬 모드)

```text
draft.meta / vars / pageRows / course_rules / manual
  → unit_setups (week_id로 연결)  ※ 서버 연동 시 과정 공통 course_setups 우선
draft.paras → source_paras_json
draft.scenes → (있으면) 별도 Run+Scene 으로 import 권장
```

## .jsonl 내보내기 → Case / Run / Decision|Scene

1행: `{ "__meta": { ... } }`
- `__meta` → `cases.meta_json` (+ title, source_paras)
- `_source_paras` → `cases.source_paras_json`
- `_mode` → `runs.mode` (`tag` | `cmp`)
- `_revisions` → `runs.revisions_json`
- `case_id` → `cases.id` / `runs.case_id`

이후 각 줄:
- tag 모드: decision 행 → `decisions`
- cmp 모드: `ais[]` 있으면 → `scenes`, 행 자체는 `decisions.payload_json`에도 보관

## case_*_decisions.json → Case + Run + Decision

```text
meta.*           → cases.meta_json / title / is_benchmark
source_paras     → cases.source_paras_json (+ source_text join)
decisions[]      → decisions (run 1개에 묶음)
```

이 파일은 **사람 완성본 대조 골드/벤치**에 가깝다. AI Scene 전용이 아님.

## 정본 원칙 (정의서 §4-3)

| 단계 | 정본 |
|------|------|
| 지금 (정리 단계) | import 스크립트로 JSON → DB 적재 검증 |
| 서버 연동 후 | DB |
| 브라우저 | 짧은 임시 초안만 |

## 아직 API로 안 옮긴 것

- `/generate` Claude 호출
- HTML fetch 교체
- 공유 비밀번호 미들웨어

이번 작업 범위는 **스키마 + import 정리**까지.
