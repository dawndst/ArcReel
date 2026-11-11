"""Locate literal citations despite EPUB whitespace and excerpt quotation wrappers."""


def locate(text: str, quote: str) -> tuple[int, int]:
    """Return a unique source span; preserve wording and punctuation inside an excerpt."""
    pos = text.find(quote)
    if quote.strip() and pos >= 0 and text.find(quote, pos + 1) < 0:
        return pos, pos + len(quote)
    positions = [i for i, char in enumerate(text) if not char.isspace()]
    compact = "".join(text[i] for i in positions)
    needle = "".join(quote.split())
    pos = compact.find(needle)
    # Models may wrap a verbatim excerpt in quotation marks absent at the excerpt boundary.
    if pos < 0:
        needle = needle.strip('「」『』“”‘’"')
        pos = compact.find(needle)
    if not needle or pos < 0 or compact.find(needle, pos + 1) >= 0:
        raise ValueError(f"引文必须在当前原文中唯一出现（仅容忍排版空白与摘录外层引号，不改词或拼接）：{quote[:90]}")
    return positions[pos], positions[pos + len(needle) - 1] + 1
