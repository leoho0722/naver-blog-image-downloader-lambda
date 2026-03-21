# Naver Blog Image Downloader Lambda

[繁體中文](README_zh-TW.md)

This is a service deployed on AWS Lambda that extracts high-quality image URLs from Naver Blog articles. It uses an **async + polling** architecture to avoid the API Gateway 29-second timeout issue.

## Features

This service uses Playwright to automate browser operations and extract images from Naver Blog articles:

1. Submit a download request and immediately receive a `job_id` (HTTP 202)
2. Lambda processes the article in the background using a Chromium browser
3. Automatically handles mobile and desktop version switching
4. Locates all images in the article and clicks each one to retrieve original image URLs
5. Results are stored in S3 and can be queried via a polling API

## Project Structure

```text
.
├── app.py                      # Lambda entry point, routes submit/status/async worker
├── data_models.py              # JobStatus enum, DownloadResult dataclass
├── job_store.py                # S3 job state management (create/get/update job)
├── helper.py                   # Helper functions (time calculation, debug output)
├── response_builder.py         # HTTP Response Builder
├── requirements.txt            # Python dependencies (playwright, boto3, awslambdaric)
├── Dockerfile                  # Container image definition (based on playwright:v1.55.0-jammy)
├── Makefile                    # Deployment commands
├── pyproject.toml              # Ruff linter configuration
├── .env                        # Environment variables configuration file (needs to be created)
└── scripts/    
    ├── deploy-image.sh         # Build and upload Docker image to ECR
    ├── update-function.sh      # Update Lambda function code and configuration
    └── setup-aws-resources.sh  # First-time AWS resource initialization (S3, IAM, Lambda)
```

## Environment Variables Configuration

Rename `.envExample` to `.env` and configure the following environment variables:

```bash
# AWS Credentials
AWS_REGION=your_aws_region
AWS_ACCESS_KEY_ID=your_access_key_id
AWS_SECRET_ACCESS_KEY=your_secret_access_key

# AWS ECR Configuration
AWS_ECR_REPOSITORY_URI=your_account_id.dkr.ecr.your_aws_region.amazonaws.com

# Lambda Function Configuration
AWS_LAMBDA_FUNCTION_NAME=your_lambda_function_name

# S3 Configuration (async job storage)
S3_BUCKET_NAME=your_s3_bucket_name

# Docker Image Configuration
IMAGE_NAME=your_lambda_container_image_name
IMAGE_TAG=latest
IMAGE_ARCH=linux/amd64
DOCKERFILE_PATH=Dockerfile

# Debug Mode (Optional)
DEBUG_MODE=true
```

## Deployment Steps

### Prerequisites

- Docker
- AWS CLI
- AWS ECR Repository (needs to be created manually)
- AWS Lambda Function (must use container image type)
- AWS S3 Bucket (stores async job state, can be created automatically via `scripts/setup-aws-resources.sh`)

### 1. Build and Upload Docker Image

```bash
make deploy-image
```

This command will:

- Build the Docker image
- Log in to AWS ECR
- Tag and upload the image to ECR
- Clean up local images

### 2. Update Lambda Function

```bash
make update-function
```

This command will:

- Update the Lambda function with the new Docker image
- Wait for the update to complete
- Display the function status

### 3. Complete Deployment in One Step

```bash
make deploy
```

This command will execute `deploy-image` and `update-function` sequentially.

## API Usage

### 1. Submit a Download Request

```json
{
  "action": "download",
  "blog_url": "https://blog.naver.com/username/post_id"
}
```

Response (HTTP 202):

```json
{
  "job_id": "uuid-string",
  "status": "processing"
}
```

### 2. Query Job Status

```json
{
  "action": "status",
  "job_id": "uuid-string"
}
```

Response (processing, HTTP 200):

```json
{
  "job_id": "uuid-string",
  "status": "processing"
}
```

Response (completed, HTTP 200):

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

### Response Fields

- `job_id`: Job ID (used for polling)
- `status`: Job status (`processing` / `completed` / `failed`)
- `result.total_images`: Total number of images found in the article
- `result.successful_downloads`: Number of images with URLs successfully retrieved
- `result.failure_downloads`: Number of images that failed to process
- `result.image_urls`: List of image URLs
- `result.errors`: List of error messages
- `result.elapsed_time`: Processing time (in seconds)

## Lambda Function Configuration Recommendations

- **Memory**: 2048 MB
- **Timeout**: 120 seconds
- **Ephemeral storage**: Recommended 512 MB or higher
- **Runtime**: Container Image

## Notes

1. This service only extracts image URLs and does not actually download image files
2. Uses a Chromium browser for web operations, which consumes more memory
3. Processing time depends on the number of images in the article
4. Job records in S3 are automatically expired and cleaned up after 1 day
