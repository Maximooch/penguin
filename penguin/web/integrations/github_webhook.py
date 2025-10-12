"""GitHub webhook handler for Penguin Agent.

Handles GitHub webhook events for @Penguin mentions, PR events, and issue events.
"""

import asyncio
import hashlib
import hmac
import logging
import os
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel

from penguin.project.git_manager import _get_github_app_client
from penguin.config import GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH, GITHUB_APP_INSTALLATION_ID

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/integrations/github", tags=["integrations"])


async def post_github_comment(repo_name: str, issue_number: int, comment_body: str) -> bool:
    """Post a comment to a GitHub issue or PR.

    Args:
        repo_name: Repository name (owner/repo)
        issue_number: Issue or PR number
        comment_body: Comment text

    Returns:
        True if successful, False otherwise
    """
    try:
        # Get GitHub client
        github_client = _get_github_app_client(
            GITHUB_APP_ID,
            GITHUB_APP_PRIVATE_KEY_PATH,
            GITHUB_APP_INSTALLATION_ID
        )

        if not github_client:
            logger.error("Failed to get GitHub client")
            return False

        # Get repository and issue
        repo = github_client.get_repo(repo_name)
        issue = repo.get_issue(issue_number)

        # Post comment
        issue.create_comment(comment_body)
        logger.info(f"Posted comment to {repo_name}#{issue_number}")
        return True

    except Exception as e:
        logger.error(f"Failed to post GitHub comment: {e}")
        return False


class GitHubWebhookPayload(BaseModel):
    """Base model for GitHub webhook payloads."""
    action: Optional[str] = None
    repository: Optional[Dict[str, Any]] = None
    sender: Optional[Dict[str, Any]] = None


def verify_github_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    """Verify GitHub webhook signature.

    Args:
        payload_body: Raw request body bytes
        signature_header: X-Hub-Signature-256 header value
        secret: Webhook secret

    Returns:
        True if signature is valid, False otherwise
    """
    if not signature_header:
        logger.warning("Missing X-Hub-Signature-256 header")
        return False

    if not signature_header.startswith("sha256="):
        logger.warning("Invalid signature format")
        return False

    # Extract signature from header
    expected_signature = signature_header.split("=", 1)[1]

    # Compute HMAC
    mac = hmac.new(secret.encode(), msg=payload_body, digestmod=hashlib.sha256)
    computed_signature = mac.hexdigest()

    # Constant-time comparison
    return hmac.compare_digest(computed_signature, expected_signature)


async def _build_review_prompt(pr: Any, files: list) -> str:
    """Build structured review prompt for LLM.

    Args:
        pr: GitHub PR object
        files: List of changed file objects

    Returns:
        Structured prompt string
    """
    prompt = f"""You are conducting a code review for a pull request. Please analyze the changes and provide constructive feedback.

## Pull Request Information
- **Title:** {pr.title}
- **Author:** {pr.user.login}
- **Branch:** `{pr.head.ref}` → `{pr.base.ref}`
- **Description:**
{pr.body or "No description provided"}

## Changed Files ({len(files)} files)

"""

    # Add each file's diff
    for file in files:
        # Truncate very long patches
        patch = file.patch or ""
        if len(patch) > 5000:
            patch = patch[:5000] + "\n... (truncated)"

        prompt += f"""
### 📄 `{file.filename}` ({file.status})
**Changes:** +{file.additions} -{file.deletions} lines

```diff
{patch}
```

"""

    # Add review guidelines
    prompt += """
## Review Guidelines

Please provide a thorough code review covering:

1. **🐛 Code Quality & Bugs**
   - Are there any logic errors or potential bugs?
   - Are edge cases handled properly?
   - Is error handling appropriate?

2. **✨ Best Practices**
   - Does the code follow language/framework best practices?
   - Are naming conventions clear and consistent?
   - Is the code DRY (Don't Repeat Yourself)?

3. **⚡ Performance**
   - Are there any performance concerns?
   - Could algorithms or data structures be optimized?

4. **🔒 Security**
   - Are there any security vulnerabilities?
   - Is user input properly validated/sanitized?
   - Are credentials or secrets exposed?

5. **📚 Maintainability**
   - Is the code readable and well-documented?
   - Are complex sections adequately commented?
   - Will other developers understand this code?

## Output Format

Please structure your review as follows:

**Summary:** (2-3 sentences about overall code quality)

**Strengths:** (What's done well)
- Point 1
- Point 2

**Issues Found:** (If any, with severity: Critical/Major/Minor)
- [Severity] Issue description and location
- Suggested fix

**Suggestions:** (Optional improvements)
- Suggestion 1
- Suggestion 2

**Verdict:** APPROVE / REQUEST_CHANGES / COMMENT

Think through your review step-by-step, considering each aspect carefully.
"""

    return prompt


