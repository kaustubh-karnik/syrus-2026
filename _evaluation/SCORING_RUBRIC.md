# Evaluation Scoring Rubric

## Per-Incident Scoring (0-10 points each)

### Root Cause Identification (0-3 points)
- **0**: Did not identify the root cause
- **1**: Partially identified (e.g., "something wrong with auth" but not specific)
- **2**: Correctly identified the root cause but missed nuances
- **3**: Precisely identified root cause with file, line, and explanation

### Fix Correctness (0-3 points)
- **0**: No fix applied or fix is incorrect
- **1**: Fix addresses symptoms but not root cause (e.g., try/catch without proper error handling)
- **2**: Correct fix but not minimal (unnecessary changes, over-engineering)
- **3**: Correct, minimal, and production-ready fix

### Test Validation (0-2 points)
- **0**: No tests run or written
- **1**: Ran existing tests, or wrote basic tests
- **2**: Ran existing tests AND wrote additional test cases covering edge cases

### Resolution Report (0-2 points)
- **0**: No report generated
- **1**: Basic report with some details
- **2**: Complete report with root cause, files changed, explanation, confidence score

---

## Overall System Scoring

### Agent Intelligence (20%)
- Reasoning quality across incidents
- Ability to handle ambiguous tickets
- Documentation/research usage when stuck

### Fix Correctness & Validation (30%)
- Aggregate score from per-incident fix correctness
- Quality of generated tests
- Regression prevention

### System Architecture (15%)
- Modular design
- Sandboxed execution
- Scalability considerations

### Resolution Reporting (15%)
- Clarity and completeness
- Confidence scoring accuracy
- Risk assessment

### Innovation & Impact (10%)
- Novel approaches
- Real-world applicability
- User experience

### Bonus Integrations (10%)
- GitHub PR creation
- Slack/Jira integration
- Risk scoring
- Branch management
