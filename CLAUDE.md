# CLAUDE.md

## 專案概述

Naver Blog 圖片下載器，部署於 AWS Lambda（容器映像模式）。透過 Playwright 操控 Chromium 瀏覽器，從 Naver Blog 文章中擷取所有原始圖片 URL。

## 技術棧

- Python 3 + Playwright 1.55.0（Chromium headless）
- AWS Lambda（Container Image runtime）、AWS ECR
- Docker（基礎映像：`mcr.microsoft.com/playwright/python:v1.55.0-jammy`）

## 程式結構

- `app.py` — Lambda 入口點 `lambda_handler` 及圖片擷取邏輯 `download_images_from_naver_blog`
- `data_models.py` — `DownloadResult` dataclass
- `helper.py` — 工具函式（debug 輸出、時間計算）
- `response_builder.py` — HTTP 回應格式建構
- `Dockerfile` — 容器映像定義
- `scripts/deploy-image.sh` — 建構並推送 Docker 映像至 ECR
- `scripts/update-function.sh` — 更新 Lambda 函數程式碼

## 核心流程

1. 接收 `blog_url` 參數（支援直接傳入或 API Gateway `body` 格式）
2. Playwright 啟動 Chromium，訪問 Naver Blog 文章
3. 若為手機版自動切換至電腦版
4. 進入 `mainFrame` iframe，定位所有 `img.se-image-resource.egjs-visible` 圖片
5. 逐一點擊圖片開啟彈窗，從 `div.cpv__img_wrap img.cpv__img` 取得原圖 URL
6. 按檔名編號遞增排序後回傳結果

## 部署指令

```bash
make deploy-image    # 建構映像 → 推送至 ECR
make update-function # 更新 Lambda 函數
make deploy          # 以上兩步合一
```

## 環境變數

透過 `.env` 設定（參考 `.envExample`）。必要變數：

- `IMAGE_NAME`, `IMAGE_TAG`, `IMAGE_ARCH`, `DOCKERFILE_PATH`（Docker 建構）
- `AWS_REGION`, `AWS_ECR_REPOSITORY_URI`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`（AWS）
- `AWS_LAMBDA_FUNCTION_NAME`（Lambda）
- `DEBUG_MODE`（選填，啟用 debug 輸出）

## CI/CD（GitHub Actions）

- **CI**（`.github/workflows/ci.yml`）：所有分支 push 及 PR 到 main 時觸發，執行 Ruff lint + format 檢查
- **CD**（`.github/workflows/cd.yml`）：push 到 main 時觸發，依序執行：
  1. 建構 Docker 映像並推送至 ECR
  2. 更新 AWS Lambda 函數
  3. 建立 git tag（`vYYMMDD.RUN_NUMBER`）
  4. 透過 GitHub Models API（Claude Sonnet 4.6）生成正體中文 Release Notes
  5. 發布 GitHub Release
- **GitHub Secrets**（需手動設定）：`AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY`、`AWS_REGION`、`AWS_ECR_REPOSITORY_URI`、`AWS_LAMBDA_FUNCTION_NAME`
- **Linter**：Ruff，設定於 `pyproject.toml`

## 開發慣例

- Commit 訊息使用正體中文撰寫，遵循 Conventional Commits 風格：`<type>: <描述>`
  - 常用 type：`feat`（新功能）、`fix`（修正）、`refactor`（重構）、`docs`（文件）、`chore`（雜項）、`ci`（CI/CD）、`test`（測試）
  - 範例：`fix: 修正 image_urls 排序問題，改為遞增排序`
- 程式碼註解與日誌使用正體中文
