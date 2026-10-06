"""The output adapter: write each page as a static HTML file.

``HtmlFolder`` writes a page body into a whole HTML document in 1 folder:
a temporary file, then a rename, so a reader never sees half a page. The
pages link to each other by relative links, so the folder works when it is
opened from the disk or put on any web host.

Another adapter (a wiki, a shared drive) needs only ``write(name, title,
body)`` and ``read(name)``.
"""
import html
import os
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
