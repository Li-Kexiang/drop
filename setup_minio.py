from minio import Minio
import json

mc = Minio("127.0.0.1:9000", access_key="drop", secret_key="drop1234", secure=False)

if not mc.bucket_exists("drop"):
    mc.make_bucket("drop")
    print("✅ drop 桶已创建")

policy = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"AWS": ["*"]}, "Action": ["s3:GetObject"], "Resource": ["arn:aws:s3:::drop/*"]}]
}
mc.set_bucket_policy("drop", json.dumps(policy))
print("✅ MinIO 桶已公开")
