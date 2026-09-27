# Security Policy — Humatron (humatron.me)

## Responsible Disclosure

At Humatron, security, privacy, and integrity of document processing are paramount. If you discover a security vulnerability in Humatron, we appreciate your assistance in disclosing it responsibly.

### Reporting a Vulnerability

**Please do NOT report security vulnerabilities via public GitHub issues or forums.**

Instead, please send a detailed vulnerability report via encrypted or direct email to:

**`security@humatron.me`** (or **`admin@humatron.me`**)

Please include:

1. Detailed description of the vulnerability and attack vector.
2. Step-by-step reproduction instructions or a minimal Proof of Concept (PoC).
3. The potential impact of the issue (e.g. data exposure, privilege escalation, DoS).
4. Any potential mitigations or patches you have identified.

### Our Commitment

- We will acknowledge receipt of your vulnerability report within **48 hours**.
- We will provide a timeline for assessing and addressing the vulnerability.
- We will coordinate public disclosure after a fix has been tested and deployed.

### Out of Scope

The following issues are strictly out of scope:

- Denial of Service (DoS) through network volume/brute force beyond defined application rate limits.
- Social engineering, phishing, or physical attacks against employees or infrastructure.
- Issues related to third-party services (e.g. PayPal sandbox outages).

## Core Security Architectures Implemented

1. **Untrusted Document Isolation**: Uploaded PDF files are never executed and are inspected for magic headers (`%PDF-`), valid object trees, password locks, and memory limits before chunked raster rendering.
2. **Object-Level Authorization (IDOR Prevention)**: Download endpoints and job statuses strictly verify that the requesting authenticated user owns the document record.
3. **Database Financial Idempotency**: Payment transaction IDs enforce PostgreSQL unique constraints (`provider`, `transaction_id`) to mathematically prevent double-activation attacks.
4. **Encrypted & Single-Use Tokens**: Email verification and password reset workflows utilize cryptographic, single-use, time-limited tokens.
5. **Strict Document Retention**: Uploaded and processed PDF binaries are permanently purged after 7 days via automated cleanup routines.
