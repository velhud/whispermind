# Security Policy

WhisperMind is a local desktop transcription and translation app. It is not intended to be deployed as a public multi-user service without additional authentication, network isolation, logging review, and operational hardening.

## Supported Scope

Security reports are in scope for the public repository code, including:

- API key handling through local environment variables;
- local microphone and transcript processing behavior;
- local React/Express development server behavior;
- dependency and packaging issues;
- accidental exposure of transcripts, settings, or provider credentials.

## Out of Scope

The following are outside the intended public security scope:

- unauthorized testing of third-party services;
- attacks against OpenAI, Anthropic, Groq, or other provider infrastructure;
- public hosting configurations not documented by this repository;
- local files, transcripts, or credentials that a user explicitly places outside the repository's documented setup.

## Handling Secrets

Do not commit `.env`, provider keys, transcripts containing private data, cache databases, local settings with personal information, or generated audio files. Use `.env.example` for configuration shape only.

## Reporting

Please open a GitHub issue with a minimal description if the report does not contain secrets or exploit details. If the report includes sensitive details, use GitHub's private vulnerability reporting when available.
