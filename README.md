# Naver Blog Image Downloader Lambda

[繁體中文](docs/README_zh-TW.md) | [English](docs/README_en-US.md)

這是一個部署在 AWS Lambda 上的服務，用於從 Naver Blog 文章中提取高畫質圖片 URL。

## 功能說明

此服務使用 Playwright 自動化瀏覽器操作，從 Naver Blog 文章中擷取圖片：

1. 接收 Naver Blog 文章網址
2. 使用 Chromium 瀏覽器訪問該網址
3. 自動處理手機版與電腦版切換
4. 定位文章中的所有圖片
5. 逐一點擊圖片開啟彈窗，取得原始圖片 URL
6. 回傳所有圖片的 URL 清單及處理結果

## 專案架構

```text
.
├── app.py                  # Lambda 函數主程式，包含圖片下載邏輯
├── data_models.py          # 資料模型定義（DownloadResult）
├── helper.py               # 輔助函數（時間計算、除錯輸出）
├── response_builder.py     # HTTP Response Builder
├── requirements.txt        # Python 依賴套件
├── Dockerfile              # Dockerfile
├── Makefile                # 部署相關指令
├── .env                    # 環境變數設定檔（需自行建立）
└── scripts/
    ├── deploy-image.sh     # 建構並上傳 Docker 映像至 ECR
    └── update-function.sh  # 更新 Lambda 函數
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
- AWS ECR Repository (需自行建立)
- AWS Lambda Function（需使用容器映像類型）

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

### 請求格式

```json
{
  "blog_url": "https://blog.naver.com/username/post_id"
}
```

或透過 API Gateway：

```json
{
  "body": "{\"blog_url\": \"https://blog.naver.com/username/post_id\"}"
}
```

### 回應格式

```json
{
  "status_code": 200,
  "headers": {
    "Content-Type": "application/json"
  },
  "body": {
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

- `total_images`: 文章中找到的圖片總數
- `successful_downloads`: 成功取得 URL 的圖片數量
- `failure_downloads`: 處理失敗的圖片數量
- `image_urls`: 圖片 URL 清單
- `errors`: 錯誤訊息清單
- `elapsed_time`: 處理時間（秒）

## Lambda 函數設定建議

- **Memory**: 建議 2048 MB 以上
- **Timeout**: 建議 60 秒以上
- **Ephemeral storage**: 建議 512 MB 以上
- **Runtime**: Container Image

## 注意事項

1. 此服務僅擷取圖片 URL，不實際下載圖片檔案
2. 使用 Chromium 瀏覽器進行網頁操作，會消耗較多記憶體
3. 處理時間取決於文章中的圖片數量
4. 建議在 Lambda 函數中設定適當的 timeout 時間，避免執行逾時
