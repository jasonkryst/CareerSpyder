# Third-party notices

This page lists data and services that CareerSpyder bundles or calls and that come with their own terms.
Python dependencies are declared in `pyproject.toml`. Vendored front-end
libraries live under `app/web/static/vendor/` with their own licence headers.

## SecLists: 10k most common passwords

- **Used for:** the offline common-password blocklist in
  `app/security/password_policy.py` (#269).
- **File:** `app/security/wordlists/common-passwords.txt`, bundled unmodified.
- **Source:** [danielmiessler/SecLists](https://github.com/danielmiessler/SecLists)
  `Passwords/Common-Credentials/10k-most-common.txt` at commit
  `68bcd12457978649d41ae4f56e3b5d2db2b72560`.
- **SHA-256:** `68782d6a4a19a4768d5f15dd66bd534e7a33055cc755411e33f16d18c50fdcce`
- **Licence:** MIT

```
MIT License

Copyright (c) 2018 Daniel Miessler

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Have I Been Pwned: Pwned Passwords API

- **Used for:** the opt-in breached-password check
  (`CHECK_BREACHED_PASSWORDS=true`).
- **Service:** [Pwned Passwords](https://haveibeenpwned.com/Passwords) by
  Troy Hunt, range endpoint `https://api.pwnedpasswords.com/range/{prefix}`.
  It needs no API key, and no data or code from it is bundled.
- **Credit:** courtesy attribution. Re-read the current
  [API terms](https://haveibeenpwned.com/API/v3) before any hosted or
  commercial deployment.
