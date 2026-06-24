import os
import base64
import time
import unicodedata
from datetime import datetime
from typing import List
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

# 라오스 현장기록 (유속측정과 분리된 별도 데이터셋)
LAOS_CSV    = "laos.csv"
LAOS_HEADER = "기록시각,지점명,메모,위도,경도,방위각,사진링크\n"

def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text)


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

# 조회(읽기)는 더 이상 서버를 거치지 않는다.
# view.html이 GitHub Contents API로 data.csv를 직접 읽고, 사진 갤러리는
# photos/ 폴더 목록에서 파일명(<시각>_<농수로ID>.jpg)으로 만든다.
# → 서버 콜드스타트와 무관하게 항상 즉시 반영, 구조도 단순화.

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
    images:     List[UploadFile] = File(default=[]),
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

        # 사진 업로드 (여러 장 가능). URL들을 ';'로 묶어 data.csv 사진링크에 기록.
        safe_id = "".join(c for c in channel_id if c.isalnum() or c in "-_")
        urls = []
        for idx, img in enumerate(images or []):
            if not img or not getattr(img, "filename", ""):
                continue
            image_filename = f"photos/{date_str}{idx:02d}_{safe_id}.jpg"
            file_content   = await img.read()
            repo.create_file(path=image_filename, message=f"Upload photo: {safe_id} [skip render]", content=file_content, branch="main")
            urls.append(f"https://raw.githubusercontent.com/{REPO_NAME}/main/{image_filename}")
        image_url = ";".join(urls)

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


@app.post("/upload_laos")
async def upload_laos(
    title:     str        = Form(""),
    memo:      str        = Form(""),
    latitude:  str        = Form("0"),
    longitude: str        = Form("0"),
    heading:   str        = Form("0"),
    images:    List[UploadFile] = File(default=[])
):
    """라오스 현장기록: 사진(복수, 선택)·메모·위치를 laos.csv에 기록.
    사진이 없어도 위치/메모만으로 전송 가능. laos_photos/ 폴더에 저장."""
    try:
        g    = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        now      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_str = datetime.now().strftime("%Y%m%d%H%M%S")

        # 사진 업로드 (여러 장 가능, 없어도 됨)
        urls = []
        for idx, img in enumerate(images or []):
            if not img or not getattr(img, "filename", ""):
                continue
            image_filename = f"laos_photos/{date_str}{idx:02d}.jpg"
            file_content   = await img.read()
            repo.create_file(path=image_filename, message="Upload laos photo [skip render]", content=file_content, branch="main")
            urls.append(f"https://raw.githubusercontent.com/{REPO_NAME}/main/{image_filename}")
        image_url = ";".join(urls)

        # CSV 읽기 (헤더 손상 시 자가복구)
        existing_str, sha = read_csv_clean(repo, LAOS_CSV, LAOS_HEADER)

        title_safe = normalize(title).replace(",", " ").replace("\n", " ").strip()
        memo_safe  = normalize(memo).replace(",", ";").replace("\n", " ")
        try:
            heading_val = f"{float(heading):.0f}"
        except (TypeError, ValueError):
            heading_val = "0"

        new_row     = f"{now},{title_safe},{memo_safe},{latitude},{longitude},{heading_val},{image_url}\n"
        updated_str = existing_str + new_row

        if sha:
            repo.update_file(LAOS_CSV, "Update laos row [skip render]", updated_str, sha, branch="main")
        else:
            repo.create_file(LAOS_CSV, "Create laos file [skip render]", updated_str, branch="main")

        return {"status": "success", "message": "라오스 현장기록 전송 완료!", "row": new_row.strip()}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서버 에러: {str(e)}")
