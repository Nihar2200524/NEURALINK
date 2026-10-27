from app.models.request import Options
from app.models.response import BridgeResponse, Content, Optimization, Section
from app.services.parser import ParsedPage
from app.services.relevance import RelevanceEngine
from app.utils.tokens import ApproximateTokenizer, TokenEstimator


class Formatter:
    def __init__(self, tokenizer: TokenEstimator | None = None):
        self.tokenizer = tokenizer or ApproximateTokenizer()

    def format(
        self,
        parsed: ParsedPage,
        blocks: list,
        options: Options,
        url: str | None,
        raw_bytes: int,
        metadata: dict,
    ) -> BridgeResponse:
        ranked = RelevanceEngine().rank(options.query, blocks) if options.query else blocks
        selected, remaining = [], options.max_content_length
        for block in ranked:
            prefix = len(block.heading) + 1 if block.heading else 0
            available = remaining - prefix - (2 if selected else 0)
            if available <= 0:
                break
            text = block.text[:available]
            selected.append((block, text))
            remaining -= prefix + len(text) + (2 if len(selected) > 1 else 0)
        main = "\n\n".join((block.heading + "\n" if block.heading else "") + text for block, text in selected)
        sections = [
            Section(heading=block.heading, text=text, relevance_score=block.relevance_score)
            for block, text in selected
        ]
        links = (
            {link.url: link for block, _ in selected for link in block.links} if options.include_links else {}
        )
        raw_tokens = self.tokenizer.estimate(parsed.raw_text)
        clean_tokens = self.tokenizer.estimate("\n".join(block.text for block in blocks))
        returned_tokens = self.tokenizer.estimate(main)
        stats = Optimization(
            raw_bytes=raw_bytes,
            raw_text_characters=len(parsed.raw_text),
            returned_characters=len(main),
            reduction_percent=self.reduction(len(parsed.raw_text), len(main)),
            estimated_raw_tokens=raw_tokens,
            estimated_clean_tokens=clean_tokens,
            estimated_returned_tokens=returned_tokens,
            estimated_tokens_saved=max(0, raw_tokens - returned_tokens),
            token_reduction_percent=self.reduction(raw_tokens, returned_tokens),
        )
        metadata = {
            **parsed.metadata,
            **metadata,
            "query_matched": bool(selected),
            "token_estimator": "utf8_bytes_div_4",
            "metrics_scope": "main_text",
        }
        return BridgeResponse(
            request={"url": url, "query": options.query},
            page=parsed.page,
            content=Content(main_text=main, sections=sections),
            links=list(links.values())[:100],
            metadata=metadata if options.include_metadata else None,
            optimization=stats,
        )

    @staticmethod
    def reduction(before: int, after: int) -> float:
        return round(max(0, 100 * (1 - after / before)), 2) if before else 0

    @staticmethod
    def markdown(response: BridgeResponse) -> str:
        lines = [
            f"# {response.page.title or 'Web content'}",
            f"Source: {response.request['url'] or 'submitted HTML'}",
            response.content.main_text,
        ]
        if response.links:
            lines += ["## Important links", *[f"- {link.text}: {link.url}" for link in response.links]]
        stats = response.optimization
        lines.append(
            f"Estimated content tokens: {stats.estimated_raw_tokens} -> {stats.estimated_returned_tokens} "
            f"({stats.token_reduction_percent}% reduction)."
        )
        return "\n\n".join(lines)
