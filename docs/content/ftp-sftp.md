---
title: FTP & SFTP storage
description: Keeping a source on an FTP, FTPS or SFTP server.
---

# FTP and SFTP storage

Two built-in adapters keep a source in a directory on a file server:

- `ftp`: FTP and FTPS (explicit TLS). It uses the standard library, so it needs no extra.
- `sftp`: SFTP over SSH, through paramiko. It needs the `sftp` extra: `pip install "jodit-python[sftp]"` (or `[all]`). Without it, requests to SFTP sources answer `501` and other sources keep working.

The editor loads files from `baseurl`, not through the connector. Point `baseurl` at the web server that publishes the same directory, for example `https://www.example.com/uploads/` for `/public_html/uploads`.

## Quick start

=== "ftp.json"

    ```json
    --8<-- "examples/config/ftp.json"
    ```

=== "sftp.json"

    ```json
    --8<-- "examples/config/sftp.json"
    ```

Get the host key for `hostKey` from the server itself:

```bash
ssh-keyscan -t ed25519 files.example.com
```

Copy the whole line it prints (`files.example.com ssh-ed25519 AAAA...`) or just its `ssh-ed25519 AAAA...` part. Compare the fingerprint (`ssh-keygen -lf`) with the one your hosting provider publishes.

## FTP options

All options live under `sources.<name>.ftp`.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `host` | `string` | required | Server name or address |
| `port` | `integer` | `21` | Control connection port |
| `username` | `string` | `anonymous` | Login |
| `password` | `string` | `""` | Password |
| `directory` | `string` | login directory | Directory acting as the source root; absolute, or relative to the login directory |
| `tls` | `boolean` | `false` | Explicit FTPS (`AUTH TLS`): commands and data are encrypted |
| `verifyCertificate` | `boolean` | `true` | Check the server certificate and name with the system CAs; turn off only for self-signed certificates on a trusted network |
| `timeout` | `number` | `30` | Seconds to wait for the server |
| `connections` | `integer` | `4` | Most connections open at once (1–64) |
| `idleTimeout` | `number` | `60` | Seconds an unused connection is kept before it is reopened |
| `encoding` | `string` | `utf-8` | Encoding of file names |

## SFTP options

All options live under `sources.<name>.sftp`.

| Option | Type | Default | Meaning |
|---|---|---|---|
| `host` | `string` | required | Server name or address |
| `port` | `integer` | `22` | SSH port |
| `username` | `string` | required | Login |
| `password` | `string` | none | Password |
| `privateKey` | `string` | none | Private key text (OpenSSH or PEM; Ed25519, ECDSA or RSA) |
| `privateKeyFile` | `string` | none | Path to a private key file; not together with `privateKey` |
| `passphrase` | `string` | none | Passphrase of an encrypted private key |
| `hostKey` | `string` or `string[]` | none | Accepted server keys, as printed by `ssh-keyscan` |
| `knownHostsFile` | `string` | system `known_hosts` | OpenSSH `known_hosts` file used when `hostKey` is not set |
| `directory` | `string` | login directory | Directory acting as the source root; absolute, or relative to the login directory |
| `timeout` | `number` | `30` | Seconds to wait for the server |
| `connections` | `integer` | `4` | Most connections open at once (1–64) |
| `idleTimeout` | `number` | `300` | Seconds an unused connection is kept before it is reopened |

The SSH agent and the keys in `~/.ssh` are not used; the adapter authenticates only with what the options name.

## Host keys

The server's key is always checked. It is compared, in this order, with `hostKey`, with the entries of `knownHostsFile`, or with the system `known_hosts` (`~/.ssh/known_hosts` of the user running the connector). A key that is missing or different fails the connection with `Server '...' not found in known_hosts`. Unknown keys are never accepted on first use: that would let anyone on the network path impersonate the server and receive the uploads and the password.

When the server's key changes (a reinstall, a key rotation), put the new key in `hostKey`. List both keys during the rotation.

## Secrets

Passwords and keys in a configuration file are readable by anyone who can read the file. Keep the file private, or pass the credentials through a [dynamic source](dynamic-sources.md) that reads them from your secret store. `privateKeyFile` can point at a mounted secret, such as `/run/secrets/...` in Docker.

## How files are handled

- **Connections.** Each source keeps up to `connections` connections open and shares them between requests. A connection that dropped while idle is reopened and the operation is retried once.
- **Writes.** Uploads and generated files are written to a temporary `.<random>.tmp` file in the target folder and then renamed over the target. Readers never see a partial file, and a failed upload leaves the previous file in place. A server that refuses to rename over an existing file gets the old file moved aside first and put back if the rename fails.
- **Streaming.** Downloads are streamed in 64 KiB chunks. Uploads are sent from the request's temporary file.
- **Copies.** FTP and SFTP have no server-side copy, so the connector downloads the file (at most 1 MB in memory, the rest in a temporary file) and uploads it again. Renames and moves are server-side.
- **Links.** Symbolic links and other special entries are skipped in listings, like on the local filesystem.

### FTP specifics

- `MLST`/`MLSD` are used when the server has them (pure-ftpd, ProFTPD, FileZilla Server, IIS). Otherwise `SIZE`, `MDTM` and `LIST` are used (vsftpd), and Unix and Windows (IIS/DOS) listing formats are read.
- Times are taken as UTC. Without `MLSD`, listings of recent files carry minutes, not seconds, and folders have no time.
- Passive mode is used. The address the server announces for data connections is ignored, and data connections go to `host`. This helps servers behind NAT and prevents a server from redirecting the connector elsewhere.
- FTPS data connections resume the TLS session of the control connection, which vsftpd requires by default (`require_ssl_reuse`).

## Limits

- Plain FTP sends the password and the files unencrypted. Use `tls: true` or SFTP outside a trusted network.
- Implicit FTPS (a TLS-only port, usually 990) is not supported. Use explicit FTPS on port 21.
- On FTP servers without `MLSD`, listing a folder that does not exist may return an empty list instead of an error.
- Each open download holds one connection until it finishes, so `connections` limits the number of simultaneous downloads per source.

## Troubleshooting

`Server '...' not found in known_hosts`
:   Set `hostKey` to the output of `ssh-keyscan` for that host and port. Keys in `known_hosts` for a non-standard port are stored as `[host]:port`.

`530 Login incorrect` / `AuthenticationException`
:   Check `username` and `password`. For SFTP with a key, also check that the server has the public key in `authorized_keys` and that `passphrase` is set for an encrypted key.

`425 Can't open data connection` or timeouts on listings
:   The server's passive port range is blocked by a firewall. Open it, or check the server's passive-mode settings.

`certificate verify failed`
:   The server's certificate is not signed by a CA the system trusts, or the certificate name does not match `host`. Use the name on the certificate, install the CA, or set `verifyCertificate: false` on a trusted network.
