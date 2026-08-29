# No hace falta cargar esta librería en producción, tan solo al desarrollar.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

import argparse
import datetime
import os
import subprocess
import boto3  # Boto3 es la librería oficial de AWS para Python.


def get_s3_client() -> "S3Client":
    # Estos dos valores se leen desde el .env para evitar literales
    aws_id = os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY")

    return boto3.client(
        "s3",
        endpoint_url="http://localhost:9000",
        aws_access_key_id=aws_id,  # Desde el environment, nada de literales.
        aws_secret_access_key=aws_secret,  # Desde el environment, nada de literales.
        region_name="us-east-1",
    )


def run_backup():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    local_file = "/tmp/test.dump"
    object_key = f"backup_{timestamp}.dump"
    bucket_name = "backups"

    env = os.environ.copy()
    cmd = [
        "pg_dump",
        "-h",
        "localhost",
        "-p",
        "5432",
        "-U",
        "postgres",
        "-d",
        "postgres",
        "-Fc",
        "-f",
        local_file,
    ]

    print("Generating backups...")
    subprocess.run(cmd, env=env, check=True)
    print(f"Dump created at {local_file}")

    s3 = get_s3_client()

    print("Uploading to MinIO...")
    s3.upload_file(local_file, bucket_name, object_key)
    print("Upload complete.")


def run_verify():
    s3 = get_s3_client()
    bucket_name = "backups"

    response = s3.list_objects_v2(Bucket=bucket_name)
    objects = response.get("Contents", [])
    if not objects:
        raise Exception("Bucket does not contain verification objects.")
    newest = max(objects, key=lambda x: x["LastModified"])
    newest_key = newest["Key"]

    local_file = "/tmp/verify.dump"
    print(f"Downloading most recent file {newest_key}")
    s3.download_file(bucket_name, newest_key, local_file)

    env = os.environ.copy()
    cmd = ["psql", "-h", "localhost", "-p", "5432", "-U", "postgres", "-d", "postgres"]

    print("Preparing the 'verify_scratch' database...")
    subprocess.run(
        cmd + ["-c", "DROP DATABASE IF EXISTS verify_scratch;"], env=env, check=True
    )
    subprocess.run(cmd + ["-c", "CREATE DATABASE verify_scratch;"], env=env, check=True)

    print("Restoring data with pg_restore...")
    subprocess.run(
        [
            "pg_restore",
            "-h",
            "localhost",
            "-p",
            "5432",
            "-U",
            "postgres",
            "-d",
            "verify_scratch",
            local_file,
        ],
        env=env,
        check=True,
    )

    tables = [
        "pgbench_accounts",
        "pgbench_branches",
        "pgbench_history",
        "pgbench_tellers",
    ]
    print("\nVerification results:")
    print("-----------------------\n")
    for table in tables:
        table_cmd = cmd[0:-2] + [
            "-d",
            "verify_scratch",
            "-t",
            "-A",
            "-c",
            f"SELECT count(*) FROM {table};",
        ]
        result = subprocess.run(
            table_cmd, env=env, check=True, capture_output=True, text=True
        )
        print(f"{table}: {result.stdout.strip()}")


def main():
    parser = argparse.ArgumentParser(description="PGTB - PostgreSQL Backup Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Registro del subcomando 'backup'
    subparsers.add_parser("backup", help="Creates backups of the DB")
    subparsers.add_parser(
        "verify", help="Verifies the existing DBs against last backups"
    )

    args = parser.parse_args()

    command_function = {}
    command_function["backup"] = run_backup
    command_function["verify"] = run_verify

    command_function[args.command]()


if __name__ == "__main__":
    main()
