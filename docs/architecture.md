# Architecture Overview

## Purpose

This project is a local-first personal AI assistant. It should be useful on one Mac today while remaining modular enough to change models, interfaces, and tools later.

## Core rule

The language model can suggest an action, but it cannot perform an external or sensitive action on its own.

A separate permission layer decides whether an action is allowed and asks the user for approval when needed.

## Main components

- Interface: how I communicate with the assistant.
- Coordinator: receives a request and decides what should happen next.
- Model adapter: communicates with the selected language model, initially through Ollama.
- Memory adapter: reads and writes assistant memory.
- Data layer: stores canonical personal data in SQLite.
- Tool layer: defines actions the assistant may request, such as reading a local file or using a browser.
- Permission layer: evaluates requested actions and requires approval when appropriate.
- Browser adapter: future authenticated browser workflows, with manual login and no credentials stored in memory or logs.

## Information flow

User request → coordinator → model and/or tools → permission layer → approved action → result returned to user

## Initial scope

The first version uses one coordinator and one local model.

Future versions may add bounded worker agents. Worker agents will receive limited tasks and permissions from the coordinator rather than unrestricted access.

## Data boundaries

- Source code, tests, and documentation are committed to Git.
- Secrets, personal data, databases, browser state, logs, and model files remain local and are excluded from Git.
