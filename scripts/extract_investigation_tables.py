"""Extract bounded workshop DART tables locally, preserving document order and text."""

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.depth = 0
        self.context = []
        self.before = ""

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.depth == 0:
                self.table = []
                self.before = " ".join(self.context)[-800:]
            self.depth += 1
        if tag == "tr" and self.depth:
            self.row = []
        if tag in ["td", "th", "tu", "te"] and self.depth:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ["td", "th", "tu", "te"] and self.cell is not None:
            if self.row is not None:
                self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            if self.table is not None:
                self.table.append(self.row)
            self.row = None
        if tag == "table":
            self.depth -= 1
            if self.depth == 0:
                self.tables.append({"before": self.before, "rows": self.table})
                self.table = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        elif not self.depth and data.strip():
            self.context.append(data.strip())
            self.context = self.context[-50:]


parser_args = argparse.ArgumentParser(description=__doc__)
parser_args.add_argument("input", type=Path)
args = parser_args.parse_args()
for p in args.input.glob("*.xml"):
    parser = Tables()
    try:
        text = p.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        text = p.read_bytes().decode("cp949")
    parser.feed(text)
    p.with_suffix(".tables.json").write_text(
        json.dumps(parser.tables, ensure_ascii=False, indent=2)
    )
    print(p.name, len(parser.tables))
