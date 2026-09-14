"""``orion email`` -- connect an email account for sending (SMTP + app password)."""

from __future__ import annotations

import smtplib

import click


@click.group()
def email() -> None:
    """Connect an email account so Orion can send approved emails."""


@email.command("setup")
@click.option("--address", prompt="Your Gmail address", help="The account emails are sent from.")
def setup(address: str) -> None:
    """Save your address and a Gmail app password, then verify the login.

    The app password is typed here, hidden, and stored only in
    ~/.orion/credentials.toml -- never in chat or a model prompt.
    """
    from orion.core.credentials import save_credential
    from orion.tools.email_send import is_valid_address, smtp_server_for

    address = address.strip()
    if not is_valid_address(address):
        raise click.ClickException(f"'{address}' is not a valid email address.")

    click.echo(
        "\nCreate an app password at https://myaccount.google.com/apppasswords\n"
        "(2-Step Verification must be on). Paste the 16 characters below; typing is hidden.\n"
    )
    password = click.prompt("App password", hide_input=True).replace(" ", "")
    if len(password) < 8:
        raise click.ClickException("That doesn't look like an app password (expected 16 characters).")

    host, port = smtp_server_for(address)
    click.echo(f"Checking the login with {host}:{port} ...")
    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            server.login(address, password)
    except smtplib.SMTPAuthenticationError:
        raise click.ClickException(
            "Login rejected. Use an app password (not your normal password) and make sure "
            "2-Step Verification is on. Nothing was saved."
        )
    except OSError as exc:
        raise click.ClickException(f"Could not reach {host}: {exc}. Nothing was saved.")

    save_credential("email", "EMAIL_USERNAME", address)
    save_credential("email", "EMAIL_PASSWORD", password)
    click.echo(click.style(f"Connected. Orion can now send approved emails from {address}.", fg="green"))
    click.echo("No restart needed: the credentials are read each time an email is sent.")


@email.command("test")
@click.argument("to")
def test(to: str) -> None:
    """Send a short test email to TO using the saved account."""
    from orion.tools.email_send import send_email

    ok, message = send_email(to, "This is a test email from Orion.", "Orion test email")
    if not ok:
        raise click.ClickException(message)
    click.echo(click.style(message, fg="green"))


@email.command("status")
def status() -> None:
    """Show whether an email account is connected (never prints the password)."""
    from orion.core.credentials import get_tool_credential
    from orion.tools.email_send import smtp_server_for

    address = get_tool_credential("email", "EMAIL_USERNAME") or ""
    has_password = bool(get_tool_credential("email", "EMAIL_PASSWORD"))
    if address and has_password:
        host, port = smtp_server_for(address)
        click.echo(f"Connected: {address} via {host}:{port}")
    else:
        click.echo("Not connected. Run `orion email setup`.")
