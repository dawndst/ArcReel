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


def expand_scene_excerpt(text: str, quote: str) -> tuple[int, int]:
    """Restore omitted source between ordered excerpts, never preserve a stitched quotation.

    Only scene anchors use this: speech still requires verbatim text. All fragments and
    the complete span must be unique in the supplied source; ambiguous or invented words fail.
    """
    import re

    pieces = [part.strip().strip('「」『』“”‘’"') for part in re.split(r"…{2,}|\.{3,}", quote) if part.strip()]
    if len(pieces) < 2 or len(pieces) > 32:
        raise ValueError("不是可恢复的省略摘录")
    positions = [i for i, char in enumerate(text) if not char.isspace()]
    compact = "".join(text[i] for i in positions)
    needles = ["".join(part.split()) for part in pieces]
    if any(not needle for needle in needles):
        raise ValueError("省略摘录包含空片段")
    states = [(None, 0)]
    for needle in needles:
        following = set()
        for start, previous_end in states:
            offset = compact.find(needle, previous_end)
            while offset >= 0:
                begin = offset if start is None else start
                end = offset + len(needle)
                if positions[end - 1] + 1 - positions[begin] <= 3000:
                    following.add((begin, end))
                if len(following) > 1000:
                    raise ValueError("省略摘录存在过多歧义")
                offset = compact.find(needle, offset + 1)
        states = list(following)
    if len(states) != 1:
        raise ValueError("省略摘录不能定位到唯一连续原文")
    start, end = states[0]
    return positions[start], positions[end - 1] + 1
