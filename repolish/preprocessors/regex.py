"""Regex-based preprocessing for templates.

This module handles regex pattern extraction and replacement in templates,
including support for capture groups and indentation-aware trimming.
"""

import re

from hotlog import get_logger

logger = get_logger(__name__)


def _select_capture(match: re.Match) -> str:
    """Return the author's intended capture from a regex match.

    If the regex contains capturing groups, prefer the first group
    (group 1). Otherwise fall back to the full match (group 0).
    This lets regex authors precisely specify what should be
    extracted and inserted.
    """
    if match.lastindex:
        # prefer the first capture group when present
        return match.group(1)
    return match.group(0)


def _trim_block_by_indent(block: str) -> str:
    """Trim a matched block to the contiguous, same-indentation region.

    Keeps the first line and any immediately following lines that are
    either blank or indented at least as far as the first line. Stops at
    the first subsequent line with smaller indentation. This heuristic is
    intentionally simple and works well for indentation-based formats
    (YAML, Python-ish lists, etc.) but is only a safeguard — authors
    should prefer explicit capture groups to precisely control what to
    extract.
    """
    lines = block.splitlines(keepends=True)
    if not lines:
        return block
    first = lines[0]
    anchor_indent = len(first) - len(first.lstrip(' '))
    kept = [first]
    for ln in lines[1:]:
        if ln.strip() == '':
            kept.append(ln)
            continue
        indent = len(ln) - len(ln.lstrip(' '))
        if indent >= anchor_indent:
            kept.append(ln)
        else:
            break
    return ''.join(kept)


def _extend_trimmed_region_to_include_whitespace(
    content: str,
    trimmed_end: int,
    tpl_cap_end: int,
) -> int:
    """Preserve trailing whitespace-only content from the original capture."""
    if trimmed_end < tpl_cap_end:
        between = content[trimmed_end:tpl_cap_end]
        # only extend if between contains only spaces/tabs (no other
        # non-whitespace characters) and includes at least one newline
        # so we don't accidentally swallow inline spaces.
        # Consider all whitespace (including newlines) when deciding if the
        # slice is empty of non-whitespace characters.
        if between.strip() == '' and '\n' in between:
            return tpl_cap_end
    return trimmed_end


def apply_regex_replacements(
    content: str,
    regexes: dict[str, str],
    local_file_content: str,
) -> str:
    """Applies regex replacements to the content."""
    regex_pattern = re.compile(
        r'^.*## repolish-regex\[(.+?)\]:.*\n?',
        re.MULTILINE,
    )
    content = regex_pattern.sub('', content)
    logger.debug(
        'applying_regex_replacements',
        regexes=[str(name) for name in regexes],
    )

    # apply regex replacements
    for regex_name, regex_pattern in regexes.items():
        pattern = re.compile(rf'{regex_pattern}', re.MULTILINE)
        local_match = pattern.search(local_file_content)
        if not local_match:
            logger.debug(
                'regex_no_match_in_target',
                regex=regex_name,
                pattern=regex_pattern,
            )
            continue

        logger.debug(
            'regex_matched_in_target',
            regex=regex_name,
            matched=_select_capture(local_match),
        )

        # Prefer the author's explicit capture when present (group 1); if no
        # capture is present fall back to the full match (group 0). This gives
        # template authors precise control while remaining backwards
        # compatible for patterns that don't use groups.
        local_matched_raw = _select_capture(local_match)
        local_matched = _trim_block_by_indent(local_matched_raw)

        # Find where the pattern would match in the template content (after
        # we've removed the declaration line). Trim the template match using
        # the same indentation-aware heuristic so we only replace the
        # anchor's block and don't remove following unrelated sections from
        # the template.
        template_match = pattern.search(content)
        if not template_match:
            # nothing to replace in template
            continue

        # Determine which group index we used (1 when the author provided a
        # capture group, otherwise 0 for the full match). Compute the absolute
        # span of that selected region in the template so replacements are
        # performed at the correct indices even when the declared pattern
        # includes surrounding context.
        tpl_group_idx = 1 if template_match.lastindex else 0
        tpl_cap_start, tpl_cap_end = template_match.span(tpl_group_idx)

        tpl_matched_raw = content[tpl_cap_start:tpl_cap_end]
        tpl_matched = _trim_block_by_indent(tpl_matched_raw)

        # Replace only the trimmed matched region in the template with the
        # trimmed local content. The trimmed region starts at the capture
        # start and extends the length of the trimmed text. However, if the
        # template contained only whitespace (spaces/newlines) between the
        # end of the trimmed block and the original capture end (for
        # example a blank line before the next section marker), preserve
        # that whitespace so surrounding structure/spacing is unchanged.
        trimmed_start = tpl_cap_start
        trimmed_end = tpl_cap_start + len(tpl_matched)

        # Potentially extend the trimmed end to include whitespace-only
        # padding that was part of the original capture. Delegate to the
        # helper so the logic is tested and `apply_regex_replacements` is
        # easier to read.
        trimmed_end = _extend_trimmed_region_to_include_whitespace(
            content,
            trimmed_end,
            tpl_cap_end,
        )

        content = content[:trimmed_start] + local_matched + content[trimmed_end:]
    return content
