import math
import re
from typing import Protocol

from bs4 import BeautifulSoup
from readability import Document

from app.models.response import ContentBlock, Link
from app.utils.text import compact
from app.utils.urls import safe_link


class Extractor(Protocol):
    def extract(self, soup: BeautifulSoup, url: str | None) -> list[ContentBlock]: ...


class ContentExtractor:
    def extract(self, soup: BeautifulSoup, url: str | None = None) -> list[ContentBlock]:
        roots = soup.find_all(["main", "article"])
        root = max(roots, key=lambda n: len(n.get_text()), default=soup.body or soup)
        blocks = self._blocks(root, url)
        if not blocks and compact(root.get_text()):
            summary = BeautifulSoup(Document(str(root)).summary(), "lxml")
            blocks = self._blocks(summary, url)
            if not blocks:
                text = compact(root.get_text(" ", strip=True))
                blocks = [ContentBlock(id="b0", tag="text", text=text, score=1)]
        return blocks

    def _blocks(self, root, url) -> list[ContentBlock]:
        blocks, seen = [], set()
        heading = ""
        tags = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "table", "blockquote", "dt", "dd"]
        for position, node in enumerate(root.find_all(tags)):
            if node.find_parent(["pre", "table", "li", "blockquote"]) is not None:
                continue
            if node.name.startswith("h"):
                heading = compact(node.get_text(" ", strip=True))[:500]
                continue
            if node.name == "pre":
                text = "```\n" + node.get_text().strip() + "\n```"
            elif node.name == "table":
                text = "\n".join(
                    " | ".join(compact(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"]))
                    for row in node.find_all("tr")
                )
            else:
                text = compact(node.get_text(" ", strip=True))
                if node.name == "li":
                    text = "- " + text
            identity = compact(text).casefold()
            if not identity or identity in seen:
                continue
            seen.add(identity)
            links = []
            for anchor in node.find_all("a", href=True):
                target = safe_link(url, anchor["href"])
                if target:
                    links.append(Link(text=compact(anchor.get_text())[:300], url=target))
            density = sum(len(link.text) for link in links) / max(len(text), 1)
            labels = " ".join(
                str(parent.get("class", "")) + " " + str(parent.get("id", ""))
                for parent in [node, *list(node.parents)[:3]]
            )
            score = math.log1p(len(text)) + min(text.count(".") + text.count(","), 10) * 0.2
            score += 2 if re.search(r"article|content|main|post", labels, re.I) else 0
            score += 1 if heading else 0
            score += 1 if node.name in {"p", "pre", "table"} else 0
            score -= 6 * min(density, 1) + min(len(list(node.parents)), 30) * 0.03
            score -= 3 if re.search(r"nav|menu|sidebar|footer", labels, re.I) else 0
            if score > 0:
                # Bound ranking cost and avoid one long paragraph consuming all output.
                for offset in range(0, len(text), 1800):
                    blocks.append(
                        ContentBlock(
                            id=f"b{position}-{offset}",
                            tag=node.name,
                            text=text[offset : offset + 1800],
                            heading=heading,
                            score=round(score, 3),
                            links=links[:30],
                            position=position,
                        )
                    )
        return blocks
