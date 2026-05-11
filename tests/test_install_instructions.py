from pathlib import Path


INSTALL_MD = Path(__file__).resolve().parents[1] / "install.md"


def test_step5_reminds_user_to_set_copilot_github_token():
    install_md = INSTALL_MD.read_text()

    assert "`COPILOT_GITHUB_TOKEN`" in install_md
    assert "user_copilot_requests=read" in install_md
    assert "gh aw secrets set COPILOT_GITHUB_TOKEN" in install_md
    assert "Account permissions > Copilot Requests > Read" in install_md


def test_step5_tells_installing_agent_to_print_reminder():
    install_md = INSTALL_MD.read_text()

    assert "When you finish Step 5, print this reminder" in install_md
    assert "with the pull request link" in install_md
