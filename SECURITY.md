# Security policy

## Supported versions

KB ERP is pre-1.0. Security fixes land on `main` and in the latest `0.1.x`
release. Older commits are not maintained.

| Version | Supported |
|---|---|
| `main` | Yes |
| `0.1.x` | Yes |
| Earlier | No |

## Reporting a vulnerability

Please do not open a public issue, discussion or pull request for a suspected
vulnerability.

Use GitHub's private reporting flow:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Include the affected version or commit, reproduction steps, expected and
   actual behaviour, and the impact you believe it has.

If private reporting is unavailable, contact the maintainer privately through
their GitHub profile before disclosing anything publicly.

You can expect an acknowledgement within 3 business days and an initial
assessment within 7 business days. Fix timing depends on severity and on
whether the issue affects a documented production control. We will credit you
in the advisory unless you ask us not to.

## In scope

- Authentication and session handling, including password reset and login
  throttling
- Authorization: ACLs, record rules, app-level gates and menu filtering
- Injection: SQL, template, command and header injection
- Cross-site scripting, request forgery and unsafe redirects
- Access to another user's records or another deployment's data
- Exposure of secrets, tokens or customer data in logs, errors or responses
- Path traversal, unsafe file handling and unsafe deserialization
- Vulnerabilities in dependencies that are reachable from the application

## Out of scope

- The documented development defaults (`admin` / `admin`, `KB_DEBUG=1`, the
  open `/metrics` endpoint in debug mode). Production settings are described in
  [`docs/runbook.md`](docs/runbook.md).
- Missing hardening that is explicitly delegated to the deployment: TLS, a
  reverse proxy, host firewalls, off-host backups and secret storage.
- Reports produced only by a scanner with no demonstrated impact.
- Social engineering, physical access and denial of service from an
  unauthenticated attacker sending sustained traffic.

## Handling

We reproduce the report against a supported commit, add a regression test, and
prepare the fix privately. Once a fix is available we publish a GitHub security
advisory, credit the reporter, and note the affected versions. Please give us a
reasonable window to ship the fix before writing publicly about the issue.
