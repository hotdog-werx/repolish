import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Patterns:
    """Container for extracted patterns from content."""

    tag_blocks: dict[str, str]
    regexes: dict[str, str]


def extract_patterns(content: str) -> Patterns:
    """Extracts text blocks and regex patterns from the given content.

    Args:
        content: The input string containing text blocks and regex patterns.

    Returns:
        A Patterns object containing extracted tag blocks and regexes.
    """
    # Accept markers with optional prefixes (e.g. "## ", "<!-- ", "/* ") so
    # templates can use comment syntax appropriate to the file type. We match a
    # whole start line that contains `repolish-start[name]`, capture the
    # following block, and then match the corresponding end line.
    tag_pattern = re.compile(
        # allow empty inner block (no extra blank line required before end)
        r'^[^\n]*repolish-start\[(.+?)\][^\n]*\n(.*?)[^\n]*repolish-end\[\1\][^\n]*',
        re.DOTALL | re.MULTILINE,
    )

    # Match regex declarations likewise with optional prefixes on the same line
    regex_pattern = re.compile(
        r'^[^\n]*repolish-regex\[(.+?)\]: (.*?)\n',
        re.DOTALL | re.MULTILINE,
    )

    # Return the raw inner block content (no artificial padding). Strip any
    # leading/trailing newlines that are an artifact of how templates were
    # authored so callers get the pure inner text.
    raw_tag_blocks = dict(tag_pattern.findall(content))
    tag_blocks: dict[str, str] = {}
    for k, v in raw_tag_blocks.items():
        tag_blocks[k] = v.strip('\n')

    return Patterns(
        tag_blocks=tag_blocks,
        regexes=dict(regex_pattern.findall(content)),
    )


def safe_file_read(file_path: Path) -> str:
    """Safely reads the content of a file if it exists.

    Args:
        file_path: Path to the file to read.

    Returns:
        The content of the file, or an empty string if the file does not exist.
    """
    if file_path.exists() and file_path.is_file():
        return file_path.read_text()
    return ''


def replace_tags_in_content(content: str, tags: dict[str, str]) -> str:
    """Replaces tag blocks in the content with provided tag values.

    Args:
        content: The original content containing tag blocks.
        tags: A dictionary mapping tag names to their replacement values.

    Returns:
        The content with the tags replaced by their corresponding values.
    """
    for tag, value in tags.items():
        # Build a pattern that matches a whole start line containing the token
        # `repolish-start[tag]`, then captures the inner block, then matches
        # the end line containing `repolish-end[tag]`. This allows comment
        # prefixes/suffixes on the marker lines.
        # Match entire block including optional leading/trailing newline so
        # the replacement doesn't leave extra blank lines.
        pattern = re.compile(
            r'\n?[^\n]*repolish-start\[' + re.escape(tag) + r'\][^\n]*\n'
            r'(.*?)[^\n]*repolish-end\[' + re.escape(tag) + r'\][^\n]*\n?',
            re.DOTALL | re.MULTILINE,
        )
        content = pattern.sub(lambda _m, v=value: f'\n{v}\n', content)
    return content


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

    # apply regex replacements
    for regex_pattern in regexes.values():
        pattern = re.compile(rf'{regex_pattern}', re.MULTILINE)
        local_match = pattern.search(local_file_content)
        if not local_match:
            continue

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


def replace_text(
    template_content: str,
    local_content: str,
    anchors_dictionary: dict[str, str] | None = None,
) -> str:
    """Replaces tag blocks and regex patterns in the template content.

    Args:
        template_content: The content of the template file.
        local_content: The content of the local file to extract patterns from.
        anchors_dictionary: Optional dictionary of anchor replacements provided by
            configuration (maps tag name -> replacement text). If provided, values
            in this dict will be used to replace corresponding `## repolish-start[...]` blocks
            in the template. If not provided, the template's own block contents are
            preserved.

    Returns:
        The modified template content with replaced tag blocks and regex patterns.
    """
    patterns = extract_patterns(template_content)

    # Build the replacement mapping for tag blocks. If an anchors dictionary is
    # provided, use its values to replace the corresponding tag blocks. Otherwise
    # fall back to the template's own block content (i.e. leave defaults).
    tags_to_replace: dict[str, str] = {}
    for tag, default_value in patterns.tag_blocks.items():
        if anchors_dictionary and tag in anchors_dictionary:
            tags_to_replace[tag] = anchors_dictionary[tag]
        else:
            tags_to_replace[tag] = default_value

    content = replace_tags_in_content(template_content, tags_to_replace)
    return apply_regex_replacements(content, patterns.regexes, local_content)
