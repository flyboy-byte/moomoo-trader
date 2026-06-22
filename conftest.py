"""Test hermeticity: moomoo's ft_logger instantiates a module-level singleton
on import that writes to ~/.com.moomoo.OpenD/Log, creating that directory if
needed. On environments where $HOME isn't writable, this crashes pytest during
collection before any test runs. Redirecting HOME to a throwaway temp dir
before collection starts makes test runs independent of the real $HOME and
keeps vendor log noise out of the workspace and the user's actual home dir.

Root-level conftest.py is imported before any test module in the repo, so this
runs ahead of the first `import moomoo` triggered by mm/connection.py,
mm/data.py, or mm/execution.py.
"""
import os
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="moomoo-test-home-")
