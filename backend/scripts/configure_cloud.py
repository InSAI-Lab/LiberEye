"""Create a private deployment configuration without printing its token."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import secrets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default="")
    parser.add_argument("--email", default="")
    args = parser.parse_args()
    if args.domain and not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", args.domain):
        parser.error("Use a DNS hostname without scheme or path")
    if args.email and not re.fullmatch(r"[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", args.email):
        parser.error("Use a valid certificate contact email")
    root = Path(__file__).resolve().parents[1]
    text = (root / ".env.example").read_text()
    text = text.replace("LIBEREYE_API_TOKEN=\n", f"LIBEREYE_API_TOKEN={secrets.token_urlsafe(32)}\n")
    text = text.replace("LIBEREYE_DOMAIN=\n", f"LIBEREYE_DOMAIN={args.domain}\n")
    text = text.replace("ACME_EMAIL=\n", f"ACME_EMAIL={args.email}\n")
    path = root / ".env"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        parser.exit(1, "Existing .env preserved. Edit it locally to change settings.\n")
    with os.fdopen(descriptor, "w") as stream:
        stream.write(text)
    (root / "models").mkdir(exist_ok=True)
    print("Created private .env and models/. Configure the same token in the phone app.")


if __name__ == "__main__":
    main()
