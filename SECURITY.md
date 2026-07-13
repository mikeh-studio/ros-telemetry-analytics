# Security Policy

## Supported versions

Security fixes are applied to the latest release on the default branch.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private
security advisory workflow for the repository and include reproduction steps,
affected inputs, and the expected impact.

The project treats downloaded archives and ROS bag metadata as untrusted input.
Archive extraction rejects links, special files, absolute paths, and parent-path
traversal. Analysis reads message metadata and raw payload boundaries but does
not deserialize message bodies.
