from signal_chatbot.llm.parsing import split_off_disclaimer


def test_no_marker_returns_message_unchanged_and_empty_disclaimer() -> None:
    assert split_off_disclaimer("just a normal reply") == ("just a normal reply", "")


def test_splits_a_trailing_disclaimer_block_off_the_message() -> None:
    text = "here's the real reply\n\nEthical disclaimer: it's a joke"
    assert split_off_disclaimer(text) == ("here's the real reply", "it's a joke")


def test_splits_a_leading_label_routing_the_rest_to_the_disclaimer() -> None:
    assert split_off_disclaimer("Ethical disclaimer: it's satire") == ("", "it's satire")


def test_marker_is_case_insensitive_and_anchored_to_a_line_start() -> None:
    text = "real reply\nETHICAL DISCLAIMER\nnot serious"
    assert split_off_disclaimer(text) == ("real reply", "not serious")


def test_a_mid_line_mention_is_not_treated_as_the_marker() -> None:
    text = "here's the plan, ethical disclaimer aside, do it."
    assert split_off_disclaimer(text) == (text, "")
