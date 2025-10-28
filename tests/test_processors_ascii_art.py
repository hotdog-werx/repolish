from repolish.processors import replace_text

ASCII_ART = """
                      ⣠⣾⣿⠟⠋⠙⠻⣦⡀
                    ⢀⣾⣿⠟⠁ ⢀⡀ ⠘⠇
                  ⣠⣴⣿⠟⢁⣤⡾⠛⠋⣴⣿⣷⣄
               ⢀⣤⣾⡿⠋ ⢀⣾⠃ ⣠⣾⣿⣿⣿⡟
           ⢀⣠⣴⣾⣿⠟⢉⣀⣀⣤⡾⠃⣠⣾⣿⣿⣿⣿⠟⠁
       ⣀⣠⣴⣾⣿⣿⠟⠋⣠⡾⠛⠉⠉⠁⣠⣾⣿⣿⣿⣿⣿⠃
    ⢰⣾⣿⣿⣿⠿⠛⠉  ⣰⡟  ⢀⣤⣾⣿⣿⣿⣿⣿⠟⠁
   ⢠⡿⠛⠉⢉⡴⠒⠒⠒⠚⠛⠉⣀⣤⣶⣿⣿⣿⣿⣿⡿⠋⠁
   ⢿⡇ ⠠⠟ ⢀⣀⣤⣴⣾⣿⣿⣿⣿⣿⣿⣿⠟⠉
   ⠈⢷⡄⢀⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠟⠋⠁
      ⠈⢿⣿⣿⣿⣿⣿⠿⠟⠋⠉
"""

TEMPLATE = r"""
Some Intro Text

## repolish-regex[custom]: (?s)<!-- custom-start -->(.*?)(?=^#|\Z)
<!-- custom-start -->
PLACEHOLDER
<!-- custom-end -->
"""

TEMPLATE_INDENTED = r"""
Some Intro Text
## repolish-regex[custom]: (?s)^\s*<!-- custom-start -->(.*?)(?=^#|\Z)
  <!-- custom-start -->  PLACEHOLDER
  <!-- custom-end -->

# Next Section
"""

LOCAL = f"""
<!-- custom-start -->
{ASCII_ART}
<!-- custom-end -->
"""

LOCAL_INDENTED = f"""
Some Intro Text

  <!-- custom-start -->
{ASCII_ART}
  <!-- custom-end -->
"""

EXPECTED_LOCAL = f"""
Some Intro Text

<!-- custom-start -->
{ASCII_ART}
<!-- custom-end -->
"""

EXPECTED_LOCAL_INDENTED = f"""
Some Intro Text
  <!-- custom-start -->
{ASCII_ART}
  <!-- custom-end -->
# Next Section
"""


def test_replace_ascii_art_single_assertion():
    """Use the variables defined above and make a single equality assertion.

    This verifies the basic, non-indented replacement path where the
    template's regex captures the block and the local file provides the
    ASCII art starting at column 0.
    """
    out = replace_text(TEMPLATE, LOCAL)
    assert out == EXPECTED_LOCAL


def test_replace_ascii_art_indented_anchor():
    """Verifies the indented replacement path using the provided variables.

    When the template's anchor is indented, trimming should drop less-
    indented lines from the captured block.
    """
    out = replace_text(TEMPLATE_INDENTED, LOCAL_INDENTED)
    assert out == EXPECTED_LOCAL_INDENTED
