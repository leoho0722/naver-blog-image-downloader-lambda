# Naver Blog Image Downloader Lambda

[繁體中文](README_zh-TW.md)

This is a service deployed on AWS Lambda that extracts high-quality image URLs from Naver Blog articles.

## Features

This service uses Playwright to automate browser operations and extract images from Naver Blog articles:

1. Receives a Naver Blog article URL
2. Visits the URL using a Chromium browser
3. Automatically handles mobile and desktop version switching
4. Locates all images in the article
5. Clicks on each image to open a popup and retrieves the original image URL
6. Returns a list of all image URLs and processing results

## Project Structure

```text
.
├── app.py                  # Lambda function main program with image download logic
├── data_models.py          # Data model definitions (DownloadResult)
├── helper.py               # Helper functions (time calculation, debug output)
├── response_builder.py     # HTTP Response Builder
├── requirements.txt        # Python dependencies
├── Dockerfile              # Dockerfile
├── Makefile                # Deployment commands
├── .env                    # Environment variables configuration file (needs to be created)
└── scripts/
    ├── deploy-image.sh     # Build and upload Docker image to ECR
    └── update-function.sh  # Update Lambda function
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

### Request Format

```json
{
  "blog_url": "https://blog.naver.com/username/post_id"
}
```

Or via API Gateway:

```json
{
  "body": "{\"blog_url\": \"https://blog.naver.com/username/post_id\"}"
}
```

### Response Format

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

### Response Fields

- `total_images`: Total number of images found in the article
- `successful_downloads`: Number of images with URLs successfully retrieved
- `failure_downloads`: Number of images that failed to process
- `image_urls`: List of image URLs
- `errors`: List of error messages
- `elapsed_time`: Processing time (in seconds)

## Lambda Function Configuration Recommendations

- **Memory**: Recommended 2048 MB or higher
- **Timeout**: Recommended 60 seconds or higher
- **Ephemeral storage**: Recommended 512 MB or higher
- **Runtime**: Container Image

## Notes

1. This service only extracts image URLs and does not actually download image files
2. Uses a Chromium browser for web operations, which consumes more memory
3. Processing time depends on the number of images in the article
4. It is recommended to set an appropriate timeout for the Lambda function to avoid execution timeouts
