import os

import boto3
from botocore.exceptions import ClientError

client = boto3.client(
    "s3",
    endpoint_url="http://storage:8333",
    aws_access_key_id=os.environ["MINIO_ROOT_USER"],
    aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"],
    region_name="us-east-1",
)
try:
    client.create_bucket(Bucket="repovox-private")
except ClientError as exc:
    if exc.response["Error"]["Code"] not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
        raise
print("Private local bucket initialized; anonymous identity is absent.")
