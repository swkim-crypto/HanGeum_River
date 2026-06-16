import os
import base64
import time
import unicodedata
from datetime import datetime
from fastapi import FastAPI, Form, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

@app.get("/")
def root():
    return {"status": "ok", "message": "HanGeum River API is running"}

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
            repo.create_file(path=image_filename, message=f"Upload photo: {safe_id}", content=file_content, branch="main")
            image_url = f"https://raw.githubusercontent.com/{REPO_NAME}/main/{image_filename}"

        # CSV 읽기
        try:
            contents     = repo.get_contents(CSV_PATH, ref="main")
            raw_bytes    = base64.b64decode(contents.content)
            existing_str = raw_bytes.decode("utf-8-sig", errors="ignore")
            existing_str = normalize(existing_str)
            sha          = contents.sha
        except Exception:
            existing_str = CSV_HEADER
            sha          = None

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
            repo.update_file(CSV_PATH, "Update data row", updated_str, sha, branch="main")
        else:
            repo.create_file(CSV_PATH, "Create data file", updated_str, branch="main")

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
        repo.create_file(path=image_filename, message=f"Photo: {safe_id}", content=file_content, branch="main")
        image_url = f"https://raw.githubusercontent.com/{REPO_NAME}/main/{image_filename}"

        # photos.csv 누적 (동시/지연 충돌 시 sha 재조회 후 재시도)
        new_row = f"{now},{normalize(channel_id)},{latitude},{longitude},{image_url}\n"
        last_err = None
        for attempt in range(5):
            try:
                try:
                    contents     = repo.get_contents(PHOTOS_PATH, ref="main")
                    existing_str = normalize(base64.b64decode(contents.content).decode("utf-8-sig", errors="ignore"))
                    repo.update_file(PHOTOS_PATH, "Add photo row", existing_str + new_row, contents.sha, branch="main")
                except Exception:
                    # 파일이 없으면 생성
                    repo.create_file(PHOTOS_PATH, "Create photos file", PHOTOS_HEADER + new_row, branch="main")
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
