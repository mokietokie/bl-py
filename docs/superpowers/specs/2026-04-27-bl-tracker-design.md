# BL Tracker — Design Spec

- Date: 2026-04-27
- Status: Approved (brainstorming complete)
- Owner: jungmocha@gmail.com

## 1. 배경 / 문제

컨테이너 화물 담당자가 매일 15-20개의 BL/IMO를 수기 조회하고 엑셀로 관리한다.

- **BL 조회**: `https://www.track-trace.com/bol` 검색 폼에 BL 입력 → 최종 Port(Busan/Incheon) ETA 확인.
- **선박 위치**: `https://www.vesselfinder.com` 검색 폼에 IMO 입력 → 위/경도 + 인근 해역 확인.
- **엑셀 양식**: `BL번호 | IMO번호 | ETA | 화물위치` 헤더로 수기 갱신.
- **핵심 페인 포인트**: 어제 대비 ETA 변경 여부와 현재 위치를 매일 일일이 손으로 비교/입력.

## 2. 목표 / 비목표

### 목표
- 위 엑셀 양식을 그대로 옮긴 로컬 웹 앱.
- 행별 BL 새로고침 / 위치 새로고침 버튼.
- 선택 행 / 전체 행 일괄 새로고침 (3개 병렬).
- KST 일자 기준 어제 마지막 ETA와 비교해 변경 행 강조.
- 엑셀 업로드(import) / 내보내기(export).
- 단일 사용자 로컬 PC(Windows)에서 `.exe` 더블클릭 실행.
- 데이터는 사용자 로컬 SQLite에 저장.

### 비목표
- 멀티 유저 / 클라우드 배포.
- 자동 스케줄 갱신 (매일 자동 실행 등). 모든 갱신은 사용자 트리거.
- 엑셀 파일 워치 자동 동기화. 교환은 명시적 import/export 버튼만.
- ETA 전체 이력 시각화 / 그래프. 비교는 "어제 vs 오늘" 1-홉만.
- 선박 실시간 추적 / 푸시 알림.

## 3. 사용자 흐름

1. 사용자가 `bl-tracker.exe` 실행 → 로컬 FastAPI 서버 기동 + 기본 브라우저로 `http://localhost:7777` 자동 오픈.
2. 테이블에 기존 데이터 표시. "엑셀 업로드"로 초기 데이터 import.
3. 행 추가/편집/삭제는 앱 내에서 수기 가능.
4. 갱신 동작:
   - 행의 **BL 새로고침** 버튼 → 그 BL만 ETA 갱신.
   - 행의 **위치 새로고침** 버튼 → 그 IMO만 위치 갱신.
   - 체크박스 다중 선택 → **선택 새로고침** (BL+위치 동시, 3개 병렬).
   - **전체 새로고침** (BL+위치 동시, 3개 병렬, 진행률 표시).
5. ETA가 KST 어제 마지막 값과 다르면 행을 빨강 강조 + "이전 ETA → 새 ETA" 표시.
6. 필요시 **엑셀 내보내기**로 현재 테이블 `.xlsx` 다운로드.

## 4. 아키텍처

```
┌─ bl-tracker.exe (PyInstaller bundle) ─────────────────┐
│                                                       │
│  ┌──────────┐   HTTP (localhost:7777)   ┌──────────┐  │
│  │ 사용자    │ ◄──────────────────────► │ FastAPI  │  │
│  │ 브라우저  │                          │  서버    │  │
│  └──────────┘                           └────┬─────┘  │
│                                              │        │
│                          ┌───────────────────┼───────┐│
│                          ▼                   ▼       ▼│
│                       ┌─────┐   ┌─────────────────┐ ┌──────┐
│                       │ db/ │   │   crawler/      │ │ web/ │
│                       │SQLite│  │  (Playwright)   │ │ HTML │
│                       └─────┘   └─────────────────┘ └──────┘
└──────────────────────────────────────────────────────┘
```

### 컴포넌트

