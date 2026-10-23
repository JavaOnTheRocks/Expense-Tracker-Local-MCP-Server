# Expense Tracker MCP Server

**With this MCP Server Track expenses using any MCP-compatible host platform, including ChatGPT, Claude, and personal AI assistants.**

An open-source Python MCP server that exposes expense-management tools to compatible AI assistants and MCP clients. Instead of manually navigating an expense-tracking application, users can express their requests in natural language and let the AI assistant invoke the appropriate tools.


## Table of Contents

- [Overview](#-overview)
- [Problem Statement](#-problem-statement)
- [Solution](#-solution)
- [Features](#-features)
- [Demo Video](#-demo-video)
- [Technology Stack](#-technology-stack)
- [Architecture](#-architecture)
- [Connect to the Hosted MCP Server](#-connect-to-the-hosted-mcp-server)
- [Available MCP Tools](#-available-mcp-tools)
- [Run Locally](#-run-locally)
- [Environment Configuration](#-environment-configuration)
- [Project Structure](#-project-structure)
- [Future Improvements](#-future-improvements)
- [License](#-license)

---

## Overview

Traditional expense tracking often requires users to open an application, navigate forms, enter transaction details, select categories, and review reports separately.

This project explores a more conversational approach.

With the Expense Tracker MCP Server, a user can ask a compatible AI assistant:

> "Add ₹250 for lunch today under Food."

The AI assistant interprets the request and calls the appropriate tool exposed by the MCP server. The server processes the operation and stores expense data using SQLite.

Users can also request expense lists, summaries, updates, and deletions through supported tools.

The project demonstrates how the **Model Context Protocol (MCP)** can connect AI assistants to application functionality through structured, callable tools.

## Problem Statement

Managing everyday expenses can involve repetitive manual work.

Common friction points include:

- Manually entering transaction amounts and descriptions.
- Selecting categories for individual expenses.
- Navigating between screens to review transactions.
- Applying filters and reviewing spending summaries.

Traditional forms remain useful, but conversational interfaces can make supported workflows more convenient.

**Goal:** Build an MCP server that makes expense-management functionality accessible through natural-language interactions with compatible AI assistants.

## Solution

The Expense Tracker MCP Server exposes expense-management functionality through MCP tools.

Instead of requiring users to interact with a custom interface for every operation, a compatible AI assistant can interpret their requests and invoke the relevant tools.

### Example

**User:**
> Add ₹500 for groceries today under Food.

**AI assistant:** Interprets the request and selects the expense-creation tool.

**MCP server:** Receives the tool arguments, validates the input, and processes the expense operation.

**Database:** Stores the expense record.

The assistant can then communicate the result to the user.

Actual results depend on a successful MCP connection, correct tool execution, and the current server configuration.

---

## Features

- **Natural-language expense entry:** Add expenses using conversational requests.
- **Expense listing:** Retrieve transactions within a specified date range.
- **Spending summaries:** Summarize expenses by category for a date range.
- **Expense updates:** Modify supported fields of an existing expense.
- **Expense deletion:** Delete an expense using its identifier.
- **SQLite storage:** Store expense records in a relational database.
- **MCP integration:** Expose expense operations as tools to compatible MCP clients.
- **Cloud deployment:** A hosted MCP endpoint is configured for the project.
- **Python implementation:** Built with Python and FastMCP.

---

## Demo Video


▶️ **[Watch the Project Demo on YouTube](https://youtu.be/tkY1E3Tor3c)**

In this demo, you'll see how to connect the remote MCP server to Claude and manage expenses using natural-language prompts.


---

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Application implementation |
| FastMCP | Building and exposing MCP tools |
| Model Context Protocol (MCP) | Communication between compatible AI clients and the server |
| SQLite | Relational database for expense records |
| FastMCP Cloud | Hosting the remote MCP server |

### Why MCP?

MCP provides a standardized way for compatible AI applications to discover and invoke tools exposed by external services.

Instead of building a separate AI integration for every expense-management operation, the server exposes its functionality through MCP.

This allows supported MCP clients to interact with the tools using their existing AI interfaces.

---

## Architecture

                        ```text
                        ┌─────────────────────────────┐
                        │            User             │
                        │                             │
                        │ "Add ₹250 for lunch today"  │
                        └──────────────┬──────────────┘
                                    │
                                    ▼
                        ┌─────────────────────────────┐
                        │     AI Assistant / Client   │
                        │                             │
                        │ Interprets the request and  │
                        │ selects the appropriate tool│
                        └──────────────┬──────────────┘
                                    │
                                    │ MCP tool call
                                    ▼
                        ┌─────────────────────────────┐
                        │   Expense Tracker MCP       │
                        │           Server            │
                        │                             │
                        │ Python + FastMCP            │
                        │                             │
                        │ • Add expense               │
                        │ • List expenses             │
                        │ • Summarize expenses        │
                        │ • Update expense            │
                        │ • Delete expense            │
                        └──────────────┬──────────────┘
                                    │
                                    ▼
                        ┌─────────────────────────────┐
                        │        SQLite Database      │
                        │                             │
                        │ Expense records             │
                        └─────────────────────────────┘
                        ```

### How the architecture works

1. The user sends a natural-language request to an AI assistant.
2. The assistant interprets the request and selects an appropriate available tool.
3. The MCP client sends the tool call to the MCP server.
4. The server validates the supplied arguments and executes the operation.
5. The server returns the result to the client.
6. The AI assistant presents the result to the user.

**Important:** MCP provides the tool-communication layer. Natural-language understanding is performed by the connected AI assistant, not by MCP itself.

---

## Connect to the Hosted MCP Server

The project has a hosted MCP endpoint configured on FastMCP Cloud.

### Hosted endpoint

```text
https://expense-tracker-mcp-server-ak.fastmcp.app/mcp
```

### Step 1: Choose an MCP-compatible client

Use an AI application or MCP client that supports remote MCP servers over Streamable HTTP.

Remote MCP configuration and authentication requirements vary between clients. Follow the connection instructions for your chosen application.

### Step 2: Add the server

In your client's MCP server settings, add a remote server using the endpoint above.

Where the client requests a transport type, select Streamable HTTP if supported and required by the client.

Do not assume that every AI assistant supports adding remote MCP servers directly.

### Step 3: Complete any required connection or authentication flow

If the client requires authentication, follow the configured authentication flow.

**Current implementation note:** Authentication has not yet been fully implemented and verified for the demonstration. The hosted endpoint may therefore require additional configuration before tools can be used successfully.

Do not provide personal financial data until the deployment, database configuration, and access controls have been verified.

### Step 4: Verify the available tools

After a successful connection, inspect the tools exposed by the server.

Expected expense-management operations include:

- `add_expense`
- `list_expenses`
- `summarize`
- `update_expense`
- `delete_expense`

The tools must be discoverable and executable before the client can use them.

### Step 5: Try a test request

For example:

> Add ₹250 for lunch today under Food.

Then ask:

> Show my expenses for today.

Finally:

> Summarize my expenses by category for October 2026.

Use test data and verify the returned results. These are example prompts, not a guarantee that the current hosted deployment is already working.



## Available MCP Tools

The server exposes the following expense-management operations.

| Tool | Purpose | Main arguments |
|---|---|---|
| `add_expense` | Create an expense | `date`, `amount`, `category`, `subcategory`, `note` |
| `list_expenses` | Retrieve expenses within a date range | `start_date`, `end_date` |
| `summarize` | Summarize spending by category | `start_date`, `end_date`, optional `category` |
| `update_expense` | Update an existing expense | `expense_id` and supported fields |
| `delete_expense` | Delete an expense | `expense_id` |

### `add_expense`

Creates an expense record.

Example user request:

```text
Add ₹250 for lunch today under Food.
```

### `list_expenses`

Retrieves expenses between a start date and an end date.

Example user request:

```text
List my expenses from 1 October 2026 to 23 October 2026.
```

### `summarize`

Calculates a spending summary grouped by category for a specified date range. An optional category can narrow the summary.

Example user request:

```text
Summarize my Food expenses for October 2026.
```

### `update_expense`

Updates an existing expense using its identifier and supported fields.

Example user request:

```text
Change my selected lunch expense from ₹250 to ₹300.
```

### `delete_expense`

Deletes an expense using its identifier.

Example user request:

```text
Delete the expense I selected.
```

The assistant must identify the correct record before performing the operation.

---

## Run Locally

You can run the project locally for development and testing.

### Prerequisites

Install the following:

- Python version compatible with the project's dependency configuration.
- Git.
- A terminal such as PowerShell, Command Prompt, or Bash.
- An MCP-compatible client for testing tool interactions.

### Step 1: Clone the repository

Replace the placeholder with your actual public GitHub repository URL.

```bash
git clone https://github.com/JavaOnTheRocks/Expense-Tracker-Local-MCP-Server
cd <Remote-MCP-Server>
```

### Step 2: Create a virtual environment

**Windows — PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Windows — Command Prompt**

```bat
python -m venv .venv
.venv\Scripts\activate.bat
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install the project dependencies

If the repository contains a `pyproject.toml` with the package and its dependencies configured, install the project in editable mode:

```bash
python -m pip install --upgrade pip
pip install -e .
```

Use the installation method that matches the files committed to the repository.


### Step 4: Start the MCP server

The exact launch command depends on the entry point and transport configured in the project.

If the package uses the `src/remote_mcp_server/main.py` entry point and the installed FastMCP CLI supports the corresponding command, start it with:

```bash
fastmcp run src/remote_mcp_server/main.py
```

If your project specifies a different command in its deployment configuration or package scripts, use that command instead.

### Step 5: Test the server

Verify that:

1. The process starts without errors.
2. The MCP endpoint is available on the configured local address.
3. The MCP client can connect using the supported transport.
4. The client discovers the expense-management tools.
5. A test expense can be added and retrieved.
6. The summary tool returns the expected result.


## Project Structure

The following is an illustrative structure based on the known application entry point. Adjust it to match the actual files in your repository before publishing.

                    ```text
                    expense-tracker-mcp-server/
                    │
                    ├── src/
                    │   └── remote_mcp_server/
                    │       ├── __init__.py
                    │       └── main.py
                    │
                    ├── categories.json
                    ├── pyproject.toml
                    ├── requirements.txt
                    ├── .gitignore
                    ├── .env.example
                    ├── LICENSE
                    └── README.md
                    ```

Include only files that actually exist in your project.

If the category data file is stored inside the Python package or another directory, document its actual location.

### Important repository files

- `main.py` — MCP server implementation and expense-management tools.
- `categories.json` — Expense category data, if included in the repository.
- `pyproject.toml` — Package configuration and dependencies, if used.
- `requirements.txt` — Python

## Future Improvements

The goal is to evolve the Expense Tracker MCP Server into a secure, scalable, and production-ready expense management system that works with any compatible MCP host.

### 1. PostgreSQL Database Integration
- Replace SQLite with PostgreSQL for more reliable, scalable, multi-user data storage.
- Use connection pooling and asynchronous database operations to handle concurrent requests efficiently.
- Support persistent database storage in production environments.

### 2. Authentication & Authorization
- Strengthen OAuth 2.0 authentication and integrate Auth0 for user identity management.
- Validate access tokens, including their issuer, audience, expiration, and signature.
- Implement authorization checks for every tool that accesses or modifies expense data.
- Apply the principle of least privilege to ensure users can perform only authorized actions.
- Support secure authentication flows for compatible MCP clients and host platforms.

### 3. Strict Multi-User Data Isolation
- Ensure every authenticated user can access **only their own expense records**.
- Associate each database record with a trusted, server-verified user identity.
- Never trust user IDs supplied through prompts, tool arguments, or other client-controlled input.
- Enforce user-scoped database queries for listing, summarizing, updating, and deleting expenses.
- Explore PostgreSQL Row-Level Security (RLS) as an additional database-level isolation layer.
- Add automated tests to verify that one user cannot read, modify, or delete another user's records.

### 4. Security & Safety Improvements
- Validate and sanitize all tool inputs, including dates, amounts, categories, and text fields.
- Use parameterized database queries to prevent SQL injection.
- Add sensible limits to date ranges, result sizes, and request frequency.
- Implement rate limiting and appropriate error handling to reduce abuse.
- Avoid exposing access tokens, secrets, database credentials, or sensitive personal information in logs and error messages.
- Store secrets in environment variables or a dedicated secrets manager rather than committing them to the repository.
- Use encrypted connections for database communication and HTTPS for network traffic.
- Add audit logging for sensitive operations while avoiding unnecessary storage of personal financial data.

---

> **Note:** The items above represent planned improvements, not necessarily features already implemented in the current version.

## License

This project is licensed under the **MIT License**. You are free to use, modify, distribute, and use the software commercially, subject to the terms of the license.

See the [LICENSE](LICENSE) file for the complete license text.