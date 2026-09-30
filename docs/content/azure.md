---
title: Azure Blob Storage
description: Keeping a source in an Azure Blob Storage container.
---

# Azure Blob Storage

The built-in `azure` adapter keeps a source in a Blob Storage container, optionally under a name prefix. It needs the `azure` extra: `pip install "jodit-python[azure]"` (or `[all]`). Without it, requests to Azure sources answer `501` and other sources keep working.

## Quick start

```json
--8<-- "examples/config/azure.json"
```

With only `accountUrl` set, the connector signs in with the Azure default credential chain: a managed identity on Azure (App Service, Container Apps, AKS, VMs), the `AZURE_*` environment variables, or your `az login` session on a workstation. Give that identity the **Storage Blob Data Contributor** role on the container.

## Options

All options live under `sources.<name>.azure`.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `container` | `string` | required | Container name |
| `accountUrl` | `string` | none | `https://<account>.blob.core.windows.net`; set this or `connectionString` |
| `connectionString` | `string` | none | Connection string from the portal (Access keys); set this or `accountUrl` |
| `accountKey` | `string` | none | Account key, with `accountUrl` |
| `sasToken` | `string` | none | SAS token, with `accountUrl`; needs read, write, delete and list permissions |
| `prefix` | `string` | `""` | Name prefix acting as the source root, e.g. `uploads/site-a` |
| `publicBaseUrl` | `string` | container URL | Base of `AzureStorageAdapter.public_url()`; the connector's answers use the source `baseurl` |
| `connectTimeout` | `number` | `10` | Seconds to wait for a connection |
| `readTimeout` | `number` | `60` | Seconds to wait for data on an open connection |
| `maxAttempts` | `integer` | `3` | Attempts per request, first one included (with backoff) |
| `maxConcurrency` | `integer` | `4` | Parallel requests for one large upload (1–64) |
| `accessTier` | `string` | account default | `Hot`, `Cool` or `Cold` for uploaded and copied files |
| `cacheControl` | `string` | none | `Cache-Control` header of uploaded files, e.g. `public, max-age=31536000` |

Only one sign-in method applies: `connectionString`, `accountUrl` with `accountKey`, `accountUrl` with `sasToken`, or `accountUrl` alone (default credential chain). The `Archive` tier is not offered: archived blobs cannot be read, so previews and thumbnails would fail.

`baseurl` of the source is what file paths in answers are relative to: the public URL of the prefix, ending with `/`.

## Serving the files

The editor loads files from `baseurl`, not through the connector. Two setups work:

- **Anonymous read access** on the container (access level "Blob"), with "Allow Blob anonymous access" enabled on the account. `baseurl` is then `https://<account>.blob.core.windows.net/<container>/<prefix>/`.
- **A CDN in front of the container** (Azure Front Door with a private origin, or your provider's CDN). `baseurl` points at the CDN and the container stays private.

SAS links are not generated. They expire, and content that links to them would break (see [Private buckets](aws-s3.md#private-buckets), which applies here too).

## How files are handled

- **Uploads** are sent in 4 MB blocks (up to `maxConcurrency` at once) and become visible only when the blob is committed, so readers never see a partial file. A failed upload leaves the previous file in place.
- **Downloads** are streamed; at most 4 MB of a blob is held in memory at a time.
- **Copies** run on the service. When the service refuses to read the source with the connector's credential (`CannotVerifyCopySource`), the copy is streamed through the connector instead. Pending copies of large blobs are awaited.
- **Folders** are emulated as in the S3 adapter: an empty `folder/` blob marks a created folder, and any blob with a `/` in its name implies its folders. A file is never written over a folder of the same name, and a folder is never created below a file.
- **Deleting a folder** removes every blob below it, 256 per batch request, and fails when any blob could not be deleted. Emulator-style URLs with the account in the path on a host other than `localhost` or `127.0.0.1` (such as `http://azurite:10000/devstoreaccount1` in Docker Compose) are deleted blob by blob, because the SDK cannot batch them.
- **Errors** name the service error code and the storage path (`read /photos/a.jpg failed: 403 AuthorizationFailure`), never the account URL or a SAS token.

## Local development with Azurite

[Azurite](https://learn.microsoft.com/azure/storage/common/storage-use-azurite) emulates Blob Storage locally:

```bash
docker run --rm -p 10000:10000 mcr.microsoft.com/azure-storage/azurite \
  azurite-blob --blobHost 0.0.0.0
```

Create the container (for example with Azure Storage Explorer), then use the development connection string:

```json
"azure": {
  "container": "files",
  "connectionString": "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
}
```

The key is Azurite's published development key, not a secret.

## Troubleshooting

`403 AuthorizationPermissionMismatch`
:   The identity signs in but lacks a data role. Assign **Storage Blob Data Contributor** (not just Reader or Owner of the account); role changes take a few minutes to apply.

`403 AuthenticationFailed`
:   Wrong `accountKey`, an expired `sasToken`, or a clock far off on the server.

`DefaultAzureCredential failed to retrieve a token`
:   No managed identity, `AZURE_*` variables or `az login` session is available where the connector runs. Set `accountKey`, `sasToken` or `connectionString` instead, or assign a managed identity.

Files upload but do not show in the editor
:   Open `baseurl` + a file name in a browser. `404 ResourceNotFound` there, while the blob exists, means anonymous access is off: enable it or put a CDN in front.
