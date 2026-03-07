# Changelog

All notable changes to this project will be documented in this file.

## v0.3.4 - 2026-03-06

- fix(cli): Resolve version from installed package metadata first to avoid `v0.0.0` on Windows/installed runs.
- fix(stdio-acp): Keep receive loop alive on oversized chunks (`Separator is not found, and chunk exceed the limit`), avoiding unexpected gateway exit on Windows.
- fix(cli): Add console symbol fallback for non-Unicode terminals (GBK/Windows), preventing startup crashes caused by `UnicodeEncodeError`.

