from unittest.mock import MagicMock, patch

from app.emailer import send_email


def test_send_email_logs_in_and_sends_via_starttls():
    with patch("app.emailer.smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        send_email(
            smtp_host="smtp.example.com", smtp_port=587, smtp_user="user",
            smtp_password="secret", email_from="from@x.test", email_to=["to@x.test"],
            subject="Subject", html_body="<p>Body</p>",
        )

        mock_smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=30)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user", "secret")
        assert mock_server.sendmail.call_count == 1
        args = mock_server.sendmail.call_args[0]
        assert args[0] == "from@x.test"
        assert args[1] == ["to@x.test"]
        assert "Subject" in args[2]


def test_send_email_with_multiple_recipients_joins_header_and_sends_to_all():
    with patch("app.emailer.smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        send_email(
            smtp_host="smtp.example.com", smtp_port=587, smtp_user="user",
            smtp_password="secret", email_from="from@x.test",
            email_to=["a@x.test", "b@x.test"],
            subject="Subject", html_body="<p>Body</p>",
        )

        args = mock_server.sendmail.call_args[0]
        assert args[1] == ["a@x.test", "b@x.test"]
        assert "To: a@x.test, b@x.test" in args[2]


def test_send_email_port_465_uses_smtp_ssl_not_starttls():
    with patch("app.emailer.smtplib.SMTP_SSL") as mock_ssl_cls, \
         patch("app.emailer.smtplib.SMTP") as mock_plain_cls:
        mock_server = MagicMock()
        mock_ssl_cls.return_value.__enter__.return_value = mock_server

        send_email(
            smtp_host="smtp.example.com", smtp_port=465, smtp_user="user",
            smtp_password="secret", email_from="from@x.test", email_to=["to@x.test"],
            subject="Subject", html_body="<p>Body</p>",
        )

        mock_ssl_cls.assert_called_once_with("smtp.example.com", 465, timeout=30)
        mock_plain_cls.assert_not_called()
        mock_server.starttls.assert_not_called()
        mock_server.login.assert_called_once_with("user", "secret")
        assert mock_server.sendmail.call_count == 1


def test_send_email_port_587_uses_plain_smtp_with_starttls():
    with patch("app.emailer.smtplib.SMTP_SSL") as mock_ssl_cls, \
         patch("app.emailer.smtplib.SMTP") as mock_plain_cls:
        mock_server = MagicMock()
        mock_plain_cls.return_value.__enter__.return_value = mock_server

        send_email(
            smtp_host="smtp.example.com", smtp_port=587, smtp_user="user",
            smtp_password="secret", email_from="from@x.test", email_to=["to@x.test"],
            subject="Subject", html_body="<p>Body</p>",
        )

        mock_plain_cls.assert_called_once_with("smtp.example.com", 587, timeout=30)
        mock_ssl_cls.assert_not_called()
        mock_server.starttls.assert_called_once()


def test_send_email_port_25_uses_plain_smtp_with_starttls():
    with patch("app.emailer.smtplib.SMTP_SSL") as mock_ssl_cls, \
         patch("app.emailer.smtplib.SMTP") as mock_plain_cls:
        mock_server = MagicMock()
        mock_plain_cls.return_value.__enter__.return_value = mock_server

        send_email(
            smtp_host="smtp.example.com", smtp_port=25, smtp_user="user",
            smtp_password="secret", email_from="from@x.test", email_to=["to@x.test"],
            subject="Subject", html_body="<p>Body</p>",
        )

        mock_plain_cls.assert_called_once_with("smtp.example.com", 25, timeout=30)
        mock_ssl_cls.assert_not_called()
