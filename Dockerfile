FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

# 設置環境變數
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV LAMBDA_TASK_ROOT=/var/task

# 設置工作目錄
WORKDIR ${LAMBDA_TASK_ROOT}

# 安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製主程式
COPY app.py ${LAMBDA_TASK_ROOT}/
COPY helper.py ${LAMBDA_TASK_ROOT}/
COPY data_models.py ${LAMBDA_TASK_ROOT}/
COPY response_builder.py ${LAMBDA_TASK_ROOT}/

# 設置工作目錄權限
RUN chmod -R 777 /ms-playwright

# Lambda 入口點
ENTRYPOINT [ "python", "-m", "awslambdaric" ]
CMD [ "app.lambda_handler" ]
