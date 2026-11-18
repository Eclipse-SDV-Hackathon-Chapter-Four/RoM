# Contributing

Thanks for your interest in this project.

## Eclipse Contributor Agreement

Before your contribution can be accepted, you must electronically sign the
[Eclipse Contributor Agreement (ECA)](https://www.eclipse.org/legal/ECA.php):

1. Create an [Eclipse account](https://accounts.eclipse.org/user/register) and link your GitHub username to it.
2. Sign the ECA from your account page.
3. Commit with the same email address as your Eclipse account.

For more information, see the [Eclipse Foundation Project Handbook](https://www.eclipse.org/projects/handbook/).

## How to contribute

1. Open an issue describing the bug or the change.
2. Fork the repository, create a branch, and make your change.
3. Every new source file starts with the license header:

   ```
   SPDX-FileCopyrightText: 2026 Contributors to the Eclipse Foundation
   SPDX-License-Identifier: Apache-2.0
   ```

4. Run the checks locally: `make test` (the same targets CI runs, see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).
5. Open a pull request against `main` and reference the issue.

## Reporting security issues

Do not open a public issue; see [SECURITY.md](SECURITY.md).
