# LOVE-AT-FIRST-BYTE

## PS-02: Autonomous Incident-to-Fix Engineering Agent  
**Track:** REZINIX AI

---

## UPDATED Demo Video
https://youtu.be/Zt_LsdGm2bo

---

## UPDATED PPT LINK
https://drive.google.com/file/d/1OiCrUJyG_DIxWZqjnzlJAxDTlml1EwO9/view?usp=sharing

---

## 1-PAGE SUMMARY DOC
https://drive.google.com/file/d/1hLrCwh7BtA3ZukWPtN1O7Po5rbuNzfQ9/view?usp=sharing

## Project Overview

Modern engineering teams rely on platforms such as GitHub, CI/CD pipelines, and issue trackers like Jira or Slack to manage production systems. While these tools help detect failures, resolving incidents still requires significant manual effort.

When a bug occurs, engineers must read incident tickets, inspect logs, explore the codebase, identify the root cause, implement fixes, and validate them through testing. As systems grow more complex and deployment cycles become faster, this process becomes slow and difficult to scale.

Our project introduces an **Agentic Engineering Platform** that automates the entire incident resolution workflow. The system acts as an **AI-powered engineering assistant** capable of understanding incident tickets, analyzing the codebase, generating fixes, applying patches, and validating them through automated tests.

---

## Problem Statement

Build an **Agentic Engineering Platform** that autonomously resolves software incidents — from interpreting natural language tickets to applying verified fixes and generating production-ready changes.

---

## Solution

We developed an **Autonomous Incident-to-Fix Agent** that performs the complete debugging lifecycle automatically.

The system:

- Interprets incident tickets using LLMs  
- Retrieves relevant code from the repository  
- Identifies the root cause of the issue  
- Generates minimal code fixes  
- Applies patches to the repository  
- Validates fixes using automated tests in a sandbox environment  
- Generates a structured resolution report  

This approach reduces **manual debugging**, speeds up **incident resolution**, and improves **developer productivity**.

---

## System Architecture

The system follows a modular agent workflow:

```
Incident Ticket
      ↓
Ticket Analyzer
      ↓
Vector Search
      ↓
Fix Generator
      ↓
Patch Applier
      ↓
Sandbox Validation
      ↓
Resolution Explanation
```

---

## Key Features

**Intelligent Incident Understanding**  
Uses LLMs to interpret incident tickets and extract important debugging information.

**Automated Codebase Analysis**  
Uses vector search over repository embeddings to retrieve relevant code sections.

**Autonomous Fix Generation**  
Automatically generates minimal and safe code fixes.

**Safe Patch Application**  
Applies generated patches directly to the repository.

**Sandbox-Based Validation**  
Runs automated tests in an isolated environment to verify the fix and prevent regressions.

**Resolution Reporting**  
Generates a structured explanation including root cause, changes made, and validation results.

---

## Repository Used for Testing

The system operates on the following repository:

https://github.com/Rezinix-AI/shopstack-platform

This repository simulates a microservices application with intentionally introduced bugs and test cases.

---

## Technology Stack

- LangGraph  
- Large Language Models (LLMs)  
- Supabase + pgvector  
- Streamlit  
- Docker  
- Python / Node.js  

---

## Workflow

1. User provides a GitHub repository link  
2. Repository is indexed and embedded  
3. Incident ticket is analyzed  
4. Relevant code is retrieved  
5. AI generates a fix  
6. Patch is applied  
7. Tests run inside a sandbox  
8. A validated fix and explanation are produced  