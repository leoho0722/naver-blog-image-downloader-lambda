#!/bin/bash

# Update the Lambda function with the new Docker image

# Load environment variables from .env file

echo "Loading environment variables from .env file..."

if [ ! -f ".env" ]; then
    echo "Error: .env file not found in current directory"
    exit 1
fi

set -a
source .env
set +a

echo "Environment variables loaded successfully."

# Validate Lambda function configuration

echo "Validating Lambda function configuration..."

if [ -z "$AWS_LAMBDA_FUNCTION_NAME" ] || [ "$AWS_LAMBDA_FUNCTION_NAME" = "" ]; then
    echo "Error: AWS_LAMBDA_FUNCTION_NAME is empty or not set"
    exit 1
fi

if [ -z "$AWS_ECR_REPOSITORY_URI" ] || [ "$AWS_ECR_REPOSITORY_URI" = "" ]; then
    echo "Error: AWS_ECR_REPOSITORY_URI is empty or not set"
    exit 1
fi

if [ -z "$IMAGE_NAME" ] || [ "$IMAGE_NAME" = "" ]; then
    echo "Error: IMAGE_NAME is empty or not set"
    exit 1
fi

if [ -z "$IMAGE_TAG" ] || [ "$IMAGE_TAG" = "" ]; then
    echo "Error: IMAGE_TAG is empty or not set"
    exit 1
fi

if [ -z "$AWS_REGION" ] || [ "$AWS_REGION" = "" ]; then
    echo "Error: AWS_REGION is empty or not set"
    exit 1
fi

if [ -z "$AWS_ACCESS_KEY_ID" ] || [ "$AWS_ACCESS_KEY_ID" = "" ]; then
    echo "Error: AWS_ACCESS_KEY_ID is empty or not set"
    exit 1
fi

if [ -z "$AWS_SECRET_ACCESS_KEY" ] || [ "$AWS_SECRET_ACCESS_KEY" = "" ]; then
    echo "Error: AWS_SECRET_ACCESS_KEY is empty or not set"
    exit 1
fi

echo "Lambda function configuration validated successfully."

# Set IMAGE_URI
IMAGE_URI=$AWS_ECR_REPOSITORY_URI/$IMAGE_NAME:$IMAGE_TAG

echo "Configuring AWS CLI..."
aws configure set aws_access_key_id $AWS_ACCESS_KEY_ID
aws configure set aws_secret_access_key $AWS_SECRET_ACCESS_KEY
aws configure set default.region $AWS_REGION

echo "Updating Lambda function..."
echo "FUNCTION_NAME: $AWS_LAMBDA_FUNCTION_NAME"
echo "AWS_ECR_REPOSITORY_URI: $AWS_ECR_REPOSITORY_URI"
echo "IMAGE_NAME: $IMAGE_NAME"
echo "IMAGE_TAG: $IMAGE_TAG"
echo "IMAGE_URI: $IMAGE_URI"

# 更新 Lambda 函數
echo "Updating Lambda function code..."
aws lambda update-function-code \
    --function-name $AWS_LAMBDA_FUNCTION_NAME \
    --image-uri $IMAGE_URI \
    --no-cli-pager \
    --output json \
    --query '{FunctionName: FunctionName, LastUpdateStatus: LastUpdateStatus, CodeSize: CodeSize}' > /tmp/lambda-update-result.json

if [ $? -eq 0 ]; then
    echo "Lambda function code update initiated. Waiting for update to complete..."
    
    # 等待函數更新完成
    aws lambda wait function-updated \
        --function-name $AWS_LAMBDA_FUNCTION_NAME \
        --no-cli-pager
    
    if [ $? -eq 0 ]; then
        echo "Lambda function update completed. Verifying final status..."
        
        # 只顯示關鍵資訊
        aws lambda get-function \
            --function-name $AWS_LAMBDA_FUNCTION_NAME \
            --no-cli-pager \
            --output table \
            --query 'Configuration.{FunctionName: FunctionName, Runtime: PackageType, CodeSize: CodeSize, LastModified: LastModified, State: State, LastUpdateStatus: LastUpdateStatus}'
        
        echo "Successfully updated Lambda function."
    else
        echo "Error: Lambda function update timed out or failed"
        exit 1
    fi
else
    echo "Error: Failed to update Lambda function"
    exit 1
fi