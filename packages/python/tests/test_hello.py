from pylib_template.hello import say_hello


def test_hello() -> None:
    assert say_hello() == "Hello from Python!"