#### `crawler/` — 크롤링 모듈 (독립 실행 가능)
- `track_trace.py`
  - `fetch_eta(bl_no: str) -> EtaResult`
  - CLI: `python -m crawler.track_trace <BL_NO>` → JSON stdout.
- `vesselfinder.py`
  - `fetch_location(imo: str) -> LocationResult`
  - CLI: `python -m crawler.vesselfinder <IMO>` → JSON stdout.
- 공통:
  - Playwright Chromium headless + `playwright-stealth`.
  - 타임아웃, 1-2초 jitter, 재시도 1회.
  - 결과 타입: `{status: "ok"|"failed", data?, reason?, fetched_at}`.
- **이게 사용자가 요청한 "CLI에서 단독 실행 가능" 요건을 충족.** 본 앱 통합 전에 각 크롤러를 CLI에서 단독 검증한다.

#### `api/` — FastAPI 서버
- `GET /shipments` — 전체 목록.
- `POST /shipments` — 행 추가.
- `PUT /shipments/{id}` — 편집.
- `DELETE /shipments/{id}` — 삭제.
- `POST /shipments/{id}/refresh-bl` — 단건 BL 갱신.
- `POST /shipments/{id}/refresh-loc` — 단건 위치 갱신.
- `POST /shipments/refresh-bulk` body: `{ids: [...], targets: ["bl","loc"]}` — 3개 동시성 풀로 처리, SSE로 진행률 스트림.
- `POST /import/excel` (multipart) — UPSERT(bl_no 기준).
- `GET /export/excel` — `.xlsx` 다운로드.

#### `web/` — 프론트엔드
- 단일 `index.html` + 바닐라 JS (또는 HTMX). 빌드 도구 없음.
- 테이블 + 행별 버튼 + 체크박스 + 상단 액션 바(전체 새로고침 / 선택 새로고침 / 업로드 / 내보내기) + 진행률 영역(SSE).
- ETA 변경 행: 빨강 배경 + `이전 → 새` 표기.

#### `db/` — SQLite
- 위치: `%APPDATA%/bl-tracker/db.sqlite` (Windows). macOS dev에서는 `~/Library/Application Support/bl-tracker/db.sqlite`.
- 단순 sqlite3 + 수동 마이그레이션 스크립트.

#### `packaging/`
- PyInstaller spec.
- Playwright Chromium: 빌드 시 동봉 (또는 첫 실행 시 다운로드 후 캐시). 디폴트는 **첫 실행 시 다운로드** (.exe 크기 절감).
- exe 시작 시 0.0.0.0:7777 대신 `127.0.0.1:7777`만 바인드 (보안).

## 5. 데이터 모델

```sql
CREATE TABLE shipments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bl_no           TEXT UNIQUE NOT NULL,
    imo_no          TEXT,
    eta             TEXT,                 -- 최신 ETA 문자열
    eta_prev_kst    TEXT,                 -- 비교 기준이 된 KST 어제 마지막 ETA
    eta_changed     INTEGER DEFAULT 0,    -- 0/1
    location        TEXT,                 -- 인근 해역/근해 텍스트
    lat             REAL,
    lon             REAL,
    bl_refreshed_at TEXT,                 -- ISO8601 KST
    loc_refreshed_at TEXT,
    memo            TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE eta_snapshots (
    shipment_id     INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    kst_date        TEXT NOT NULL,        -- 'YYYY-MM-DD' KST
    eta             TEXT,
    fetched_at      TEXT NOT NULL,        -- 그 일자의 마지막 갱신 시각
    PRIMARY KEY (shipment_id, kst_date)
);
```

### ETA 변경 판정 (KST 일자 기준)
갱신 시:
1. `now_kst = now in Asia/Seoul`. `today = now_kst.date()`. `yesterday = today - 1 day`.
2. 새 ETA 가져옴 → `eta_snapshots`에 `(shipment_id, today)` UPSERT.
3. `eta_snapshots`에서 `(shipment_id, yesterday)` 조회 → `prev`.
4. `eta_changed = (prev is not None and prev.eta != new_eta)`.
5. `shipments.eta_prev_kst = prev.eta`, `shipments.eta = new_eta`, `shipments.eta_changed = ...`.

