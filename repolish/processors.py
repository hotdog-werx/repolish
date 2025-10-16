import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Patterns:
    tag_blocks: dict[str, str]
    regexes: dict[str, str]


def extract_patterns(content: str) -> Patterns:
    """Extracts text blocks and regex patterns from the given content.

    Args:
        content: The input string containing text blocks and regex patterns.

    Returns:
        A Patterns object containing extracted tag blocks and regexes.
    """
    tag_pattern = re.compile(
        r'## repolish-start\[(.+?)\](.*?)## repolish-end\[\1\]',
        re.DOTALL,
    )
    regex_pattern = re.compile(
        r'## repolish-regex\[(.+?)\]: (.*?)\n',
        re.DOTALL,
    )

    return Patterns(
        tag_blocks=dict(tag_pattern.findall(content)),
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
        new_text = value
        start_tag = re.escape(f'## repolish-start[{tag}]')
        end_tag = re.escape(f'## repolish-end[{tag}]')

        if not value.strip():
            # handle empty replacement
            pattern = re.compile(
                rf'\n?(\s+)({start_tag})(\s+)({end_tag})',
                re.DOTALL,
            )
        else:
            # Handle normal replacement
            pattern = re.compile(
                rf'\n?(\s+)({start_tag})(.*?)({end_tag})\n',
                re.DOTALL,
            )

        content = pattern.sub(rf'{new_text}', content)
    return content


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
        matches = pattern.search(local_file_content)
        if matches:
            content = pattern.sub(rf'{matches.group(0)}', content)
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
    content = apply_regex_replacements(content, patterns.regexes, local_content)
    return content
