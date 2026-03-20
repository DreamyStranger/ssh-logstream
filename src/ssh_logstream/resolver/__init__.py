"""
ssh_logstream.resolver
======================

Remote file resolver exports.
"""

from ssh_logstream.resolver.remote_file_resolver import RemoteFileResolver, resolve_remote_member

__all__ = ["RemoteFileResolver", "resolve_remote_member"]
