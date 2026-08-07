<!-- Ported from Hermes Agent skill collection. Original author: Hermes / Nous Research. -->
<!-- Licensed under the same terms as the original (MIT). -->

---
name: gmail-access
description: "Gmail access via IMAP/SMTP for reading, searching, and sending emails"
category: productivity
tags: [email, gmail, imap, smtp, communication]
version: 1.0.0
created_by: agent
---

# Gmail Access

Access Gmail via IMAP/SMTP using app password authentication.

## Setup

Credentials stored in `~/.hermes/.env`:
```
GMAIL_ADDRESS=xxx@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

## Usage

```bash
# List recent emails
python3 ~/.hermes/scripts/gmail.py inbox 20

# Read specific email
python3 ~/.hermes/scripts/gmail.py read <uid>

# Search emails
python3 ~/.hermes/scripts/gmail.py search "query"

# Send email
python3 ~/.hermes/scripts/gmail.py send "to@email.com" "Subject" "Body text"

# List folders
python3 ~/.hermes/scripts/gmail.py folders
```

## Notes

- Uses IMAP for reading, SMTP for sending
- App password required (not regular Gmail password)
- Enable 2FA first, then create app password at myaccount.google.com/apppasswords
- Script named `gmail.py` to avoid conflict with Python's `email` module
