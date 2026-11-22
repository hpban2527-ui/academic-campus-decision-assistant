"""Keep API reset and save tests away from the running application's session."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory


def pytest_configure(config):
    directory = TemporaryDirectory(prefix="unilife-tests-")
    previous = os.environ.get("UNILIFE_SESSION_FILE")
    os.environ["UNILIFE_SESSION_FILE"] = str(Path(directory.name) / "session.json")

    def restore():
        if previous is None:
            os.environ.pop("UNILIFE_SESSION_FILE", None)
        else:
            os.environ["UNILIFE_SESSION_FILE"] = previous
        directory.cleanup()

    config.add_cleanup(restore)
