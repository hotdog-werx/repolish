from repolish.processors import replace_text

TEMPLATE = r"""
cat1:
  - line1
  - line2
  ## repolish-regex[cat1-filter]: (^\s*# cat1-filter-additional-paths.*\n(?:\s+.*\n)*)
  # cat1-filter-additional-paths

cat2:
  - from-template
  ## repolish-regex[cat2-filter]: (^\s*# cat2-filter-additional-paths.*\n(?:\s+.*\n)*)
  # cat2-filter-additional-paths

cat3:
  - cat3-line
  ## repolish-regex[cat3-filter]: (^\s*# cat3-filter-additional-paths.*\n(?:\s+.*\n)*)
  # cat3-filter-additional-paths
"""

LOCAL = """
cat1:
  - line1
  - line2
  # cat1-filter-additional-paths
  - extra
"""

LOCAL_WITH_CAT2 = """
cat1:
  - line1
  - line2
  # cat1-filter-additional-paths
  - extra

cat2:
  - from-template
  # cat2-filter-additional-paths
  - cat2-extra
"""

LOCAL_WITH_CAT3 = """
cat1:
  - line1
  - line2
  # cat1-filter-additional-paths
  - extra

cat3:
  - cat3-line
  # cat3-filter-additional-paths
"""


def test_regex_anchor_allows_following_sections_to_remain():
    out = replace_text(TEMPLATE, LOCAL)
    # The replacement should preserve the following sections (cat2) from the
    # template. If cat2 is missing after replacement, the regex replacement
    # logic is too aggressive.
    assert 'cat2:' in out
    # And the extra item should be inserted into cat1
    assert '- extra' in out


def test_regex_anchor_normal():
    out = replace_text(TEMPLATE, LOCAL_WITH_CAT2)
    assert 'cat2:' in out
    assert '- extra' in out
    assert '- cat2-extra' in out


def test_regex_anchor_normal_cat3():
    out = replace_text(TEMPLATE, LOCAL_WITH_CAT3)
    expected = r"""
cat1:
  - line1
  - line2
  # cat1-filter-additional-paths
  - extra

cat2:
  - from-template
  # cat2-filter-additional-paths

cat3:
  - cat3-line
  # cat3-filter-additional-paths
"""
    assert out == expected
