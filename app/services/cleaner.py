import re

from bs4 import BeautifulSoup, Tag

from app.utils.text import compact

BAD = re.compile(
    r"(?:^|[-_\s])(advert(?:isement)?|ads?|cookie|consent|social|share|newsletter|login|tracking|menu)(?:$|[-_\s])",
    re.I,
)


class ContentCleaner:
    def clean(self, soup: BeautifulSoup) -> BeautifulSoup:
        for node in list(soup.find_all(True)):
            if node.parent is None:
                continue
            if node.name in {"script", "style", "noscript", "svg", "iframe", "canvas", "template"}:
                node.decompose()
                continue
            style = re.sub(r"\s+", "", str(node.get("style", "")).lower())
            if (
                node.has_attr("hidden")
                or node.get("aria-hidden") == "true"
                or "display:none" in style
                or "visibility:hidden" in style
            ):
                node.decompose()
                continue
            label = " ".join([str(node.get("id", "")), " ".join(node.get("class", []))])
            if BAD.search(label) and not self.substantive(node):
                node.decompose()
            elif node.name in {"nav", "aside", "footer", "header"} and not self.substantive(node):
                node.decompose()
        return soup

    @staticmethod
    def substantive(node: Tag) -> bool:
        text = compact(node.get_text(" ", strip=True))
        linked = sum(len(a.get_text()) for a in node.find_all("a"))
        return (len(text) >= 160 and linked / max(len(text), 1) < 0.45) or bool(node.find(["pre", "table"]))
