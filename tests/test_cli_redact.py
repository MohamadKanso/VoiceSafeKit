from voicesafekit.cli import main


def test_missing_file_gives_a_clear_error(capsys) -> None:
    assert main(["check", "/nonexistent/transcript.txt"]) == 2
    assert "file not found" in capsys.readouterr().err


def test_redact_reads_stdin(monkeypatch, capsys) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("my pin is four eight two one"))
    assert main(["redact"]) == 0
    assert capsys.readouterr().out.strip() == "my pin is [PIN removed]"


def test_redact_placeholders(monkeypatch, capsys) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("email alex dot rivera at gmail dot com"))
    assert main(["redact", "--placeholders"]) == 0
    assert capsys.readouterr().out.strip() == "email [EMAIL_1]"
