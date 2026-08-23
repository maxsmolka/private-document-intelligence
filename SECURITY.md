# Security policy

PDI handles highly sensitive documents and should be deployed only on a trusted private network or VPN behind an HTTPS reverse proxy. It is not hardened for direct public-Internet exposure.

## Supported versions

Security fixes are provided for the latest stable release. At publication, that is the `1.0.x` line. Upgrade to the newest patch before reporting an issue that may already be resolved.

Please report suspected vulnerabilities privately through GitHub's **Report a vulnerability** feature. Do not open a public issue and do not attach documents, credentials, API tokens, logs containing personal data, backups, or exports. Include a minimal reproduction using synthetic data where possible.

The repository, issues, pull requests, Actions logs, and release metadata are public. Treat everything submitted to them as public and permanent. Before posting, remove document contents and metadata, names, addresses, account or contract identifiers, hostnames, IP addresses, storage paths, and deployment topology. If safe redaction is uncertain, do not submit the material.

Local accounts and scoped API tokens still protect access to sensitive material: revoke exposed tokens immediately, use HTTPS and secure cookies, and keep token/secret files readable only by the service account. Backups and exports contain plaintext document and metadata material and require the same custody as originals.

Security fixes are provided for the current release line. See [the security model](docs/SECURITY.md) for threat boundaries, deployment safeguards, and known limitations.
