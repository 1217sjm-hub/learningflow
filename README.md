# 러닝플로우 서버 (SQLite + FastAPI)

정의서 기준: **과정·주차를 SQLite에 저장**, HTML은 서버로 서빙.

매핑표: [`MAPPING.md`](./MAPPING.md)

## SQLite / SQLAlchemy 설치?

| 구성 | 설치 |
|------|------|
| **SQLite** | **별도 설치 없음.** Python 표준 라이브러리에 포함 |
| **SQLAlchemy / FastAPI** | `pip install -r requirements.txt` (아래 venv) |

DB 파일은 `server/data/learningflow.db` 에 자동 생성됩니다.

## 설치

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

`.env` 의 `APP_PASSWORD` 기본값은 `change-me` 입니다. 테스트 전에 바꾸세요.

## 서버 실행

```powershell
cd server
.\.venv\Scripts\Activate.ps1
python -m scripts.init_db
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

브라우저: **http://127.0.0.1:8000/**  
→ 로그인/회원가입 후 `/app` 으로 진입 (`file://` 로 열면 DB·로그인 안 됨)

- `/register` 계정 생성, `/login` 로그인, `/logout` 로그아웃
- 과정 저장 시 `PUT /api/course-lib` → SQLite (세션 쿠키 인증)
- 상태: http://127.0.0.1:8000/api/stats (로그인 필요)
- 헬스: http://127.0.0.1:8000/health

## 기존 JSON 넣기 (선택)

```powershell
python -m scripts.import_case_decisions ..\files\case_001_decisions_v2.json
python -m scripts.import_course_lib path\to\course_lib.json
python -m scripts.import_jsonl path\to\export.jsonl
```

## 다음 단계

1. `/generate` 로 Claude API 키 서버 이전
2. 차시 draft·Scene도 DB API로
3. Render/Railway + 영구 디스크
