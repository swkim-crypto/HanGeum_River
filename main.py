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

# UTF-8 BOM 헤더 — 엑셀이 인코딩을 자동 인식하여 한글 깨짐 없이 열림
CSV_HEADER = "\ufeff조사일자,농수로ID,수로폭(m),수심(m),유속(m/s),위도,경도,사진링크\n"

def normalize(text: str) -> str:
    """macOS/iOS NFC ↔ 윈도우 NFD 자모 분리 문제를 NFC로 통일"""
    return unicodedata.normalize("NFC", text)

@app.get("/")
def root():
    return {"status": "ok", "message": "HanGeum River API is running"}

@app.post("/upload")
async def upload_data(
    channel_id: str       = Form(...),
    width:      float     = Form(...),
    depth:      float     = Form(...),
    velocity:   float     = Form(...),
    latitude:   str       = Form(...),
    longitude:  str       = Form(...),
    image:      UploadFile = File(...)
):
    try:
        g    = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)

        now      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_str = datetime.now().strftime("%Y%m%d%H%M%S")

        # ── 1. 사진 업로드 ─────────────────────────────────────────────────
        # 파일명: 날짜시간_수로ID.jpg  (한글 제거, 영숫자+하이픈만 허용)
        safe_id = "".join(c for c in channel_id if c.isalnum() or c in "-_")
        image_filename = f"photos/{date_str}_{safe_id}.jpg"

        file_content = await image.read()
        repo.create_file(
            path    = image_filename,
            message = f"Upload photo: {safe_id} {date_str}",
            content = file_content,   # bytes → PyGitHub가 base64 처리
            branch  = "main"
        )
        image_url = f"https://raw.githubusercontent.com/{REPO_NAME}/main/{image_filename}"

        # ── 2. CSV 읽기 ────────────────────────────────────────────────────
        try:
            contents = repo.get_contents(CSV_PATH, ref="main")
            raw_bytes    = base64.b64decode(contents.content)
            existing_str = raw_bytes.decode("utf-8-sig", errors="ignore")  # BOM 자동 제거 후 읽기
            existing_str = normalize(existing_str)
            sha          = contents.sha
        except Exception:
            existing_str = CSV_HEADER   # 파일 없으면 헤더부터 생성
            sha          = None

        # ── 3. 새 행 추가 ──────────────────────────────────────────────────
        channel_id_nfc = normalize(channel_id)
        new_row = (
            f"{now},{channel_id_nfc},"
            f"{width:.3f},{depth:.3f},{velocity:.3f},"
            f"{latitude},{longitude},{image_url}\n"
        )
        updated_str = existing_str + new_row

        # ── 4. CSV 저장 — PyGitHub에 str 전달 (내부에서 base64 인코딩) ───
        # BOM 포함 UTF-8로 인코딩하여 base64 문자열로 직접 전달
        updated_bytes  = updated_str.encode("utf-8-sig")          # BOM 포함
        updated_b64    = base64.b64encode(updated_bytes).decode()  # str

        file_msg = "Update data row"
        if sha:
            repo.update_file(
                path    = CSV_PATH,
                message = file_msg,
                content = updated_b64,
                sha     = sha,
                branch  = "main"
            )
        else:
            repo.create_file(
                path    = CSV_PATH,
                message = "Create data file",
                content = updated_b64,
                branch  = "main"
            )

        return {
            "status":  "success",
            "message": "데이터 전송 완료!",
            "row":     new_row.strip()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 에러: {str(e)}")
