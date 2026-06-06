# 주간업무계획 회의자료 취합 시스템

부서별 주간업무계획 입력 자료를 날짜 세션별로 취합하고 HWPX 결과물을 생성하는 FastAPI 기반 행정 보고서 취합 웹앱입니다.

## 주요 기능

- 부서별 입력 화면
  - 행정팀, 장비회계팀, 홍보교육팀, 대응총괄팀, 구조팀, 구급팀, 예방팀, 검사지도팀, 위험물안전팀, 현장대응단
- 날짜 세션별 관리
- 부서별 입력/제출 현황 대시보드
- 큰 글씨, 한 줄 표시 중심의 행정 업무용 UI
- 개인정보 없는 무작위 예시 데이터
- HWPX 결과물 생성 및 다운로드

## 로컬 실행

```bash
cd /mnt/c/coding/weekly-work-plan-collector
uv run --with fastapi --with uvicorn --with pydantic uvicorn app:app --host 0.0.0.0 --port 8792
```

브라우저:

```text
http://127.0.0.1:8792/
```

## Vercel 배포

이 저장소는 Vercel Python Serverless Functions 배포를 위한 `requirements.txt`와 `vercel.json`을 포함합니다.

```bash
npx --yes vercel --prod
```

Vercel 환경에서는 생성 파일과 업로드/세션 데이터가 `/tmp`에 임시 저장됩니다. 서버리스 특성상 장기 보관 데이터베이스가 아니므로, 실제 운영에서는 별도 저장소 연동이 필요합니다.

## 원본 문서 관련 안내

사용자가 제공한 원본 `source.hwp`는 legacy binary HWP 형식이며 저장소와 Vercel 배포에서 제외했습니다. 원본 표, 글꼴, 쪽 나눔까지 완전히 동일한 자동 HWP/HWPX 출력을 구현하려면 한컴오피스에서 HWPX로 변환한 뒤 XML 텍스트 노드 매핑을 추가해야 합니다.

현재 배포 버전은 웹 입력/취합/HWPX 생성용 MVP입니다.
