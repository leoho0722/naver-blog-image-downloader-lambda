import json
import os
import time
import uuid

import boto3
from botocore.exceptions import ClientError

from data_models import JobStatus

BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "naver-blog-download-jobs")
PREFIX = "jobs/"

s3 = boto3.client("s3")


def create_job(blog_url: str) -> str:
    """建立新任務，回傳 job_id"""
    job_id = str(uuid.uuid4())
    job_data = {
        "job_id": job_id,
        "status": JobStatus.PROCESSING,
        "blog_url": blog_url,
        "result": None,
        "created_at": int(time.time()),
    }
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=f"{PREFIX}{job_id}.json",
        Body=json.dumps(job_data),
        ContentType="application/json",
    )
    return job_id


def update_job(job_id: str, status: JobStatus, result: dict | None = None):
    """更新任務狀態與結果"""
    job = get_job(job_id)
    if job is None:
        return
    job["status"] = status
    job["updated_at"] = int(time.time())
    if result is not None:
        job["result"] = result
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=f"{PREFIX}{job_id}.json",
        Body=json.dumps(job),
        ContentType="application/json",
    )


def get_job(job_id: str) -> dict | None:
    """取得任務狀態"""
    try:
        resp = s3.get_object(Bucket=BUCKET_NAME, Key=f"{PREFIX}{job_id}.json")
        return json.loads(resp["Body"].read().decode("utf-8"))
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return None
        raise
