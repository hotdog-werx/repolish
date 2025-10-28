from repolish import processors


def test_extend_when_whitespace_and_newline():
    prefix = 'P'
    trimmed = 'T'
    between = '   \n'
    suffix = 'S'
    content = prefix + trimmed + between + suffix

    trimmed_end = len(prefix + trimmed)
    tpl_cap_end = trimmed_end + len(between)

    assert (
        processors._extend_trimmed_region_to_include_whitespace(
            content,
            trimmed_end,
            tpl_cap_end,
        )
        == tpl_cap_end
    )


def test_do_not_extend_when_no_newline():
    prefix = 'P'
    trimmed = 'T'
    between = '   '  # spaces but no newline
    suffix = 'S'
    content = prefix + trimmed + between + suffix

    trimmed_end = len(prefix + trimmed)
    tpl_cap_end = trimmed_end + len(between)

    assert (
        processors._extend_trimmed_region_to_include_whitespace(
            content,
            trimmed_end,
            tpl_cap_end,
        )
        == trimmed_end
    )


def test_do_not_extend_when_non_whitespace_present():
    prefix = 'P'
    trimmed = 'T'
    between = ' a\n'  # contains non-whitespace
    suffix = 'S'
    content = prefix + trimmed + between + suffix

    trimmed_end = len(prefix + trimmed)
    tpl_cap_end = trimmed_end + len(between)

    assert (
        processors._extend_trimmed_region_to_include_whitespace(
            content,
            trimmed_end,
            tpl_cap_end,
        )
        == trimmed_end
    )