def extract_mention_command(text: str) -> Optional[Dict[str, Any]]:
    """Extract @Penguin mention and command from text.

    Args:
        text: Comment body text

    Returns:
        Dict with command info if found, None otherwise

    Examples:
        "@Penguin review" -> {"command": "review", "args": []}
        "@Penguin fix tests" -> {"command": "fix", "args": ["tests"]}
        "@Penguin plan implementation" -> {"command": "plan", "args": ["implementation"]}
    """
    # Match @Penguin mentions (case-insensitive)
    mention_pattern = r'@Penguin\s+(\w+)(?:\s+(.*))?'
    match = re.search(mention_pattern, text, re.IGNORECASE)

    if not match:
        return None

    command = match.group(1).lower()
    args_str = match.group(2) or ""
    args = args_str.split() if args_str else []

    return {
        "command": command,
        "args": args,
        "full_text": match.group(0)
    }


async def handle_issue_comment(payload: Dict[str, Any], core: Any) -> None:
    """Handle issue_comment webhook event.

    Args:
        payload: Webhook payload
        core: PenguinCore instance
    """
    action = payload.get("action")
    comment = payload.get("comment", {})
    issue = payload.get("issue", {})
    repository = payload.get("repository", {})

    # Only process "created" comments
    if action != "created":
        logger.debug(f"Ignoring issue_comment action: {action}")
        return

    comment_body = comment.get("body", "")
    comment_user = comment.get("user", {}).get("login", "unknown")
    issue_number = issue.get("number")
    is_pr = "pull_request" in issue
    repo_name = repository.get("full_name")

    logger.info(f"Processing comment from {comment_user} on {'PR' if is_pr else 'issue'} #{issue_number} in {repo_name}")

    # Check for @Penguin mention
    mention = extract_mention_command(comment_body)
    if not mention:
        logger.debug("No @Penguin mention found in comment")
        return

    command = mention["command"]
    args = mention["args"]

    logger.info(f"@Penguin command detected: {command} {args}")

    # Validate command is enabled
    enabled_commands = os.getenv("PENGUIN_ENABLED_COMMANDS", "review,fix,plan,summarize").split(",")
    if command not in enabled_commands:
        logger.warning(f"Command '{command}' not in enabled commands: {enabled_commands}")
        # TODO: Post comment saying command is not enabled
        return

    # Generate conversation ID for this PR/issue (for persistent context)
    # Format: github-{repo_name}-{pr/issue}-{number}
    conversation_id = f"github-{repo_name.replace('/', '-')}-{'pr' if is_pr else 'issue'}-{issue_number}"
    logger.info(f"Using conversation ID: {conversation_id}")

    # Route to appropriate handler (pass conversation_id for persistence)
    if command == "review":
        await handle_review_command(payload, core, is_pr, issue_number, repo_name, conversation_id)
    elif command == "fix":
        await handle_fix_command(payload, core, args, is_pr, issue_number, repo_name, conversation_id)
    elif command == "plan":
        await handle_plan_command(payload, core, is_pr, issue_number, repo_name, conversation_id)
    elif command == "summarize":
        await handle_summarize_command(payload, core, is_pr, issue_number, repo_name, conversation_id)
    else:
        # Handle as general follow-up question in context of the PR/issue
        logger.info(f"Handling as follow-up question: {command} {args}")
        await handle_followup_question(payload, core, comment_body, is_pr, issue_number, repo_name, conversation_id)


