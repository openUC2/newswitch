"""Accounts of the FastAPI server: who may use the microscope, with which role.

- `auth`: logging in, tokens, the middleware checking every request;
- `store`: the account database (users, roles, sessions, audit);
- `routes`: account management over HTTP (admin-only, except ``/auth/me``).

Recovery from a shell: `newswitch.tools.accounts`.
"""
