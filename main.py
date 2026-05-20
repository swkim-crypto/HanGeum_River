# requirements.txt에 다음을 추가하세요: fastapi, uvicorn, PyGithub, python-multipart
import os
import base64
from datetime import datetime
from fastapi import FastAPI, Form, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from github import Github

app = FastAPI()

# 현장 앱과의 통신을 위한 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Render 환경변수에서 설정할 GitHub 정보
GITHUB_TOKEN = os.getenv("GH_TOKEN")        # GitHub 개인 액세스 토큰
REPO_NAME = os.getenv("GH_REPO")          # 계정명/저장소명 (예: cubicinc/river-data)
CSV_PATH = "data.csv"

@app.post("/upload")
async def upload_data(
    channel_id: str = Form(...),
    width: float = Form(...),
    depth: float = Form(...),
    velocity: float = Form(...),
    latitude: str = Form(...),
    longitude: str = Form(...),
    image: UploadFile = File(...)
):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. 사진 파일 처리 (파일명에 농수로ID, 날짜, 좌표를 내장)
        file_content = await image.read()
        image_filename = f"photos/{channel_id}_{date_str}.jpg"
        
        # GitHub에 사진 업로드 (신규 생성)
        repo.create_file(
            path=image_filename,
            message=f"📸 사진 업로드: {channel_id}",
            content=file_content,
            branch="main"
        )
        
        # GitHub 이미지 주소 생성 (Raw 이미지 주소)
        image_url = f"https://raw.githubusercontent.com/{REPO_NAME}/main/{image_filename}"

        # 2. CSV 데이터 업데이트
        try:
            # 기존 data.csv 파일이 있으면 가져옴
            contents = repo.get_contents(CSV_PATH, ref="main")
            existing_data = base64.b64decode(contents.content).decode("utf-8")
            sha = contents.sha
        except Exception:
            # 파일이 없으면 헤더 생성
            existing_data = "조사일자,농수로ID,수로폭(m),수심(m),유속(m/s),위도,경도,사진링크\n"
            sha = None

        # 새 행 추가
        new_row = f"{now},{channel_id},{width},{depth},{velocity},{latitude},{longitude},{image_url}\n"
        updated_data = existing_data + new_row

        # GitHub에 CSV 업데이트
        if sha:
            repo.update_file(CSV_PATH, f"📝 데이터 추가: {channel_id}", updated_data, sha, branch="main")
        else:
            repo.create_file(CSV_PATH, f"✨ 최초 데이터 파일 생성", updated_data, branch="main")

        return {"status": "success", "message": "GitHub 동기화 완료!"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))