async def handle_review_command(
    payload: Dict[str, Any],
    core: Any,
    is_pr: bool,
    issue_number: int,
    repo_name: str,
    conversation_id: str
) -> None:
    """Handle @Penguin review command with persistent conversation.

    Args:
        payload: GitHub webhook payload
        core: PenguinCore instance
        is_pr: Whether this is a PR or issue
        issue_number: PR/issue number
        repo_name: Repository name (owner/repo)
        conversation_id: Persistent conversation ID for this PR/issue
    """
    if not is_pr:
        logger.info("Review command only works on PRs")
        await post_github_comment(
            repo_name,
            issue_number,
            "👋 The `review` command only works on pull requests. Please use it in a PR comment."
        )
        return

    logger.info(f"Starting review for PR #{issue_number} in {repo_name} (conversation: {conversation_id})")

    # Post acknowledgment comment
    await post_github_comment(
        repo_name,
        issue_number,
        f"🐧 **Penguin is reviewing PR #{issue_number}**\n\nI'm analyzing the changes now. This may take a moment..."
    )

    try:
        # Fetch PR details and changed files
        github_client = _get_github_app_client(
            GITHUB_APP_ID,
            GITHUB_APP_PRIVATE_KEY_PATH,
            GITHUB_APP_INSTALLATION_ID
        )

        if not github_client:
            await post_github_comment(
                repo_name,
                issue_number,
                "❌ **Review failed:** Could not authenticate with GitHub API."
            )
            return

        repo = github_client.get_repo(repo_name)
        pr = repo.get_pull(issue_number)

        # Get changed files
        files = list(pr.get_files())

        # Check limits
        max_files = int(os.getenv("PENGUIN_MAX_FILES_PER_REVIEW", "10"))
        max_lines = int(os.getenv("PENGUIN_MAX_DIFF_LINES", "1000"))

        total_lines = sum(file.additions + file.deletions for file in files)

        if len(files) > max_files or total_lines > max_lines:
            await post_github_comment(
                repo_name,
                issue_number,
                f"⚠️ **PR is too large for automatic review**\n\n"
                f"- Files changed: {len(files)} (limit: {max_files})\n"
                f"- Lines changed: {total_lines} (limit: {max_lines})\n\n"
                f"Please break this PR into smaller chunks for review."
            )
            return

        # Construct review prompt
        review_prompt = await _build_review_prompt(pr, files)

        # Feed to Penguin's LLM with persistent conversation
        logger.info(f"Sending {len(files)} files to Penguin for review (conversation: {conversation_id})")
        result = await core.process(
            input_data={"text": review_prompt},
            conversation_id=conversation_id,  # Enable persistence and follow-up questions
            max_iterations=3,
            streaming=False
        )

        # Extract review response
        review_response = result.get("assistant_response", "No response generated")

        # Post review results
        await post_github_comment(
            repo_name,
            issue_number,
            f"✅ **Review complete!**\n\n{review_response}\n\n---\n*💡 You can ask follow-up questions like: `@Penguin explain the security concern` or `@Penguin how would you fix line 407?`*"
        )

        logger.info(f"Successfully completed review for PR #{issue_number} (saved to conversation: {conversation_id})")

    except Exception as e:
        logger.error(f"Failed to review PR #{issue_number}: {e}", exc_info=True)
        await post_github_comment(
            repo_name,
            issue_number,
            f"❌ **Review failed:** {str(e)}"
        )


async def handle_fix_command(
    payload: Dict[str, Any],
    core: Any,
    args: list,
    is_pr: bool,
    issue_number: int,
    repo_name: str,
    conversation_id: str
) -> None:
    """Handle @Penguin fix command with persistent conversation."""
    fix_target = " ".join(args) if args else "errors"

    logger.info(f"Starting fix for '{fix_target}' on {'PR' if is_pr else 'issue'} #{issue_number} in {repo_name} (conversation: {conversation_id})")

    # TODO: Implement fix logic with conversation_id
    # 1. Analyze the issue/PR
    # 2. Create branch
    # 3. Apply fixes
    # 4. Push changes
    # 5. Create/update PR
    # Use conversation_id for context awareness

    logger.warning("Fix command not yet implemented")


async def handle_plan_command(
    payload: Dict[str, Any],
    core: Any,
    is_pr: bool,
    issue_number: int,
    repo_name: str,
    conversation_id: str
) -> None:
    """Handle @Penguin plan command with persistent conversation."""
    logger.info(f"Generating plan for {'PR' if is_pr else 'issue'} #{issue_number} in {repo_name} (conversation: {conversation_id})")

    # TODO: Implement plan logic with conversation_id
    # 1. Analyze the issue/PR description
    # 2. Generate implementation plan
    # 3. Post as comment with checklist
    # Use conversation_id for context awareness

    logger.warning("Plan command not yet implemented")


async def handle_summarize_command(
    payload: Dict[str, Any],
    core: Any,
    is_pr: bool,
    issue_number: int,
    repo_name: str,
    conversation_id: str
) -> None:
    """Handle @Penguin summarize command with persistent conversation."""
    logger.info(f"Summarizing {'PR' if is_pr else 'issue'} #{issue_number} in {repo_name} (conversation: {conversation_id})")

    # TODO: Implement summarize logic with conversation_id
    # 1. Fetch all comments and changes
    # 2. Generate summary
    # 3. Post as comment
    # Use conversation_id for context awareness

    logger.warning("Summarize command not yet implemented")


