import os
import base64
import time
import unicodedata
from datetime import datetime
from fastapi import FastAPI, Form, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from github import Github

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

GITHUB_TOKEN = os.getenv("GH_TOKEN")
REPO_NAME    = os.getenv("GH_REPO")
CSV_PATH     = "data.csv"

# 촬영방위각 + 사용장비/rpm/n 컬럼 추가
CSV_HEADER = "조사일자,농수로ID,수로폭(m),수심(m),높이(m),유속1(m/s),유속2(m/s),유속3(m/s),평균유속(m/s),촬영방위각(°),특이사항,위도,경도,사진링크,장비,rpm1,rpm2,rpm3,n1,n2,n3\n"

def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text)

PHOTOS_PATH   = "photos.csv"
PHOTOS_HEADER = "촬영시각,농수로ID,위도,경도,사진링크\n"

def read_csv_clean(repo, path, header):
    """기존 CSV를 읽되, 내용이 인코딩 손상됐거나 헤더가 비표준/빈 줄이면
    정상 헤더로 자가복구하고 실제 데이터 행만 보존한다. (text, sha) 반환."""
    try:
        contents = repo.get_contents(path, ref="main")
    except Exception:
        return header, None  # 파일 없음 → 새로 생성
    try:
        raw  = base64.b64decode(contents.content)
        text = normalize(raw.decode("utf-8-sig"))  # 손상 시 UnicodeDecodeError
    except Exception:
        return header, contents.sha  # 내용 손상 → 헤더만 남기고 초기화(기존 파일 교체)
    lines = text.split("\n")
    first = lines[0].strip() if lines else ""
    if first != header.strip():
        body = [l for l in lines[1:] if l.strip(", \t\r")]  # 빈 ',,,,' 줄 제거
        text = header + ("\n".join(body) + "\n" if body else "")
    return text, contents.sha

@app.get("/")
def root():
    return {"status": "ok", "message": "HanGeum River API is running"}

# ── 조회용: 서버가 인증 호출로 GitHub에서 직접 읽어 내려줌 ──────────────
# (Contents API 60회/시간 한도 회피 + raw CDN 5분 캐시 회피 + Pages 배포와 무관)
def _read_repo_file(path: str, header: str) -> str:
    try:
        g        = Github(GITHUB_TOKEN)
        repo     = g.get_repo(REPO_NAME)
        contents = repo.get_contents(path, ref="main")
        return normalize(base64.b64decode(contents.content).decode("utf-8-sig", errors="ignore"))
    except Exception:
        return header

@app.get("/data", response_class=PlainTextResponse)
def get_data():
    return _read_repo_file(CSV_PATH, CSV_HEADER)

@app.get("/photos", response_class=PlainTextResponse)
def get_photos():
    return _read_repo_file(PHOTOS_PATH, PHOTOS_HEADER)

@app.post("/upload")
async def upload_data(
    channel_id: str        = Form(""),
    width:      float      = Form(0.0),
    depth:      float      = Form(0.0),
    height:     float      = Form(0.0),
    v1:         float      = Form(0.0),
    v2:         float      = Form(0.0),
    v3:         float      = Form(0.0),
    velocity:   float      = Form(0.0),
    heading:    float      = Form(0.0),
    memo:       str        = Form(""),
    latitude:   str        = Form("0"),
    longitude:  str        = Form("0"),
    image:      UploadFile = File(None),
    device:     str        = Form(""),
    rpm1:       str        = Form(""),
    rpm2:       str        = Form(""),
    rpm3:       str        = Form(""),
    n1:         str        = Form(""),
    n2:         str        = Form(""),
    n3:         str        = Form("")
):
    try:
        g    = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        now      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_str = datetime.now().strftime("%Y%m%d%H%M%S")

        # 사진 업로드 (있을 때만)
        image_url = ""
        if image is not None and image.filename:
            safe_id        = "".join(c for c in channel_id if c.isalnum() or c in "-_")
            image_filename = f"photos/{date_str}_{safe_id}.jpg"
            file_content   = await image.read()
            repo.create_file(path=image_filename, message=f"Upload photo: {safe_id} [skip render]", content=file_content, branch="main")
            image_url = f"https://raw.githubusercontent.com/{REPO_NAME}/main/{image_filename}"

        # CSV 읽기 (헤더 손상 시 자가복구)
        existing_str, sha = read_csv_clean(repo, CSV_PATH, CSV_HEADER)

        memo_safe = normalize(memo).replace(",", ";").replace("\n", " ")

        # 사용장비/rpm/n 정리 (쉼표 제거)
        device_safe = normalize(device).replace(",", " ").strip()
        rpm1_s, rpm2_s, rpm3_s = (str(x).replace(",", "").strip() for x in (rpm1, rpm2, rpm3))
        n1_s,   n2_s,   n3_s   = (str(x).replace(",", "").strip() for x in (n1, n2, n3))

        new_row = (
            f"{now},{normalize(channel_id)},"
            f"{width:.3f},{depth:.3f},{height:.3f},"
            f"{v1:.3f},{v2:.3f},{v3:.3f},{velocity:.3f},"
            f"{heading:.0f},{memo_safe},{latitude},{longitude},{image_url},"
            f"{device_safe},{rpm1_s},{rpm2_s},{rpm3_s},{n1_s},{n2_s},{n3_s}\n"
        )
        updated_str = existing_str + new_row

        if sha:
            repo.update_file(CSV_PATH, "Update data row [skip render]", updated_str, sha, branch="main")
        else:
            repo.create_file(CSV_PATH, "Create data file [skip render]", updated_str, branch="main")

        return {"status": "success", "message": "데이터 전송 완료!", "row": new_row.strip()}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 에러: {str(e)}")


@app.post("/upload_photo")
async def upload_photo(
    channel_id: str        = Form(""),
    latitude:   str        = Form("0"),
    longitude:  str        = Form("0"),
    timestamp:  str        = Form(""),
    image:      UploadFile = File(...)
):
    """현장 사진 일괄 전송용. 사진은 repo에 저장하고 photos.csv에 ID로 기록."""
    try:
        g    = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        now      = normalize(timestamp) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_str = datetime.now().strftime("%Y%m%d%H%M%S%f")

        # 사진 저장 (파일명에 ID 포함)
        safe_id        = "".join(c for c in normalize(channel_id) if c.isalnum() or c in "-_")
        image_filename = f"photos/{date_str}_{safe_id}.jpg"
        file_content   = await image.read()
        repo.create_file(path=image_filename, message=f"Photo: {safe_id} [skip render]", content=file_content, branch="main")
        image_url = f"https://raw.githubusercontent.com/{REPO_NAME}/main/{image_filename}"

        # photos.csv 누적 (동시/지연 충돌 시 sha 재조회 후 재시도)
        new_row = f"{now},{normalize(channel_id)},{latitude},{longitude},{image_url}\n"
        last_err = None
        for attempt in range(5):
            try:
                existing_str, sha = read_csv_clean(repo, PHOTOS_PATH, PHOTOS_HEADER)
                if sha:
                    repo.update_file(PHOTOS_PATH, "Add photo row [skip render]", existing_str + new_row, sha, branch="main")
                else:
                    repo.create_file(PHOTOS_PATH, "Create photos file [skip render]", existing_str + new_row, branch="main")
                last_err = None
                break
            except Exception as ex:
                last_err = ex
                time.sleep(0.8)
        if last_err is not None:
            raise last_err

        return {"status": "success", "url": image_url}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"사진 전송 에러: {str(e)}")
