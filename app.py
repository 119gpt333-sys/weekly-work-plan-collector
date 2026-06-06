from __future__ import annotations

import base64
import json
import os
import random
import re
import shutil
import time
import zipfile
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

APP_VERSION = "2026.06.06-r10-item-layout-fix"
ROOT = Path(__file__).resolve().parent
IS_VERCEL = bool(os.environ.get("VERCEL"))
RUNTIME_ROOT = Path(os.environ.get("TMPDIR", "/tmp")) / "weekly-work-plan-collector" if IS_VERCEL else ROOT
DATA = RUNTIME_ROOT / "data"
OUTPUT = RUNTIME_ROOT / "output"
UPLOADS = RUNTIME_ROOT / "uploads"
SESSIONS = DATA / "sessions"
TEMPLATES = ROOT / "templates"
SOURCE_HWP = TEMPLATES / "source.hwp"
SEED_JSON = DATA / "seed.json"
OUTPUT.mkdir(parents=True, exist_ok=True)
DATA.mkdir(parents=True, exist_ok=True)
UPLOADS.mkdir(parents=True, exist_ok=True)
SESSIONS.mkdir(parents=True, exist_ok=True)

DEPARTMENT_ORDER = [
    "행정팀", "장비회계팀", "홍보교육팀", "대응총괄팀", "구조팀", "구급팀",
    "예방팀", "검사지도팀", "위험물안전팀", "현장대응단",
]

app = FastAPI(title="주간업무계획 회의자료 취합 시스템", version=APP_VERSION)


class WorkItem(BaseModel):
    title: str = ""
    details: list[str] = []


class GenerateRequest(BaseModel):
    week_title: str = "2026. 6. 8.(월) ~ 6. 12.(금)"
    meeting_date: str = "2026. 6. 8.(월)"
    writer: str = ""
    mode: str = "html"
    session_id: str = ""
    departments: dict[str, list[WorkItem]]


class UploadJsonRequest(BaseModel):
    department: str
    filename: str
    content_type: str = "application/octet-stream"
    data_url: str
    session_id: str = ""


class CreateSessionRequest(BaseModel):
    week_title: str
    meeting_date: str = ""


def build_random_demo_seed() -> dict[str, list[dict[str, Any]]]:
    """개인정보 없는 부서별 무작위 표시용 예시 데이터."""
    title_pool = {
        "행정팀": ["근무편성 기준 점검", "복무관리 자료 정비", "청사 운영 개선사항 검토", "민원 응대 절차 안내"],
        "장비회계팀": ["소모품 재고 현황 점검", "장비 유지관리 일정 조정", "계약 집행 자료 정리", "차량 점검 결과 취합"],
        "홍보교육팀": ["안전교육 콘텐츠 정비", "홍보자료 배포계획 수립", "교육 참석 현황 취합", "캠페인 운영 결과 정리"],
        "대응총괄팀": ["재난대응 훈련계획 검토", "상황관리 보고체계 점검", "출동 통계 기초자료 정리", "비상연락망 현행화"],
        "구조팀": ["구조장비 운용상태 확인", "전문훈련 일정 조정", "현장활동 사례 공유", "위험지역 사전 점검"],
        "구급팀": ["구급품목 보유량 확인", "응급처치 교육자료 정비", "구급활동 통계 점검", "감염관리 체크리스트 보완"],
        "예방팀": ["화재예방 안내자료 정비", "점검대상 일정 조율", "안전관리 홍보계획 검토", "예방행정 처리현황 취합"],
        "검사지도팀": ["대상처 지도점검 일정 정리", "보완요청 처리현황 확인", "검사결과 통계자료 작성", "관계자 안내문 검토"],
        "위험물안전팀": ["위험물 시설 점검계획 수립", "안전관리자 교육현황 확인", "허가자료 정비", "위험물 민원 처리현황 점검"],
        "현장대응단": ["현장대응 절차 숙달훈련", "출동장비 배치상태 확인", "대응활동 평가자료 정리", "근무조별 전달사항 취합"],
    }
    detail_pool = [
        "○ 세부 추진일정 및 담당자 확인",
        "○ 관련 자료 취합 후 내부 검토 예정",
        "○ 부서별 의견 반영 및 보완사항 정리",
        "○ 추진 결과는 다음 회의자료에 반영",
        "○ 현황표 업데이트 및 공유폴더 게시",
        "○ 미비사항은 주중 보완 후 재확인",
        "○ 유관 부서 협조사항 별도 안내",
        "○ 개인정보 없는 통계자료 기준으로 작성",
    ]
    seed: dict[str, list[dict[str, Any]]] = {}
    for dept in DEPARTMENT_ORDER:
        count = random.randint(1, 3)
        titles = random.sample(title_pool[dept], count)
        seed[dept] = []
        for title in titles:
            details = random.sample(detail_pool, random.randint(2, 4))
            seed[dept].append({"title": title, "details": details})
    return seed


def load_seed() -> dict[str, list[dict[str, Any]]]:
    return build_random_demo_seed()


def make_session_id(week_title: str, meeting_date: str = "") -> str:
    base = f"{week_title} {meeting_date}"
    nums = re.findall(r"\d+", base)
    if len(nums) >= 3:
        year = nums[0]
        month = nums[1].zfill(2)
        day = nums[2].zfill(2)
        sid = f"{year}{month}{day}"
    else:
        sid = datetime.now().strftime("%Y%m%d")
    return safe_session_id(sid)


def safe_session_id(session_id: str | None) -> str:
    session_id = re.sub(r"[^0-9A-Za-z_-]+", "", session_id or "")
    return session_id or "20260608"


def session_dir(session_id: str | None) -> Path:
    sid = safe_session_id(session_id)
    path = SESSIONS / sid
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_upload_dir(session_id: str | None) -> Path:
    sid = safe_session_id(session_id)
    path = UPLOADS / sid
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_meta_path(session_id: str | None) -> Path:
    return session_dir(session_id) / "meta.json"


def upload_status_path(session_id: str | None) -> Path:
    return session_dir(session_id) / "upload_status.json"


