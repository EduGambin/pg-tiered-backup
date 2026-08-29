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

    # TODO: En vez de descargar todos los objetos, se puede solicitar aquel
    # que tenga el nombre más reciente (dado que todos los backups se llaman)
    # backup_{timestamp}.dump. Esta mejora proporciona O(1) en búsqueda.
    paginator = s3.get_paginator("list_objects_v2")
    objects = []
    for page in paginator.paginate(Bucket=bucket_name):
        objects.extend(page.get("Contents", []))

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
    # Aunque en el finally haya la misma llamada, hay que mantener esta porque
    # si se mata al proceso, no se ejecuta el finally, así que mejor dejarlo.
    subprocess.run(
        cmd + ["-c", "DROP DATABASE IF EXISTS verify_scratch WITH (FORCE);"], env=env, check=False
    )
    subprocess.run(cmd + ["-c", "CREATE DATABASE verify_scratch;"], env=env, check=True)

    try:
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
        # TODO: en el paso 4 esto sasaldrá del manifest.
        expected = {
            "pgbench_accounts": 2000000,
            "pgbench_branches": 20,
            "pgbench_history": 0,
            "pgbench_tellers": 200,
        }

        print("\nVerification results:")
        print("-----------------------\n")
        mismatches = []
        for table, want in expected.items():
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
            got = int(result.stdout.strip())
            print(
                f"{table}: {got} (expected {want}) {'OK' if got == want else 'MISMATCH'}"
            )
            if got != want:
                mismatches.append(table)

        if mismatches:
            raise SystemExit(
                f"verify failed, row counts differ: {', '.join(mismatches)}"
            )

    finally:
        print("Dropping scratch database...")
        # Necesitamos check=False para que no salte una excepción dentro del finally.
        # Lo de WITH (FORCE) es para que no falle aunque hayan cosas abiertas aún.
        subprocess.run(
            cmd + ["-c", "DROP DATABASE IF EXISTS verify_scratch WITH (FORCE);"],
            env=env,
            check=False,
        )


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
