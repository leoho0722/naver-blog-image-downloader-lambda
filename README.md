# Naver Blog Image Downloader Lambda

[繁體中文](docs/README_zh-TW.md) | [English](docs/README_en-US.md)

這是一個部署在 AWS Lambda 上的服務，用於從 Naver Blog 文章中提取高畫質圖片 URL。採用**非同步 + Polling** 架構，避免 API Gateway 29 秒超時問題。

## 功能說明

此服務使用 Playwright 自動化瀏覽器操作，從 Naver Blog 文章中擷取圖片：

1. 提交下載請求，立即回傳 `job_id`（HTTP 202）
2. Lambda 於背景以 Chromium 瀏覽器訪問文章
3. 自動處理手機版與電腦版切換
4. 定位文章中的所有圖片，逐一點擊取得原始圖片 URL
5. 結果儲存至 S3，透過輪詢 API 查詢進度與結果

## 專案架構

```text
.
├── app.py                  # Lambda 入口點，路由 submit/status/async worker
├── data_models.py          # JobStatus enum、DownloadResult dataclass
├── job_store.py            # S3 任務狀態管理（create/get/update job）
├── helper.py               # 輔助函數（時間計算、除錯輸出）
├── response_builder.py     # HTTP Response Builder
├── requirements.txt        # Python 依賴套件（playwright、boto3、awslambdaric）
├── Dockerfile              # 容器映像定義（基於 playwright:v1.55.0-jammy）
├── Makefile                # 部署相關指令
├── pyproject.toml          # Ruff linter 設定
├── .env                    # 環境變數設定檔（需自行建立）
└── scripts/
    ├── deploy-image.sh     # 建構並上傳 Docker 映像至 ECR
    ├── update-function.sh  # 更新 Lambda 函數程式碼與設定
    └── setup-aws-resources.sh  # 首次 AWS 資源初始化（S3、IAM、Lambda）
```

## 環境變數設定

將 `.envExample` 改名為 `.env`，並設定以下環境變數：

```bash
# AWS 認證資訊
AWS_REGION=your_aws_region
AWS_ACCESS_KEY_ID=your_access_key_id
AWS_SECRET_ACCESS_KEY=your_secret_access_key

# AWS ECR 設定
AWS_ECR_REPOSITORY_URI=your_account_id.dkr.ecr.your_aws_region.amazonaws.com

# Lambda 函數設定
AWS_LAMBDA_FUNCTION_NAME=your_lambda_function_name

# S3 設定（非同步任務儲存）
S3_BUCKET_NAME=your_s3_bucket_name

# Docker 映像設定
IMAGE_NAME=your_lambda_container_image_name
IMAGE_TAG=latest
IMAGE_ARCH=linux/amd64
DOCKERFILE_PATH=Dockerfile

# 除錯模式（選填）
DEBUG_MODE=true
```

## 部署步驟

### 前置需求

- Docker
- AWS CLI
- AWS ECR Repository（需自行建立）
- AWS Lambda Function（需使用容器映像類型）
- AWS S3 Bucket（儲存非同步任務狀態，可透過 `scripts/setup-aws-resources.sh` 自動建立）

### 1. 建構並上傳 Docker 映像

```bash
make deploy-image
```

此指令會執行以下動作：

- 建構 Docker 映像
- 登入 AWS ECR
- 標記並上傳映像至 ECR
- 清理本地映像

### 2. 更新 Lambda 函數

```bash
make update-function
```

此指令會：

- 使用新的 Docker 映像更新 Lambda 函數
- 等待更新完成
- 顯示函數狀態

### 3. 一次完成部署

```bash
make deploy
```

此指令會依序執行 `deploy-image` 和 `update-function`。

## API 使用方式

### 1. 提交下載請求

```json
{
  "action": "download",
  "blog_url": "https://blog.naver.com/username/post_id"
}
```

回應（HTTP 202）：

```json
{
  "job_id": "uuid-string",
  "status": "processing"
}
```

### 2. 查詢任務狀態

```json
{
  "action": "status",
  "job_id": "uuid-string"
}
```

回應（處理中，HTTP 200）：

```json
{
  "job_id": "uuid-string",
  "status": "processing"
}
```

回應（完成，HTTP 200）：

```json
{
  "job_id": "uuid-string",
  "status": "completed",
  "result": {
    "total_images": 10,
    "successful_downloads": 10,
    "failure_downloads": 0,
    "image_urls": [
      "https://postfiles.pstatic.net/...",
      "https://postfiles.pstatic.net/..."
    ],
    "errors": [],
    "elapsed_time": 15.23
  }
}
```

### 回應欄位說明

- `job_id`: 任務 ID（用於輪詢查詢）
- `status`: 任務狀態（`processing` / `completed` / `failed`）
- `result.total_images`: 文章中找到的圖片總數
- `result.successful_downloads`: 成功取得 URL 的圖片數量
- `result.failure_downloads`: 處理失敗的圖片數量
- `result.image_urls`: 圖片 URL 清單
- `result.errors`: 錯誤訊息清單
- `result.elapsed_time`: 處理時間（秒）

## Lambda 函數設定建議

- **Memory**: 2048 MB
- **Timeout**: 120 秒
- **Ephemeral storage**: 建議 512 MB 以上
- **Runtime**: Container Image

## 注意事項

1. 此服務僅擷取圖片 URL，不實際下載圖片檔案
2. 使用 Chromium 瀏覽器進行網頁操作，會消耗較多記憶體
3. 處理時間取決於文章中的圖片數量
4. S3 中的任務記錄會在 1 天後自動過期清除
