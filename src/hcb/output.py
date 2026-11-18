"""The output adapter: write each page as a static HTML file.

``HtmlFolder`` writes a page body into a whole HTML document in 1 folder:
a temporary file, then a rename, so a reader never sees half a page. The
pages link to each other by relative links, so the folder works when it is
opened from the disk or put on any web host.

Another adapter (a wiki, a shared drive) needs only ``write(name, title,
body)`` and ``read(name)``.

``write_file`` writes 1 file of a run folder whole or not at all (the notes
step's ``reply.txt`` and ``notes.json``).
"""
import contextlib
import html
import os
import tempfile
from pathlib import Path

DOCUMENT = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>html,body{{margin:0;padding:12px 0;background:#e9e3d6}}
@media (prefers-color-scheme: dark){{html:not([data-theme]),html:not([data-theme]) body{{background:#0b0c10}}}}
html[data-theme="dark"],html[data-theme="dark"] body{{background:#0b0c10}}</style>
</head>
<body>
{body}
</body>
</html>
"""


class FolderSyncError(OSError):
    """``write_file`` put the new file in place, but the fsync of its folder failed."""


def write_file(path, text):
    """Write the whole file ``path``, so a reader or a power cut never finds half of it.

    A ``.`` temp file in the same folder, flush, fsync, ``os.replace``, then an
    fsync of the folder, so the rename is on disk too (skipped where
    ``os.O_DIRECTORY`` does not exist, such as on Windows). The folder must
    exist: this makes none. A failure before the rename leaves the old file
    and no temp file; when the temp file can not be removed, the first error
    is raised. Raises OSError, or UnicodeError for text that UTF-8 can not
    hold; a failed sync of the folder after the rename raises
    ``FolderSyncError``, an OSError: the new file is in place.
    """
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):      # the first error stays
            Path(tmp).unlink(missing_ok=True)
        raise
    if hasattr(os, "O_DIRECTORY"):
        try:
            folder = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(folder)
            finally:
                os.close(folder)
        except OSError as err:
            raise FolderSyncError(f"{path.name} written, folder not synced "
                                  f"({type(err).__name__})") from err


class HtmlFolder:
    def __init__(self, folder):
        self.folder = Path(folder)

    def path(self, name):
        return self.folder / f"{name}.html"

    def read(self, name):
        """The text of the page ``name``, or "" when there is none."""
        try:
            return self.path(name).read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def write(self, name, title, body):
        """Write the page ``name`` (``whiteboard``, ``menu``, ``groceries``); returns its path."""
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.path(name)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(DOCUMENT.format(title=html.escape(title), body=body),
                             encoding="utf-8")
        os.replace(temporary, path)
        return path