def save_session_meta(session_id: str, week_title: str, meeting_date: str = "") -> dict[str, Any]:
    sid = safe_session_id(session_id)
    meta = {
        "session_id": sid,
        "week_title": week_title.strip() or sid,
        "meeting_date": meeting_date.strip(),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = session_meta_path(sid)
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        meta["created_at"] = old.get("created_at", meta["created_at"])
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def ensure_default_session() -> dict[str, Any]:
    default = "20260608"
    if not session_meta_path(default).exists():
        save_session_meta(default, "2026. 6. 8.(월) ~ 6. 12.(금)", "2026. 6. 8.(월)")
    # migrate old single-session status if it exists
    old_status = DATA / "upload_status.json"
    new_status = upload_status_path(default)
    if old_status.exists() and not new_status.exists():
        shutil.copy2(old_status, new_status)
    old_uploads = UPLOADS
    default_uploads = old_uploads / default
    for dept in DEPARTMENT_ORDER:
        legacy = old_uploads / dept
        if legacy.exists() and legacy.is_dir():
            target = default_uploads / dept
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.move(str(legacy), str(target))
    return json.loads(session_meta_path(default).read_text(encoding="utf-8"))


def list_sessions() -> list[dict[str, Any]]:
    ensure_default_session()
    rows = []
    for meta_path in SESSIONS.glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        status = load_upload_status(meta.get("session_id"))
        meta["summary"] = upload_summary(status)
        rows.append(meta)
    rows.sort(key=lambda x: x.get("session_id", ""), reverse=True)
    return rows


def empty_upload_status() -> dict[str, Any]:
    return {
        "updated_at": "",
        "departments": {
            dept: {"uploaded": False, "filename": "", "size": 0, "uploaded_at": "", "content_type": ""}
            for dept in DEPARTMENT_ORDER
        },
    }


def load_upload_status(session_id: str | None = None) -> dict[str, Any]:
    status = empty_upload_status()
    path = upload_status_path(session_id)
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            for dept, info in saved.get("departments", {}).items():
                if dept in status["departments"]:
                    status["departments"][dept].update(info)
            status["updated_at"] = saved.get("updated_at", "")
        except Exception:
            pass
    return status


def save_upload_status(status: dict[str, Any], session_id: str | None = None) -> None:
    status["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    upload_status_path(session_id).write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_filename(name: str) -> str:
    name = Path(name or "upload.bin").name
    return re.sub(r"[^0-9A-Za-z가-힣._ -]+", "_", name).strip() or "upload.bin"


def upload_summary(status: dict[str, Any]) -> dict[str, Any]:
    depts = status.get("departments", {})
    submitted = sum(1 for d in DEPARTMENT_ORDER if depts.get(d, {}).get("uploaded"))
    total = len(DEPARTMENT_ORDER)
    return {"submitted": submitted, "total": total, "ratio": round(submitted / total * 100, 1) if total else 0}


def normalize_payload(payload: GenerateRequest) -> dict[str, Any]:
    result = {
        "week_title": payload.week_title.strip(),
        "meeting_date": payload.meeting_date.strip(),
        "writer": payload.writer.strip(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "departments": {},
    }
    for dept in DEPARTMENT_ORDER + [d for d in payload.departments.keys() if d not in DEPARTMENT_ORDER]:
        rows = []
        for item in payload.departments.get(dept, []):
            title = item.title.strip()
            details = [x.strip() for x in item.details if x.strip()]
            if title or details:
                rows.append({"title": title, "details": details})
        result["departments"][dept] = rows
    return result


def render_report_html(data: dict[str, Any]) -> str:
    dept_cards = []
    total = 0
    for dept, items in data["departments"].items():
        if not items:
            continue
        total += len(items)
        body = []
        for item in items:
            body.append(f"<section class='item'><h3>󰏚 {escape(item['title'])}</h3>")
            if item["details"]:
                body.append("<ul>")
                for detail in item["details"]:
                    body.append(f"<li>{escape(detail)}</li>")
                body.append("</ul>")
            body.append("</section>")
        dept_cards.append(f"<article class='dept'><div class='dept-head'><h2>{escape(dept)}</h2><span>{len(items)}건</span></div>{''.join(body)}</article>")
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>주간업무계획 회의자료</title>
<style>
@page {{ size: A4; margin: 16mm 14mm; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family: 'Malgun Gothic','맑은 고딕',Arial,sans-serif; color:#111827; background:#eef2f7; }}
.sheet {{ width: 210mm; min-height: 297mm; margin: 24px auto; background:white; padding: 18mm 16mm; box-shadow: 0 20px 60px rgba(15,23,42,.18); }}
.report-top {{ border-bottom: 4px solid #0f2a44; padding-bottom: 14px; margin-bottom: 18px; display:flex; justify-content:space-between; gap:16px; align-items:end; }}
.kicker {{ color:#2b5d7e; font-weight:800; letter-spacing:.18em; font-size:13px; }}
h1 {{ margin: 7px 0 0; font-size: 30px; letter-spacing:-.04em; }}
.meta {{ text-align:right; font-size:13px; line-height:1.7; color:#475569; }}
.summary {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:16px 0 22px; }}
.summary div {{ border:1px solid #d7dee9; border-left:5px solid #1f5f8b; padding:10px 12px; background:#f8fafc; }}
.summary b {{ display:block; font-size:20px; color:#0f2a44; }}
.dept {{ page-break-inside: avoid; border-top:2px solid #1f2937; margin:18px 0 22px; padding-top:10px; }}
.dept-head {{ display:flex; align-items:center; justify-content:space-between; background:#f1f5f9; border:1px solid #d9e1ec; padding:8px 12px; margin-bottom:8px; }}
.dept-head h2 {{ margin:0; font-size:20px; }}
.dept-head span {{ font-weight:800; color:#174968; }}
.item {{ padding:8px 4px 10px; border-bottom:1px dashed #cbd5e1; }}
.item h3 {{ margin:0 0 6px; font-size:16px; line-height:1.45; color:#111827; }}
ul {{ margin:0 0 0 23px; padding:0; }}
li {{ margin:3px 0; line-height:1.55; font-size:14px; }}
.footer {{ margin-top:28px; padding-top:10px; border-top:1px solid #d7dee9; color:#64748b; font-size:11px; text-align:right; }}
@media print {{ body {{ background:white; }} .sheet {{ margin:0; box-shadow:none; width:auto; min-height:auto; }} }}
</style>
</head>
<body><main class="sheet">
<header class="report-top"><div><div class="kicker">WEEKLY WORK PLAN</div><h1>주간업무계획 회의자료</h1></div><div class="meta">회의일자: {escape(data['meeting_date'])}<br>대상기간: {escape(data['week_title'])}<br>취합시각: {escape(data['generated_at'])}</div></header>
<section class="summary"><div><span>제출부서</span><b>{len([d for d,i in data['departments'].items() if i])}</b></div><div><span>업무건수</span><b>{total}</b></div><div><span>작성자</span><b>{escape(data['writer'] or '관리부서')}</b></div></section>
{''.join(dept_cards)}
<div class="footer">주간업무계획 회의자료 취합 시스템 v{APP_VERSION}</div>
</main></body></html>"""


def hwpx_paragraph(text: str, pid: int) -> str:
    return f'<hp:p id="{pid}" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>{escape(text or "")}</hp:t></hp:run></hp:p>'


def build_hwpx_section(data: dict[str, Any]) -> str:
    paras: list[str] = []
    pid = 1
    for line in [
        "주간업무계획 회의자료",
        f"회의일자: {data.get('meeting_date', '')}",
        f"대상기간: {data.get('week_title', '')}",
        f"취합시각: {data.get('generated_at', '')}",
        "",
    ]:
        paras.append(hwpx_paragraph(line, pid)); pid += 1
    for dept in DEPARTMENT_ORDER:
        items = data.get("departments", {}).get(dept, [])
        if not items:
            continue
        paras.append(hwpx_paragraph(f"□ {dept}", pid)); pid += 1
        for item in items:
            title = item.get("title", "").strip()
            details = [x.strip() for x in item.get("details", []) if x.strip()]
            if title:
                paras.append(hwpx_paragraph(f"  ○ {title}", pid)); pid += 1
            for detail in details:
                paras.append(hwpx_paragraph(f"    - {detail.lstrip('○-· ')}", pid)); pid += 1
        paras.append(hwpx_paragraph("", pid)); pid += 1
    if len(paras) <= 5:
        paras.append(hwpx_paragraph("입력된 자료가 없습니다.", pid))
    return "".join(paras)


def write_hwpx(data: dict[str, Any], out_path: Path) -> None:
    """Create a simple HWPX package that contains the consolidated text."""
    section = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core">
{build_hwpx_section(data)}
</hp:sec>'''
    header = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core">
  <hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>
  <hh:refList/>
  <hh:fontfaces itemCnt="1"><hh:fontface lang="KO" fontCnt="1"><hh:font id="0" face="맑은 고딕" type="TTF"/></hh:fontface></hh:fontfaces>
  <hh:styles itemCnt="1"><hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langID="1042" lockForm="0"/></hh:styles>
  <hh:paraProperties itemCnt="1"><hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" suppressLineNumbers="0" checked="0"/></hh:paraProperties>
  <hh:charProperties itemCnt="1"><hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0"><hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/></hh:charPr></hh:charProperties>
</hh:head>'''
    content_hpf = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<opf:package xmlns:opf="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <opf:metadata><opf:title>주간업무계획 회의자료</opf:title><opf:language>ko-KR</opf:language></opf:metadata>
  <opf:manifest><opf:item id="header" href="header.xml" media-type="application/xml"/><opf:item id="section0" href="section0.xml" media-type="application/xml"/></opf:manifest>
  <opf:spine><opf:itemref idref="section0"/></opf:spine>
</opf:package>'''
    version = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><hv:version xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" app="한글" major="1" minor="0" micro="0" buildNumber="1"/>'''
    settings = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><hs:settings xmlns:hs="http://www.hancom.co.kr/hwpml/2011/settings"/>'''
    container = '''<?xml version="1.0" encoding="UTF-8"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/></rootfiles></container>'''
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("version.xml", version)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("Contents/content.hpf", content_hpf)
        zf.writestr("Contents/header.xml", header)
        zf.writestr("Contents/section0.xml", section)
        zf.writestr("Settings/settings.xml", settings)


@app.get("/health")
def health():
    return {"ok": True, "version": APP_VERSION, "source_hwp": SOURCE_HWP.exists()}


@app.get("/api/sessions")
def api_sessions():
    return JSONResponse({"ok": True, "sessions": list_sessions(), "default": ensure_default_session()})


@app.post("/api/sessions")
def api_create_session(req: CreateSessionRequest):
    sid = make_session_id(req.week_title, req.meeting_date)
    original = sid
    counter = 2
    while session_meta_path(sid).exists():
        existing = json.loads(session_meta_path(sid).read_text(encoding="utf-8"))
        if existing.get("week_title") == req.week_title.strip() and existing.get("meeting_date", "") == req.meeting_date.strip():
            break
        sid = f"{original}_{counter}"
        counter += 1
    meta = save_session_meta(sid, req.week_title, req.meeting_date)
    return JSONResponse({"ok": True, "session": meta, "sessions": list_sessions()})


@app.get("/api/seed")
def api_seed():
    return JSONResponse(load_seed())


@app.get("/api/upload-status")
def api_upload_status(session_id: str = ""):
    sid = safe_session_id(session_id)
    ensure_default_session()
    status = load_upload_status(sid)
    status["session_id"] = sid
    status["summary"] = upload_summary(status)
    return JSONResponse(status)


@app.post("/api/upload-json")
def api_upload_json(req: UploadJsonRequest):
    sid = safe_session_id(req.session_id)
    ensure_default_session()
    if req.department not in DEPARTMENT_ORDER:
        raise HTTPException(status_code=400, detail="등록되지 않은 부서입니다.")
    if not req.data_url.startswith("data:") or "," not in req.data_url:
        raise HTTPException(status_code=400, detail="파일 데이터 형식이 올바르지 않습니다.")
    meta, encoded = req.data_url.split(",", 1)
    try:
        raw = base64.b64decode(encoded)
    except Exception:
        raise HTTPException(status_code=400, detail="파일을 읽을 수 없습니다.")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="20MB 이하 파일만 업로드할 수 있습니다.")
    dept_dir = session_upload_dir(sid) / req.department
    dept_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(req.filename)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved_name = f"{stamp}_{filename}"
    saved_path = dept_dir / saved_name
    saved_path.write_bytes(raw)
    status = load_upload_status(sid)
    status["departments"][req.department] = {
        "uploaded": True,
        "filename": filename,
        "saved_name": saved_name,
        "size": len(raw),
        "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "content_type": req.content_type or "application/octet-stream",
    }
    save_upload_status(status, sid)
    status["session_id"] = sid
    status["summary"] = upload_summary(status)
    return JSONResponse({"ok": True, "status": status})


@app.post("/api/reset")
def api_reset(session_id: str = ""):
    sid = safe_session_id(session_id)
    path = upload_status_path(sid)
    if path.exists():
        path.unlink()
    upload_dir = session_upload_dir(sid)
    if upload_dir.exists():
        shutil.rmtree(upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    status = empty_upload_status()
    status["session_id"] = sid
    status["summary"] = upload_summary(status)
    return JSONResponse({"ok": True, "status": status, "departments": {dept: [] for dept in DEPARTMENT_ORDER}})


@app.get("/", response_class=HTMLResponse)
def index():
    ensure_default_session()
    seed = load_seed()
    source_note = "원본 HWP 보관 완료" if SOURCE_HWP.exists() else "원본 HWP 없음"
    html = (INDEX_HTML
        .replace("__SEED__", json.dumps(seed, ensure_ascii=False))
        .replace("__SESSIONS__", json.dumps(list_sessions(), ensure_ascii=False))
        .replace("__VERSION__", APP_VERSION)
        .replace("__SOURCE_NOTE__", source_note))
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.post("/api/generate")
def generate(req: GenerateRequest):
    sid = safe_session_id(req.session_id)
    data = normalize_payload(req)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    hwpx_path = (OUTPUT / f"weekly_report_{sid}_{stamp}").with_suffix(".hwpx")
    write_hwpx(data, hwpx_path)
    if IS_VERCEL:
        encoded = base64.b64encode(hwpx_path.read_bytes()).decode("ascii")
        hwpx_link = f"data:application/hwp+zip;base64,{encoded}"
    else:
        hwpx_link = f"/download/{hwpx_path.name}"
    return JSONResponse({
        "ok": True,
        "hwpx": hwpx_link,
        "filename": hwpx_path.name,
        "note": "취합 결과물은 HWPX 파일만 생성됩니다."
    })


@app.get("/download/{name}")
def download(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(status_code=400, detail="bad name")
    path = OUTPUT / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    if path.suffix == ".hwpx":
        media = "application/hwp+zip"
    elif path.suffix == ".html":
        media = "text/html; charset=utf-8"
    else:
        media = "application/octet-stream"
    return FileResponse(path, media_type=media, filename=path.name)


INDEX_HTML = r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>주간업무계획 회의자료 취합 시스템</title>
<style>
:root{
  --navy:#0b2540;--navy2:#123d66;--blue:#1d70b8;--green:#1f8a70;--bg:#edf3f8;--card:#ffffff;--line:#cfd9e5;--text:#102033;--muted:#607085;--danger:#b42318;
}
*{box-sizing:border-box}
html{min-width:1100px}
body{margin:0;font-family:'Malgun Gothic','맑은 고딕',Dotum,'돋움',Arial,sans-serif;color:var(--text);background:radial-gradient(circle at 8% 0%,rgba(29,112,184,.18),transparent 30%),radial-gradient(circle at 96% 10%,rgba(31,138,112,.15),transparent 28%),linear-gradient(180deg,#f4f8fb 0%,#edf3f8 50%,#f7fafc 100%)}
body:before{content:'';position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(15,37,64,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(15,37,64,.035) 1px,transparent 1px);background-size:34px 34px;mask-image:linear-gradient(180deg,rgba(0,0,0,.7),transparent 75%)}
.header{position:relative;background:linear-gradient(135deg,#08233d 0%,#123d66 58%,#155f72 100%);color:#fff;padding:0 24px 28px;box-shadow:0 14px 36px rgba(8,35,61,.22);overflow:hidden}.header:before{content:'';position:absolute;right:9%;top:22px;width:260px;height:260px;border:1px solid rgba(255,255,255,.18);border-radius:50%;box-shadow:0 0 0 44px rgba(255,255,255,.035),0 0 0 88px rgba(255,255,255,.025)}.header:after{content:'REPORT';position:absolute;right:46px;bottom:-28px;font-weight:900;font-size:96px;letter-spacing:.08em;color:rgba(255,255,255,.055)}
.header-inner{position:relative;z-index:1;max-width:1180px;margin:0 auto;padding-top:30px;display:grid;grid-template-columns:1fr auto;gap:26px;align-items:end}.header .kicker{display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:800;letter-spacing:.18em;color:#cbe5f5;margin-bottom:9px}.header .kicker:before{content:'';width:8px;height:8px;background:#4ade80;border-radius:50%;box-shadow:0 0 0 5px rgba(74,222,128,.16)}.header h1{margin:0;font-size:32px;line-height:1.2;letter-spacing:-.04em}.header p{margin:10px 0 0;color:#d7e8f5;line-height:1.6;font-size:14px;max-width:720px}
.hero-card{min-width:270px;border:1px solid rgba(255,255,255,.22);background:rgba(255,255,255,.10);border-radius:18px;padding:18px 20px;backdrop-filter:blur(10px);box-shadow:0 18px 50px rgba(0,0,0,.18)}.hero-card b{display:block;font-size:15px;margin-bottom:6px}.hero-card span{display:block;color:#d7e8f5;font-size:12px;line-height:1.55}.hero-card .seal{width:42px;height:42px;border-radius:13px;background:linear-gradient(135deg,#fff,#d9ecff);color:#123d66;display:grid;place-items:center;font-weight:900;margin-bottom:10px}.top-actions{position:relative;z-index:1;max-width:1180px;margin:20px auto 0;display:flex;gap:10px;flex-wrap:wrap;justify-content:flex-end}
.wrap{width:min(1180px,calc(100% - 48px));margin:24px auto 70px;padding:0}.wrap:before{content:'행정 보고서 취합 · 날짜 세션별 관리 · HWPX 단일 출력';display:block;margin:0 auto 14px;padding:10px 14px;border:1px solid #d3e1ee;border-left:5px solid var(--blue);background:rgba(255,255,255,.78);border-radius:12px;color:#37516b;font-size:13px;font-weight:800;box-shadow:0 8px 24px rgba(15,37,64,.06)}
.panel,.summary-card,.status-board,.session-bar{background:rgba(255,255,255,.94);border:1px solid var(--line);box-shadow:0 16px 42px rgba(15,37,64,.09)}.panel{border-radius:18px;overflow:hidden}.dashboard{display:grid;grid-template-columns:300px 1fr;gap:18px;margin-bottom:18px}.summary-card,.status-board{border-radius:18px;padding:20px}.summary-card h2,.status-board h2{margin:0 0 12px;font-size:18px;letter-spacing:-.03em;color:#12304f}.summary-card h2:before,.status-board h2:before{content:'';display:inline-block;width:7px;height:18px;background:var(--blue);border-radius:6px;margin-right:8px;vertical-align:-3px}.ratio{font-size:46px;font-weight:900;color:var(--navy);line-height:1}.ratio small{font-size:18px;color:var(--muted)}.progress{height:16px;border-radius:999px;background:#e2e8f0;overflow:hidden;margin:15px 0}.progress span{display:block;height:100%;width:0%;background:linear-gradient(90deg,var(--blue),var(--green));transition:width .25s}.summary-meta{color:#52657a;line-height:1.7;font-size:14px}.status-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:9px}.status-tile{border:1px solid #d8e2ec;border-radius:12px;padding:10px;background:#f8fafc;min-height:74px;transition:.15s}.status-tile.done{border-color:#94d9c0;background:linear-gradient(180deg,#f0fdf8,#ecfdf5)}.status-tile.missing{border-color:#f4d48a;background:#fffaf0}.status-tile b{display:block;font-size:14px;margin-bottom:5px}.status-tile span{display:block;color:#66788b;font-size:12px;line-height:1.35;word-break:break-all}
.session-bar{display:grid;grid-template-columns:1.1fr 1fr .8fr 190px 150px;gap:12px;align-items:end;border-radius:18px;margin-bottom:18px;padding:17px}.session-bar label,.field label{display:block;font-size:12px;font-weight:900;color:#334b63;margin-bottom:7px}.session-bar input,.session-bar select,.field input{width:100%;height:44px;border:1px solid #cbd7e3;border-radius:10px;padding:0 12px;font-size:14px;background:#fff;outline:none}.session-bar input:focus,.session-bar select:focus,.field input:focus,.item input:focus,.item textarea:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(29,112,184,.13)}
.toolbar{display:grid;grid-template-columns:1.25fr .8fr .7fr 190px;gap:14px;padding:20px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#fbfdff,#f4f8fc)}.status{font-size:12px;line-height:1.55;color:#607085;background:#f3f7fb;border:1px solid #d8e2ec;border-radius:10px;padding:9px 11px;min-height:44px}.main{display:grid;grid-template-columns:230px 1fr;min-height:530px}.side{background:#f3f7fb;border-right:1px solid var(--line);padding:16px}.dept-btn{width:100%;border:1px solid transparent;background:transparent;text-align:left;padding:12px 12px;border-radius:11px;font-weight:800;color:#334155;cursor:pointer;margin-bottom:7px;display:flex;justify-content:space-between;align-items:center}.dept-btn:hover{background:#eaf2fa}.dept-btn.active{background:#123d66;color:#fff;box-shadow:0 8px 22px rgba(18,61,102,.18)}.dept-btn span{background:rgba(255,255,255,.72);color:#31536f;border-radius:999px;padding:2px 8px;font-size:12px}.dept-btn.active span{background:rgba(255,255,255,.18);color:#fff}.content{padding:22px 24px 26px}.section-title{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}.section-title h2{margin:0;font-size:24px;color:#102b46;letter-spacing:-.03em}.section-title h2:after{content:' 입력 서식';font-size:13px;color:#607085;font-weight:700;margin-left:8px}.hint{border:1px solid #cfe1f1;background:linear-gradient(180deg,#f2f8fd,#ffffff);border-radius:12px;padding:12px 14px;color:#466076;font-size:13px;line-height:1.55;margin-bottom:14px}.count{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:0 0 16px}.count div{border:1px solid #dbe4ee;background:#fff;border-radius:12px;padding:10px;color:#607085;font-size:12px}.count b{display:block;margin-top:4px;font-size:18px;color:#123d66}.item{border:1px solid #d8e2ec;border-radius:14px;background:#fff;margin-bottom:14px;padding:14px;box-shadow:0 10px 26px rgba(15,37,64,.05)}.item-top{display:grid;grid-template-columns:minmax(0,1fr) 88px;gap:12px;margin-bottom:12px;align-items:start}.item input{display:block;width:100%;min-width:0;height:52px;border:1px solid #cbd7e3;border-radius:12px;padding:0 15px;font-size:18px;font-weight:800;color:#102033;background:#fff;outline:none}.item textarea{display:block;width:100%;min-width:0;min-height:170px;border:1px solid #cbd7e3;border-radius:12px;padding:15px 16px;font-size:18px;line-height:1.55;resize:vertical;color:#102033;background:#fbfdff;outline:none;white-space:pre-wrap}.actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:flex-end;padding:18px 22px;border-top:1px solid var(--line);background:#f8fbfe}.download a{display:inline-flex;margin:4px 8px 0 0;padding:7px 10px;border-radius:9px;background:#e8f2fb;color:#0b5fa5;text-decoration:none;font-weight:800}.notice{max-width:1180px;margin:14px auto;color:#607085;font-size:12px;line-height:1.55}.btn{height:42px;border:0;border-radius:10px;padding:0 15px;font-weight:900;cursor:pointer;font-family:inherit}.btn.primary{background:linear-gradient(135deg,#1769aa,#1f8a70);color:#fff;box-shadow:0 8px 20px rgba(23,105,170,.22)}.btn.ghost{background:#fff;color:#123d66;border:1px solid #cbd7e3}.btn.reset,.btn.danger{background:#fff1f1;color:var(--danger);border:1px solid #f2b8b5}.btn.danger{width:88px;padding:0 10px}.btn:hover{filter:brightness(.98);transform:translateY(-1px)}
.large-type-note{display:none}
body{font-size:17px;line-height:1.42}.header-inner{grid-template-columns:1fr}.header h1{font-size:40px}.header p{font-size:18px;line-height:1.42;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}.header .kicker{font-size:14px}.wrap{width:min(1280px,calc(100% - 48px))}.wrap:before{font-size:16px;padding:13px 16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.top-actions{max-width:1280px}.btn{font-size:16px!important;min-height:48px;padding:0 18px!important;display:inline-flex;align-items:center;justify-content:center;white-space:nowrap;line-height:1!important}.summary-card h2,.status-board h2{font-size:22px;line-height:1.25;white-space:nowrap}.summary-meta{font-size:17px;line-height:1.45;white-space:nowrap}.dashboard{grid-template-columns:320px 1fr;align-items:stretch}.status-grid{grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}.status-tile{min-height:78px;padding:12px 13px;display:flex;flex-direction:column;justify-content:center;gap:5px;overflow:hidden}.status-tile b{font-size:17px;line-height:1.2;margin:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.status-tile span{font-size:15px;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.session-bar{grid-template-columns:1.05fr 1.15fr .85fr 220px 180px;align-items:end}.session-bar label,.field label{font-size:15px;line-height:1.2;white-space:nowrap}.session-bar input,.session-bar select,.field input{height:52px;font-size:18px;line-height:1.2}.status{font-size:16px;line-height:1.35;min-height:52px;display:flex;align-items:center}.toolbar{grid-template-columns:1.2fr .8fr .7fr 210px;align-items:end}.main{grid-template-columns:260px 1fr}.dept-btn{font-size:17px;line-height:1.2;padding:14px 13px;white-space:nowrap;gap:8px}.dept-btn span{font-size:14px;white-space:nowrap;flex:0 0 auto}.section-title h2{font-size:30px;line-height:1.2;white-space:nowrap}.section-title h2:after{font-size:16px}.hint{font-size:17px;line-height:1.42;padding:15px 16px}.count div{font-size:15px;line-height:1.25;padding:13px}.count b{font-size:22px;line-height:1.2}.item{padding:18px}.item input,.item textarea{font-size:18px!important;line-height:1.42!important}.item input{height:52px}.item textarea{min-height:170px}.item-top{grid-template-columns:minmax(0,1fr) 92px;align-items:start}.actions{align-items:center}.download a{white-space:nowrap}.result{font-size:17px;line-height:1.45}.file-row{font-size:16px;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.ratio{font-size:54px}.ratio small{font-size:22px}

.overview{display:grid;grid-template-columns:1.05fr .95fr;gap:16px;margin:0 0 18px}.overview-card{position:relative;overflow:hidden;background:rgba(255,255,255,.96);border:1px solid var(--line);border-radius:18px;padding:20px 22px;box-shadow:0 16px 42px rgba(15,37,64,.08)}.overview-card:before{content:'';position:absolute;right:-34px;top:-34px;width:132px;height:132px;border-radius:50%;background:linear-gradient(135deg,rgba(29,112,184,.10),rgba(31,138,112,.10))}.overview-card h2{position:relative;margin:0 0 10px;font-size:23px;line-height:1.25;color:#102b46;letter-spacing:-.03em;white-space:nowrap}.overview-card h2:before{content:'';display:inline-block;width:7px;height:20px;background:var(--green);border-radius:6px;margin-right:9px;vertical-align:-4px}.overview-card p{position:relative;margin:0;color:#40566f;font-size:17px;line-height:1.48}.overview-card ul{position:relative;margin:10px 0 0 0;padding:0;list-style:none;display:grid;gap:8px}.overview-card li{font-size:16px;line-height:1.35;color:#334b63;padding-left:28px;position:relative}.overview-card li:before{content:'✓';position:absolute;left:0;top:0;width:20px;height:20px;border-radius:6px;background:#e6f7ef;color:#168058;display:grid;place-items:center;font-weight:900;font-size:13px}.flow-list{counter-reset:step;display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}.flow-step{counter-increment:step;border:1px solid #d8e2ec;border-radius:14px;background:#f8fbfe;padding:13px 12px;min-height:86px}.flow-step b{display:block;font-size:16px;color:#123d66;margin-bottom:6px;white-space:nowrap}.flow-step b:before{content:counter(step);display:inline-grid;place-items:center;width:24px;height:24px;border-radius:50%;background:#123d66;color:#fff;font-size:13px;margin-right:7px}.flow-step span{display:block;font-size:14px;line-height:1.32;color:#607085}.template-note{margin-top:12px;border:1px solid #bdd7ef;background:linear-gradient(180deg,#f2f8ff,#ffffff);border-radius:14px;padding:13px 15px;color:#35536d;font-size:15px;line-height:1.4}.template-note b{color:#0b4f7d}.input-guide{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}.input-guide div{border:1px solid #dbe7f0;background:#fbfdff;border-radius:12px;padding:11px 12px;font-size:15px;line-height:1.35;color:#425971}.input-guide b{display:block;color:#123d66;font-size:16px;margin-bottom:4px;white-space:nowrap}

@media(max-width:1180px){html{min-width:0}.header-inner,.top-actions{max-width:calc(100vw - 48px)}.wrap{width:calc(100% - 32px)}.dashboard,.main,.toolbar,.session-bar,.overview{grid-template-columns:1fr}.status-grid{grid-template-columns:repeat(2,1fr)}.flow-list,.input-guide{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<header class="header">
  <div class="header-inner">
    <div>
      <div class="kicker">WEEKLY WORK PLAN COLLECTION</div>
      <h1>주간업무계획 회의자료 취합 시스템</h1>
      <p>부서별 입력 자료를 중앙에서 취합하고, 날짜 세션별 제출 현황과 HWPX 결과물을 한 화면에서 관리합니다.</p>
    </div>
  </div>
  <div class="top-actions"><button class="btn ghost" onclick="loadSeed()">무작위 예시 새로 불러오기</button><button class="btn reset" onclick="resetAllData()">데이터 초기화</button><button class="btn primary" onclick="generate()">취합 결과물 생성</button></div>
</header>
<div class="wrap">
  <section class="overview" aria-label="시스템 소개">
    <article class="overview-card">
      <h2>시스템 개요</h2>
      <p>각 부서가 주간업무계획을 웹 서식에 맞게 입력하면, 관리부서가 제출 현황을 확인하고 HWPX 취합본을 생성하는 행정 보고서 취합 시스템입니다.</p>
      <ul>
        <li>부서별 입력 여부와 취합률을 상단 현황판에서 즉시 확인</li>
        <li>날짜 세션별로 회의자료를 분리 관리하여 자료 혼입 방지</li>
        <li>최종 결과는 HWPX 단일 파일로 내려받기</li>
      </ul>
    </article>
    <article class="overview-card">
      <h2>사용 순서</h2>
      <div class="flow-list">
        <div class="flow-step"><b>세션 선택</b><span>대상기간과 회의일자를 먼저 확인합니다.</span></div>
        <div class="flow-step"><b>부서 입력</b><span>왼쪽 부서를 선택하고 업무 제목과 세부내용을 입력합니다.</span></div>
        <div class="flow-step"><b>현황 확인</b><span>입력·제출률과 부서별 누락 상태를 점검합니다.</span></div>
        <div class="flow-step"><b>HWPX 생성</b><span>취합 결과물을 내려받아 회의자료로 사용합니다.</span></div>
      </div>
      <div class="template-note"><b>원본 서식 보존 방향:</b> 최종 운영 단계에서는 원본 HWPX 템플릿의 표·글꼴·여백을 유지하고 입력 텍스트만 지정 위치에 반영하는 방식으로 맞춥니다.</div>
    </article>
  </section>
  <section class="session-bar">
    <div><label>날짜 세션 선택</label><select id="sessionSelect" onchange="changeSession(this.value)"></select></div>
    <div><label>새 대상기간</label><input id="newWeek" placeholder="예: 2026. 6. 15.(월) ~ 6. 19.(금)"></div>
    <div><label>새 회의일자</label><input id="newMeeting" placeholder="예: 2026. 6. 15.(월)"></div>
    <button class="btn ghost" onclick="createDateSession()">다른 날짜 세션 만들기</button>
    <button class="btn reset" onclick="resetAllData()">현재 세션 초기화</button>
  </section>
  <section class="dashboard">
    <article class="summary-card"><h2>자료 입력·제출 현황</h2><div class="ratio"><span id="ratioText">0</span><small>%</small></div><div class="progress"><span id="ratioBar"></span></div><div class="summary-meta"><b id="submittedText">0 / 10개 부서 제출</b><br><span id="statusUpdated">최근 갱신: -</span></div></article>
    <article class="status-board"><h2>부서별 제출 상태</h2><div class="status-grid" id="statusGrid"></div></article>
  </section>
  <section class="panel">
  <div class="toolbar"><div class="field"><label>대상기간</label><input id="week" value="2026. 6. 8.(월) ~ 6. 12.(금)"></div><div class="field"><label>회의일자</label><input id="meeting" value="2026. 6. 8.(월)"></div><div class="field"><label>취합 담당</label><input id="writer" placeholder="예: 기획담당"></div><div class="field"><label>상태</label><div class="status">__SOURCE_NOTE__<br>v__VERSION__</div></div></div>
  <div class="main"><nav class="side" id="deptNav"></nav><main class="content"><div class="section-title"><h2 id="deptTitle"></h2><button class="btn ghost" onclick="addItem()">+ 업무 추가</button></div><div class="hint">부서별 업무를 직접 입력하면 상단 현황판에 입력 여부와 취합비율이 즉시 반영됩니다.</div><div class="input-guide"><div><b>제목 입력</b>업무명을 한 줄로 명확하게 작성합니다.</div><div><b>세부내용 입력</b>줄바꿈으로 추진일정·협조사항을 구분합니다.</div><div><b>자동 반영</b>입력 즉시 제출 상태와 취합률에 반영됩니다.</div></div><div class="count"><div>현재 부서<b id="deptCount">0건</b></div><div>전체 업무<b id="totalCount">0건</b></div><div>입력 부서<b id="filledCount">0개</b></div></div><div id="items"></div></main></div>
  <div class="actions"><button class="btn ghost" onclick="loadSeed()">무작위 예시 새로 불러오기</button><button class="btn reset" onclick="resetAllData()">데이터 초기화</button><button class="btn primary" onclick="generate()">취합 결과물 생성</button><div id="result" class="status download" style="min-width:360px">생성 전입니다.</div></div>
</section><p class="notice">※ 데이터 초기화는 현재 세션의 입력 내용, 업로드 현황, 저장된 업로드 파일을 모두 빈 상태로 비웁니다. 현재 웹 출력은 HWPX 취합본입니다. 원본과 완전히 동일한 편집 서식 출력은 원본 HWPX 변환 후 XML 위치 매핑을 적용해 운영 단계에서 확정합니다.</p></div>
<script>
const seed=__SEED__;
let sessions=__SESSIONS__;
const deptOrder=['행정팀','장비회계팀','홍보교육팀','대응총괄팀','구조팀','구급팀','예방팀','검사지도팀','위험물안전팀','현장대응단'];
let currentSession=(sessions[0]&&sessions[0].session_id)||'20260608';
let data={}; let current=deptOrder[0]; let uploadStatus={departments:{},summary:{submitted:0,total:deptOrder.length,ratio:0},updated_at:''};
function clone(o){return JSON.parse(JSON.stringify(o||{}));}
function renderSessions(){
  const sel=document.getElementById('sessionSelect'); if(!sel) return;
  sel.innerHTML='';
  sessions.forEach(s=>{const opt=document.createElement('option'); opt.value=s.session_id; const sum=s.summary||{}; opt.textContent=`${s.week_title} (${sum.submitted||0}/${sum.total||deptOrder.length})`; if(s.session_id===currentSession) opt.selected=true; sel.appendChild(opt);});
  const cur=sessions.find(s=>s.session_id===currentSession)||sessions[0];
  if(cur){document.getElementById('week').value=cur.week_title||document.getElementById('week').value; if(cur.meeting_date) document.getElementById('meeting').value=cur.meeting_date;}
}
async function refreshSessions(){try{const r=await fetch('/api/sessions',{cache:'no-store'}); if(r.ok){const j=await r.json(); sessions=j.sessions||sessions; if(!sessions.find(s=>s.session_id===currentSession) && sessions[0]) currentSession=sessions[0].session_id; renderSessions();}}catch(e){renderSessions();}}
async function changeSession(sid){currentSession=sid; renderSessions(); await loadUploadStatus(); document.getElementById('result').textContent='세션 전환 완료';}
async function createDateSession(){
  const week=document.getElementById('newWeek').value.trim(); const meeting=document.getElementById('newMeeting').value.trim();
  if(!week){alert('새 대상기간을 입력하세요.'); return;}
  const r=await fetch('/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({week_title:week,meeting_date:meeting})});
  const j=await r.json(); if(!j.ok){alert('세션 생성 실패'); return;}
  sessions=j.sessions||sessions; currentSession=j.session.session_id; renderSessions(); await loadUploadStatus(); document.getElementById('result').textContent='새 날짜 세션 생성 완료';
}
async function loadSeed(){
  try{const r=await fetch('/api/seed',{cache:'no-store'}); data=r.ok?await r.json():clone(seed);}catch(e){data=clone(seed);}
  deptOrder.forEach(d=>{if(!data[d])data[d]=[]}); renderNav(); renderDept();
}
async function loadUploadStatus(){
  try{const r=await fetch('/api/upload-status?session_id='+encodeURIComponent(currentSession),{cache:'no-store'}); if(r.ok) uploadStatus=await r.json();}catch(e){}
  renderUploadDashboard(); renderDeptUploadBox(); await refreshSessions();
}
function renderUploadDashboard(){
  const submitted=deptOrder.filter(d=>(((uploadStatus.departments||{})[d]||{}).uploaded)||deptHasInput(d)).length;
  const total=deptOrder.length;
  const ratio=total?Math.round(submitted/total*1000)/10:0;
  document.getElementById('ratioText').textContent=ratio;
  document.getElementById('ratioBar').style.width=ratio+'%';
  document.getElementById('submittedText').textContent=`${submitted} / ${total}개 부서 입력·제출`;
  document.getElementById('statusUpdated').textContent='최근 갱신: '+(uploadStatus.updated_at||'-');
  const grid=document.getElementById('statusGrid'); grid.innerHTML='';
  deptOrder.forEach(d=>{const info=(uploadStatus.departments||{})[d]||{}; const typed=deptHasInput(d); const done=info.uploaded||typed; const div=document.createElement('div'); div.className='status-tile '+(done?'done':'missing'); const label=info.uploaded?esc(info.filename||'파일 제출 완료'):(typed?`텍스트 입력됨 · ${deptTextItemCount(d)}건`:'미입력'); div.innerHTML=`<b>${done?'✅':'⏳'} ${d}</b><span>${label}</span><span>${info.uploaded?esc(info.uploaded_at||''):''}</span>`; grid.appendChild(div);});
}
function renderDeptUploadBox(){
  const title=document.getElementById('uploadTitle');
  const infoEl=document.getElementById('uploadInfo');
  if(!title || !infoEl) return;
  const info=(uploadStatus.departments||{})[current]||{};
  title.textContent=current+' 자료';
  infoEl.textContent=info.uploaded ? `제출 완료 · ${info.filename||''} · ${formatBytes(info.size||0)} · ${info.uploaded_at||''}` : '';
}
function deptTextItemCount(d){return (data[d]||[]).filter(x=>(x.title||'').trim()||(x.details||[]).join('').trim()).length;}
function deptHasInput(d){return deptTextItemCount(d)>0;}
function renderNav(){const nav=document.getElementById('deptNav'); nav.innerHTML=''; deptOrder.forEach(d=>{const b=document.createElement('button'); const up=(((uploadStatus.departments||{})[d]||{}).uploaded)||deptHasInput(d); b.className='dept-btn '+(d===current?'active':''); b.innerHTML=`${up?'✅ ':'⏳ '}${d}<span>${(data[d]||[]).length}</span>`; b.onclick=()=>{current=d;renderNav();renderDept()}; nav.appendChild(b);}); updateCounts();}
function renderDept(){document.getElementById('deptTitle').textContent=current; renderDeptUploadBox(); const f=document.getElementById('deptFile'); if(f) f.value=''; const box=document.getElementById('items'); box.innerHTML=''; (data[current]||[]).forEach((it,idx)=>{const div=document.createElement('div'); div.className='item'; div.innerHTML=`<div class="item-top"><input value="${esc(it.title||'')}" oninput="data[current][${idx}].title=this.value; updateCounts(); renderUploadDashboard(); renderNav();"><button class="btn danger" onclick="removeItem(${idx})">삭제</button></div><textarea oninput="data[current][${idx}].details=this.value.split('\\n'); updateCounts(); renderUploadDashboard(); renderNav();">${esc((it.details||[]).join('\n'))}</textarea>`; box.appendChild(div);}); updateCounts(); renderUploadDashboard();}
function addItem(){if(!data[current])data[current]=[]; data[current].push({title:'',details:['']}); renderNav(); renderDept(); renderUploadDashboard();}
function removeItem(i){data[current].splice(i,1); renderNav(); renderDept(); renderUploadDashboard();}
function updateCounts(){let total=0,filled=0; deptOrder.forEach(d=>{const n=(data[d]||[]).filter(x=>(x.title||'').trim()||(x.details||[]).join('').trim()).length; total+=n;if(n)filled++;}); document.getElementById('deptCount').textContent=((data[current]||[]).length)+'건'; document.getElementById('totalCount').textContent=total+'건'; document.getElementById('filledCount').textContent=filled+'개';}
function esc(s){return String(s||'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
function formatBytes(n){if(!n)return '0B'; if(n<1024)return n+'B'; if(n<1048576)return (n/1024).toFixed(1)+'KB'; return (n/1048576).toFixed(1)+'MB';}
async function uploadCurrentDeptFile(){
  const input=document.getElementById('deptFile'); const result=document.getElementById('result');
  if(!input.files || !input.files[0]){alert('업로드할 파일을 선택하세요.');return;}
  const file=input.files[0]; if(file.size>20*1024*1024){alert('20MB 이하 파일만 업로드할 수 있습니다.');return;}
  result.textContent=current+' 자료 업로드 중...';
  const dataUrl=await new Promise((resolve,reject)=>{const reader=new FileReader(); reader.onload=()=>resolve(reader.result); reader.onerror=reject; reader.readAsDataURL(file);});
  const r=await fetch('/api/upload-json',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:currentSession,department:current,filename:file.name,content_type:file.type||'application/octet-stream',data_url:dataUrl})});
  const j=await r.json(); if(!j.ok){result.textContent='업로드 실패: '+(j.detail||'오류');return;}
  uploadStatus=j.status; renderUploadDashboard(); renderNav(); renderDeptUploadBox(); input.value=''; result.textContent=current+' 자료 업로드 완료';
}
async function resetAllData(){
  if(!confirm('현재 세션의 입력 내용, 업로드 현황, 저장된 업로드 파일을 모두 빈 상태로 비울까요?')) return;
  const r=await fetch('/api/reset?session_id='+encodeURIComponent(currentSession),{method:'POST'}); const j=await r.json();
  if(j.ok){uploadStatus=j.status; data=j.departments||{}; deptOrder.forEach(d=>{data[d]=[]}); renderUploadDashboard(); renderNav(); renderDept(); document.getElementById('result').textContent='데이터를 빈 상태로 초기화했습니다.';}
}
async function generate(){const result=document.getElementById('result'); result.textContent='HWPX 생성 중...'; const payload={session_id:currentSession,week_title:document.getElementById('week').value,meeting_date:document.getElementById('meeting').value,writer:document.getElementById('writer').value,departments:data}; const r=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); const j=await r.json(); if(!j.ok){result.textContent='생성 실패';return} result.innerHTML=`생성 완료<br><a href="${j.hwpx}" download="${esc(j.filename||'weekly_report.hwpx')}">HWPX 결과물 내려받기</a><br><small>${j.filename||''}</small><br><small>${j.note}</small>`;}
renderSessions(); loadSeed(); loadUploadStatus();
</script>
</body></html>'''
