# Security Policy

## Reporting a vulnerability

Please do not open a public GitHub issue for security vulnerabilities.

Report them privately via GitHub's security advisory feature.

Include:

- a description of the issue
- steps to reproduce
- affected configuration or environment details
- the potential impact

## Known considerations

- Host key verification: unknown SSH host keys are rejected by default. For controlled trust-on-first-use environments, `SshConfig.allow_unknown_hosts=True` can be enabled explicitly. For strict production verification, set `SshConfig.known_hosts_path` or rely on the system known-hosts file.
- Private key handling: private key paths are passed directly to Paramiko. Ensure key files have appropriate filesystem permissions and are not stored in insecure locations.
- Remote command execution: the library executes remote `find`, `cat`, and `tail` commands over SSH. Dynamic path inputs are shell-quoted, but callers should still treat remote folders and filenames as security-sensitive inputs.
- Follow mode: `stream(follow=True)` keeps the SSH session open and continues reading appended data indefinitely. Use it only when long-lived remote streams are expected and operationally acceptable.
- Decode configuration: `encoding` and `errors` settings affect how remote bytes are interpreted. Use conservative settings in production unless you explicitly need permissive decoding behavior.
