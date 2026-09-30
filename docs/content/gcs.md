---
title: Google Cloud Storage
description: Keeping a source in a Google Cloud Storage bucket.
---

# Google Cloud Storage

The built-in `gcs` adapter keeps a source in a Cloud Storage bucket, optionally under a name prefix. It needs the `gcs` extra: `pip install "jodit-python[gcs]"` (or `[all]`). Without it, requests to GCS sources answer `501` and other sources keep working.

## Quick start

```json
--8<-- "examples/config/gcs.json"
```

Without `credentialsFile` the connector uses the Application Default Credentials: the service account of the Cloud Run service, GKE workload identity or VM it runs on, the key file named by `GOOGLE_APPLICATION_CREDENTIALS`, or your `gcloud auth application-default login` session on a workstation. Give that account the **Storage Object User** role on the bucket (or Storage Object Admin, when uploads replace files under an object retention policy).

## Options

All options live under `sources.<name>.gcs`.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `bucket` | `string` | required | Bucket name |
| `project` | `string` | from the credentials | Project of the client (billing for requester-pays buckets) |
| `credentialsFile` | `string` | none | Path to a service account key (JSON) |
| `anonymous` | `boolean` | `false` | No credentials: for emulators and public buckets |
| `endpoint` | `string` | Google | API endpoint, e.g. an emulator at `http://localhost:4443` |
| `prefix` | `string` | `""` | Name prefix acting as the source root, e.g. `uploads/site-a` |
| `publicBaseUrl` | `string` | `https://storage.googleapis.com/<bucket>` | Base of `GcsStorageAdapter.public_url()`; the connector's answers use the source `baseurl` |
| `timeout` | `number` | `60` | Seconds per request |
| `storageClass` | `string` | bucket default | `STANDARD`, `NEARLINE`, `COLDLINE` or `ARCHIVE` for uploaded and copied files |
| `cacheControl` | `string` | none | `Cache-Control` header of uploaded files, e.g. `public, max-age=31536000` |

`credentialsFile` accepts service account keys only. Other credential configurations (workload identity federation, impersonation) work through `GOOGLE_APPLICATION_CREDENTIALS` instead. Service account keys are long-lived secrets: prefer an attached service account or workload identity where the connector runs on Google Cloud.

`NEARLINE`, `COLDLINE` and `ARCHIVE` objects stay readable, but reads and early deletes are billed extra; thumbnails read every image once.

`baseurl` of the source is what file paths in answers are relative to: the public URL of the prefix, ending with `/`.

## Serving the files

The editor loads files from `baseurl`, not through the connector. Two setups work:

- **Public read on the bucket.** Grant `allUsers` the Storage Object Viewer role (the bucket must use uniform bucket-level access and allow public access). `baseurl` is then `https://storage.googleapis.com/<bucket>/<prefix>/`.
- **A CDN in front of the bucket** (Cloud CDN with a backend bucket, or your provider's CDN). `baseurl` points at the CDN.

Signed URLs are not generated. They expire, and content that links to them would break (see [Private buckets](aws-s3.md#private-buckets), which applies here too).

## How files are handled

- **Uploads** go up in one request up to 8 MB and as resumable uploads in 8 MB parts above that. An object appears only when it is finalized, so readers never see a partial file, and a failed upload leaves the previous file in place.
- **Downloads** are streamed; at most 8 MB of an object is held in memory at a time.
- **Copies** are server-side rewrites, continued until done, so objects of any size can be copied, renamed and moved. The copy keeps the content type, `Cache-Control` and custom metadata, and takes `storageClass` when it is set.
- **Folders** are emulated as in the S3 adapter: an empty `folder/` object marks a created folder (the same objects the Cloud Console creates), and any object with a `/` in its name implies its folders. A file is never written over a folder of the same name, and a folder is never created below a file.
- **Deleting a folder** removes every object below it, 16 requests at a time.
- **Errors** name the HTTP status, the service reason and the storage path (`read /photos/a.jpg failed: 403 forbidden`), never the request URL or the bucket.

## Local development

Two emulators work with `anonymous: true` and `endpoint`:

- [fake-gcs-server](https://github.com/fsouza/fake-gcs-server) in Docker:

    ```bash
    docker run --rm -p 4443:4443 fsouza/fake-gcs-server -scheme http
    ```

    It drops objects whose names end with `/`, so empty folders disappear there.

- [gcp-storage-emulator](https://github.com/oittaa/gcp-storage-emulator), a Python package that keeps them:

    ```bash
    pip install gcp-storage-emulator
    gcp-storage-emulator start --port 4443 --default-bucket my-bucket
    ```

```json
"gcs": {"bucket": "my-bucket", "anonymous": true, "endpoint": "http://localhost:4443"}
```

## Troubleshooting

`403 forbidden`
:   The account lacks a role on the bucket. Assign **Storage Object User**; `storage.objects.list` is needed too, so a role on single objects is not enough.

`DefaultCredentialsError: Your default credentials were not found`
:   No attached service account, `GOOGLE_APPLICATION_CREDENTIALS` or `gcloud` session is available where the connector runs. Set `credentialsFile`, or attach a service account.

`404 notFound` on every request
:   The bucket name is wrong or the bucket is in another project the credentials cannot see.

Files upload but do not show in the editor
:   Open `baseurl` + a file name in a browser. `403` or an XML `AccessDenied` there means the bucket is not public: grant `allUsers` read access or put a CDN in front.
