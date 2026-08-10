from app.agent import INSTRUCTIONS, create_agent


def test_language_policy_has_polish_starting_fallback_and_switch_examples() -> None:
    assert "fallback language is Polish" in INSTRUCTIONS
    assert '"Actually, let\'s continue in English" -> answer in English' in INSTRUCTIONS
    assert '"Dobra, wróćmy do polskiego" -> answer in Polish' in INSTRUCTIONS


def test_agent_receives_language_policy() -> None:
    agent = create_agent()
    assert agent.instructions == INSTRUCTIONS


def test_polish_accent_is_controlled_separately_from_language() -> None:
    assert "Control response language and spoken accent separately" in INSTRUCTIONS
    assert "native STANDARD POLISH accent" in INSTRUCTIONS
    assert "Do NOT use American or British English" in INSTRUCTIONS