async def handle_followup_question(
    payload: Dict[str, Any],
    core: Any,
    comment_body: str,
    is_pr: bool,
    issue_number: int,
    repo_name: str,
    conversation_id: str
) -> None:
    """Handle general follow-up questions in context of a PR/issue.

    This allows users to ask questions like:
    - "@Penguin explain the security concern in detail"
    - "@Penguin how would you fix line 407?"
    - "@Penguin what are the performance implications?"

    Args:
        payload: GitHub webhook payload
        core: PenguinCore instance
        comment_body: Full comment text
        is_pr: Whether this is a PR or issue
        issue_number: PR/issue number
        repo_name: Repository name
        conversation_id: Persistent conversation ID
    """
    logger.info(f"Processing follow-up question on {'PR' if is_pr else 'issue'} #{issue_number} (conversation: {conversation_id})")

    try:
        # Extract the question (remove @Penguin mention)
        question = comment_body.replace("@Penguin", "").replace("@penguin", "").strip()

        if not question:
            await post_github_comment(
                repo_name,
                issue_number,
                "👋 I'm here! What would you like to know? Try asking:\n"
                "- `@Penguin review` - Review this PR\n"
                "- `@Penguin explain [something]` - Get detailed explanation\n"
                "- `@Penguin how would you fix [issue]?` - Get suggestions"
            )
            return

        # Process in context of existing conversation
        result = await core.process(
            input_data={"text": question},
            conversation_id=conversation_id,  # Use existing conversation context
            max_iterations=3,
            streaming=False
        )

        response = result.get("assistant_response", "I'm not sure how to answer that.")

        # Post response
        await post_github_comment(
            repo_name,
            issue_number,
            f"{response}"
        )

        logger.info(f"Successfully answered follow-up question on {'PR' if is_pr else 'issue'} #{issue_number}")

    except Exception as e:
        logger.error(f"Failed to answer follow-up question: {e}", exc_info=True)
        await post_github_comment(
            repo_name,
            issue_number,
            f"❌ Sorry, I encountered an error: {str(e)}"
        )


async def handle_pull_request(payload: Dict[str, Any], core: Any) -> None:
    """Handle pull_request webhook event.

    Args:
        payload: Webhook payload
        core: PenguinCore instance
    """
    action = payload.get("action")
    pr = payload.get("pull_request", {})
    pr_number = pr.get("number")
    repository = payload.get("repository", {})
    repo_name = repository.get("full_name")

    logger.info(f"Processing pull_request event: {action} for PR #{pr_number} in {repo_name}")

    # Handle different PR actions
    if action == "opened":
        logger.info(f"New PR opened: #{pr_number}")
        # TODO: Auto-review on open if enabled
    elif action == "synchronize":
        logger.info(f"PR updated: #{pr_number}")
        # TODO: Re-run checks if needed
    elif action == "closed":
        logger.info(f"PR closed: #{pr_number}")
        # TODO: Cleanup if needed


@router.post("/webhook")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """GitHub webhook endpoint.

    Receives and processes GitHub webhook events.
    """
    # Get webhook secret from environment
    webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not webhook_secret:
        logger.error("GITHUB_WEBHOOK_SECRET not configured")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    # Get signature from header
    signature_header = request.headers.get("X-Hub-Signature-256", "")

    # Read raw body for signature verification
    body_bytes = await request.body()

    # Verify signature
    if not verify_github_signature(body_bytes, signature_header, webhook_secret):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse payload
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Get event type
    event_type = request.headers.get("X-GitHub-Event", "unknown")
    logger.info(f"Received GitHub webhook: {event_type}")

    # Get core instance (attached to router by app.py)
    core = getattr(router, "core", None)
    if not core:
        logger.error("PenguinCore not available")
        raise HTTPException(status_code=500, detail="Core not initialized")

    # Validate repository if configured
    allowed_repo = os.getenv("GITHUB_REPOSITORY")
    repository = payload.get("repository")
    repo_name = repository.get("full_name") if repository else None

    # Log the payload for debugging
    if not repo_name:
        logger.warning(f"Webhook payload missing repository. Event: {event_type}, Keys: {list(payload.keys())}")

    if allowed_repo and repo_name and repo_name != allowed_repo:
        logger.warning(f"Webhook from unauthorized repo: {repo_name} (allowed: {allowed_repo})")
        raise HTTPException(status_code=403, detail="Unauthorized repository")

    # Route event to appropriate handler
    # Process in background to avoid timeout
    if event_type == "issue_comment":
        background_tasks.add_task(handle_issue_comment, payload, core)
    elif event_type == "pull_request":
        background_tasks.add_task(handle_pull_request, payload, core)
    elif event_type == "pull_request_review":
        logger.info("Received pull_request_review event (not yet handled)")
    elif event_type == "pull_request_review_comment":
        logger.info("Received pull_request_review_comment event (not yet handled)")
    elif event_type == "ping":
        logger.info("Received ping event from GitHub")
    else:
        logger.warning(f"Unhandled event type: {event_type}")

    # Return success
    return {"status": "ok", "event": event_type}
