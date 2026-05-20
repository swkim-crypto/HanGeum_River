import os
import base64
import unicodedata
from datetime import datetime
from fastapi import FastAPI, Form, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from github import Github

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GITHUB_TOKEN = os.getenv("GH_TOKEN")
REPO_NAME    = os.getenv("GH_REPO")
CSV_PATH     = "data.csv"

# BOM 포함 헤더 — 유속1,2,3 / 평균유속 / 높이 / 메모 추가
CSV_HEADER = "\ufeff조사일자,농수로ID,수로폭(m),수심(m),높이(m),유속1(m/s),유속2(m/s),유속3(m/s),평균유속(m/s),특이사항,위도,경도,사진링크\n"

def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text)

@app.get("/")
def root():
    return {"status": "ok", "message": "HanGeum River API is running"}

@app.post("/upload")
async def upload_data(
    channel_id: str        = Form(...),
    width:      float      = Form(...),
    depth:      float      = Form(...),
    height:     float      = Form(0.0),
    v1:         float      = Form(0.0),
    v2:         float      = Form(0.0),
    v3:         float      = Form(0.0),
    velocity:   float      = Form(...),   # 평균유속 (프론트에서 계산)
    memo:       str        = Form(""),
    latitude:   str        = Form(...),
    longitude:  str        = Form(...),
    image:      UploadFile = File(...)
):
    try:
        g    = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)

        now      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_str = datetime.now().strftime("%Y%m%d%H%M%S")

        # ── 사진 업로드 ──────────────────────────────────────────────────
        safe_id        = "".join(c for c in channel_id if c.isalnum() or c in "-_")
        image_filename = f"photos/{date_str}_{safe_id}.jpg"
        file_content   = await image.read()
        repo.create_file(
            path=image_filename, message=f"Upload photo: {safe_id}",
            content=file_content, branch="main"
        )
        image_url = f"https://raw.githubusercontent.com/{REPO_NAME}/main/{image_filename}"

        # ── CSV 읽기 ─────────────────────────────────────────────────────
        try:
            contents     = repo.get_contents(CSV_PATH, ref="main")
            raw_bytes    = base64.b64decode(contents.content)
            existing_str = raw_bytes.decode("utf-8-sig", errors="ignore")
            existing_str = normalize(existing_str)
            sha          = contents.sha
        except Exception:
            existing_str = CSV_HEADER
            sha          = None

        # ── 새 행: 메모의 쉼표를 세미콜론으로 치환(CSV 파싱 오류 방지) ──
        memo_safe = normalize(memo).replace(",", ";").replace("\n", " ")
        new_row = (
            f"{now},{normalize(channel_id)},"
            f"{width:.3f},{depth:.3f},{height:.3f},"
            f"{v1:.3f},{v2:.3f},{v3:.3f},{velocity:.3f},"
            f"{memo_safe},{latitude},{longitude},{image_url}\n"
        )
        updated_str  = existing_str + new_row
        updated_b64  = base64.b64encode(updated_str.encode("utf-8-sig")).decode()

        if sha:
            repo.update_file(CSV_PATH, "Update data row", updated_b64, sha, branch="main")
        else:
            repo.create_file(CSV_PATH, "Create data file", updated_b64, branch="main")

        return {"status": "success", "message": "데이터 전송 완료!", "row": new_row.strip()}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 에러: {str(e)}")
