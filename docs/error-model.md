# Error Model

All library exceptions derive from `SshLogStreamError`.

## Configuration and connection errors

- `ConfigurationError`: invalid input, unsupported codec settings, or invalid SSH options
- `AuthenticationError`: SSH authentication failure
- `SshConnectionError`: SSH connection or channel setup failure

## Resolution and streaming errors

- `RemoteFileNotFoundError`: no matching file found in the target folder
- `RemoteFileAmbiguityError`: more than one matching file found
- `StreamingError`: non-decode runtime streaming failure
- `DecodeError`: byte decoding failed under the configured policy
- `LineTooLongError`: a partial line exceeded `max_line_bytes`

## Intent

The hierarchy is designed so callers can either catch specific operational
failures or use `SshLogStreamError` as a library-wide fallback.

In particular, configuration failures are intended to happen before remote
streaming begins, while transport and streaming errors represent runtime
operational failures.
