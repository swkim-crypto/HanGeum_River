import os
import base64
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
REPO_NAME = os.getenv("GH_REPO")
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

        # [보완] 파일명에 한글이 섞이지 않도록 영어/숫자로만 조합 (유니코드 에러 방지)
        file_content = await image.read()
        image_filename = f"photos/{date_str}_data.jpg"
        
        repo.create_file(
            path=image_filename,
            message=f"Upload photo via API",
            content=file_content,
            branch="main"
        )
        
        image_url = f"https://raw.githubusercontent.com/{REPO_NAME}/main/{image_filename}"

        # [보완] CSV 데이터를 다룰 때 인코딩 에러 방지 처리
        try:
            contents = repo.get_contents(CSV_PATH, ref="main")
            # 디코딩 시 ignore 옵션 추가로 유니코드 충돌 방지
            existing_data = base64.b64decode(contents.content).decode("utf-8", errors="ignore")
            sha = contents.sha
        except Exception:
            # 최초 생성 시 한글 헤더가 잘 인식되도록 설정
            existing_data = "조사일자,농수로ID,수로폭(m),수심(m),유속(m/s),위도,경도,사진링크\n"
            sha = None

        new_row = f"{now},{channel_id},{width},{depth},{velocity},{latitude},{longitude},{image_url}\n"
        updated_data = existing_data + new_row

        # [보완] GitHub 전송 전 바이트 변환 시 UTF-8 인코딩 명시
        if sha:
            repo.update_file(
                path=CSV_PATH, 
                message="Update data row", 
                content=updated_data.encode("utf-8"), # 강제 인코딩
                sha=sha, 
                branch="main"
            )
        else:
            repo.create_file(
                path=CSV_PATH, 
                message="Create data file", 
                content=updated_data.encode("utf-8"), # 강제 인코딩
                branch="main"
            )

        return {"status": "success", "message": "GitHub 동기화 완료!"}

    except Exception as e:
        # 에러 발생 시 구체적인 이유를 모바일 화면에 던져주도록 수정
        raise HTTPException(status_code=500, detail=f"서버 내부 에러: {str(e)}")