어제 스냅샷이 없으면 `eta_changed = 0` (비교 기준 없음).

## 6. 위치 텍스트 처리 (A/B 프로토타입)

`vesselfinder.py`는 **두 값 모두** 반환:
- **A**: 페이지에 노출되는 area 텍스트 (예: `Off Busan`, `East China Sea`).
- **B**: lat/lon → reverse geocoding (해양 영역 사전 또는 marineregions / Nominatim 근사).

스파이크 단계에서 실제 5-10개 IMO로 비교 후 표시 필드 채택. 디폴트는 **A** (외부 API 의존 없음). lat/lon은 항상 DB에 저장.

## 7. 동시성 정책

- 단건 갱신: 즉시 1회.
- 선택/전체 새로고침: **동시성 3** (asyncio Semaphore 또는 Playwright context 풀). 1-2초 jitter.
- 진행률: SSE로 `{done, total, current_bl, status}` 스트림.
- 실패 BL/IMO: 행에 ⚠️ + 마지막 성공값/시각 유지. 부분 실패는 전체 작업 중단 없이 끝까지 진행.

## 8. 에러 처리

| 상황 | 처리 |
|---|---|
| 사이트 차단 / Cloudflare | 크롤러 `failed` 반환, 행에 ⚠️ + 사유 툴팁. 사용자가 잠시 후 재시도. |
| 사이트 DOM 변경 | 파서 실패 → `failed`, 사유에 "셀렉터 미스". 픽스처 단위 테스트로 조기 감지. |
| BL/IMO 미존재 | `failed: not_found`. 행에 표시. |
| 네트워크 오류 | 1회 재시도 후 `failed`. |
| 엑셀 import 시 중복 BL | UPSERT (bl_no 기준 갱신). |
| Playwright Chromium 미설치 | 첫 실행 시 자동 다운로드. 실패 시 사용자에게 안내 모달. |

## 9. 테스트 전략

- **크롤러 파서**: 저장된 HTML 픽스처에 대해 `parse_eta_html`, `parse_vessel_html` 단위 테스트.
- **크롤러 라이브**: CLI 모듈로 수동 스모크 (`python -m crawler.track_trace <BL>`).
- **API**: pytest + httpx + 인메모리 SQLite, CRUD/UPSERT/SSE 진행률.
- **ETA 비교 로직**: KST 경계(자정 직전/직후), 어제 스냅샷 없음, 동일 ETA 등 단위 테스트.
- **E2E**: 핵심 시나리오 1-2개 (엑셀 업로드 → 행 새로고침 → DB 갱신 확인). Playwright는 모킹.
- **패키징**: 빌드된 `.exe`로 수동 스모크 1회.

## 10. 구현 단계 (개략)

1. **Spike**: `crawler/track_trace.py`, `crawler/vesselfinder.py` CLI 단독 실행 → 5-10건으로 셀렉터/안정성/봇 차단 여부 검증. 위치 A/B 비교 후 채택.
2. **DB + API CRUD**: shipments / eta_snapshots, 기본 CRUD.
3. **갱신 API**: 단건 + bulk(동시성 3) + SSE 진행률.
4. **프론트 테이블**: 표 + 버튼 + ETA 변경 강조.
5. **엑셀 import/export**.
6. **PyInstaller 패키징**: 단일 exe + 첫 실행 다운로드.
7. **수동 스모크 + 사용자 테스트**.

## 11. 미해결 / 추후 결정

- 위치 A/B 채택은 Spike 결과로 결정.
- Playwright Chromium 동봉 vs 첫 실행 다운로드: 패키징 단계에서 exe 크기/UX 트레이드오프 확정.
- track-trace.com이 Cloudflare 챌린지를 강하게 거는 경우 carrier-direct 추적 스위칭(백업 안)은 본 스펙 범위 밖. 발생 시 별도 스펙.
