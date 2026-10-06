"""The row of links between the 3 pages, in the order of the row.

The pages sit in 1 output folder, so each link is relative. The entry of the
page that the reader is on is plain text. The row is fixed text of this
module: no calendar, notes or model text reaches it.
"""
PAGES = (("Whiteboard", "whiteboard.html"),
         ("Dinner plan", "menu.html"),
         ("Groceries", "groceries.html"))
CSS_CLASS = "pagelinks"
WHITEBOARD_LINK, MENU_LINK, GROCERIES_LINK = (link for _, link in PAGES)


def html_row(current):
    """1 line at column 0: a link for each page, the page ``current`` as plain text."""
    entries = "".join(f'<span aria-current="page">{name}</span>' if name == current
                      else f'<a href="{link}">{name}</a>' for name, link in PAGES)
    return f'<div class="{CSS_CLASS}">{entries}</div>'
