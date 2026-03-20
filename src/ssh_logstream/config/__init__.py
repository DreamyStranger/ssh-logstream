"""
ssh_logstream.config
====================

Public configuration exports for ssh-logstream.
"""

from ssh_logstream.config.ssh import SshConfig
from ssh_logstream.config.streamer import LineStreamerConfig

__all__ = ["LineStreamerConfig", "SshConfig"]
