---
title: AWS S3 & S3-compatible storage
description: Storing files in AWS S3, MinIO, Cloudflare R2 and other S3-compatible services.
---

# AWS S3 and S3-compatible storage

The built-in `s3` adapter keeps a source in a bucket (optionally under a key prefix) through boto3. It needs the `s3` extra: `pip install "jodit-python[s3]"` (or `[all]`); without it requests to S3 sources answer `501`, while other sources keep working.

## Quick start

```json
--8<-- "examples/config/s3.json"
```

```bash
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... jcpy
```

Or with Docker:

```bash
docker run --rm -p 8081:8081 \
  -e CONFIG_FILE=/app/config.json -v $(pwd)/s3.json:/app/config.json:ro \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
  w2fb/jodit-python
```

## Options

All options live under `sources.<name>.s3`.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `bucket` | `string` | required | Bucket name |
| `region` | `string` | `us-east-1` | AWS region; S3-compatible services usually accept the default |
| `endpoint` | `string` | AWS | Endpoint URL of an S3-compatible service |
| `forcePathStyle` | `boolean` | service default | `endpoint/bucket/key` URLs; MinIO and some self-hosted services need `true` |
| `prefix` | `string` | `""` | Key prefix acting as the source root, e.g. `uploads/site-a` |
| `credentials` | `object` | AWS default chain | `accessKeyId`, `secretAccessKey`, optional `sessionToken` |
| `publicBaseUrl` | `string` | bucket URL | Base of `S3StorageAdapter.public_url()`; the connector's answers use the source `baseurl` |

`baseurl` of the source is what file paths in answers are relative to: the public URL of the prefix, ending with `/`.

## Credentials

Without `credentials` boto3 looks in the standard places:

1. `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (and `AWS_SESSION_TOKEN`)
2. the shared files `~/.aws/credentials` / `~/.aws/config` and `AWS_PROFILE`
3. the instance, task or pod role (EC2, ECS, EKS/IRSA)

This keeps secrets out of configuration files. Use `credentials` when one connector serves buckets with different keys; the values can come from your secret store through a [dynamic source](dynamic-sources.md) instead of a file.

## S3-compatible services

| Service | `endpoint` | `forcePathStyle` | `region` |
|---|---|---|---|
| MinIO | `http://minio:9000` | `true` | any |
| Cloudflare R2 | `https://<account-id>.r2.cloudflarestorage.com` | `true` | `auto` |
| Yandex Object Storage | `https://storage.yandexcloud.net` | `false` | `ru-central1` |
| DigitalOcean Spaces | `https://<region>.digitaloceanspaces.com` | `false` | the space region |
| Backblaze B2 | `https://s3.<region>.backblazeb2.com` | `false` | the bucket region |
| Wasabi | `https://s3.<region>.wasabisys.com` | `false` | the bucket region |

MinIO next to the connector in Docker Compose:

```json
{
  "sources": {
    "files": {
      "title": "Files",
      "baseurl": "http://localhost:9000/jodit/files/",
      "storageAdapter": "s3",
      "s3": {
        "bucket": "jodit",
        "endpoint": "http://minio:9000",
        "forcePathStyle": true,
        "prefix": "files",
        "credentials": {"accessKeyId": "minioadmin", "secretAccessKey": "minioadmin"}
      }
    }
  }
}
```

The connector talks to MinIO at `minio:9000` inside the network; the browser loads files from `localhost:9000` (`baseurl`).

## Serving the files

The connector never streams files to the browser: answers contain paths and the editor loads `baseurl + path`. The objects under the prefix must be readable by browsers.

**Public read on the prefix**, with a bucket policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "PublicReadForJoditUploads",
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::my-bucket/media/*"
  }]
}
```

On AWS this also needs "Block public access" relaxed for bucket policies (`BlockPublicPolicy`, `RestrictPublicBuckets`).

**A CDN in front of the bucket** (CloudFront with origin access control, or your provider's CDN): `baseurl` points at the CDN and the bucket stays private.

The adapter never sets object ACLs; buckets created since April 2023 have ACLs disabled, and access goes through the bucket policy.

## IAM policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::my-bucket",
      "Condition": {"StringLike": {"s3:prefix": ["media/*", "media"]}}
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::my-bucket/media/*"
    }
  ]
}
```

`s3:PutObject` covers copies, which rename and move use.

## Bucket layout

S3 has keys, not folders; the adapter follows the AWS console convention:

- `/photos/cat.jpg` in the browser is the object `<prefix>/photos/cat.jpg`.
- Creating a folder writes an empty `<prefix>/photos/` object. Folders that exist only because objects sit under them are listed too.
- Thumbnails go to `<prefix>/photos/_thumbs/cat.jpg`, as on disk; the `_thumbs` folder is hidden from listings.
- Rename and move are copy plus delete; moving a folder copies every object under it.
- Removing a folder deletes every key under it, 1000 per request.

Objects uploaded by other tools appear when they are under the prefix and their extension is in `extensions`.

Thumbnails cost one `GetObject` and one `PutObject` per image on the first listing of a folder (at most `safeThumbsCountInOneTime` per request). Set `createThumb: false` on the source for large buckets or when a CDN resizes images.

## Limits

- `CopyObject` is limited to 5 GB, so larger objects cannot be renamed or moved. Uploads are multipart and have no such limit.
- Signed URLs are not generated: files must be readable through `baseurl`.
- `fileUploadRemote` downloads through the connector's memory, bounded by `maxUploadFileSize`.

## Troubleshooting

`AccessDenied` on listing
:   `s3:ListBucket` must be granted on the bucket ARN (not `bucket/*`) and the `s3:prefix` condition must match the prefix.

Files upload but do not show in the editor
:   Open `baseurl` + a file name in a browser. A `403` there means the bucket policy or the CDN is missing.

MinIO answers `NoSuchBucket` or `301`
:   Set `forcePathStyle: true`; otherwise boto3 addresses `bucket.minio:9000`, which does not resolve.

Wrong region
:   AWS answers `PermanentRedirect` naming the right region; set `region` to it.

Two sources on one bucket
:   Give them different prefixes, or each sees the other's `_thumbs` folder as data.
