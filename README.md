# pg-tiered-backup

A backup service for PostgreSQL that writes dumps to S3-compatible object storage and then
restores them into a scratch database to prove they are readable. A backup is not a backup
until you have restored it, so the restore test is the point and the upload is the plumbing.

## What it does

`pgtb backup` dumps the database and uploads the archive to a bucket.

`pgtb verify` pulls the most recent backup down, restores it into a throwaway database,
checks the per-table row counts, and drops the scratch database whether or not it passed.

Objects age down through storage tiers on a retention policy, so recent backups stay hot
and old ones move to cold storage before they expire.

## Built with

Python with boto3 for the S3 API, `pg_dump` and `pg_restore` for the database side, MinIO as
the local object store, and Docker Compose to run Postgres and MinIO together.

## Status

Work in progress. `backup` and `verify` work end to end against the Compose stack. Streaming
uploads, manifests, lifecycle rules and scheduling are not there yet.
