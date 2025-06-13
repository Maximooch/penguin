"""
Test script for token counting across session boundaries.

This script tests:
1. Basic token counting for different message types
2. Proper token accumulation in a single session
3. Token counting across session boundaries
4. Integration with the API client
"""

import asyncio
import os
import sys
from pathlib import Path
import logging

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from penguin.config import Config
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig
from penguin.system.conversation_manager import ConversationManager
from penguin.system.state import MessageCategory, Message, Session


# Setup logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("token_test")

# Import rich if available
try:
    from rich.console import Console # type: ignore
    console = Console()
    has_rich = True
except ImportError:
    has_rich = False

async def test_token_counting():
    """Run token counting tests"""
    logger.info("Starting token counting tests")
    
    # Initialize components
    config = Config.load_config()
    model_config = ModelConfig(
        model=config.model.default,
        provider=config.model.provider,
        api_base=config.api.base_url
    )
    api_client = APIClient(model_config=model_config)
    
    # Test direct token counting - fixed to pass a formatted message
    test_message = "This is a test message for token counting"
    tokens = api_client.count_tokens([{"role": "user", "content": test_message}])
    logger.info(f"Test message token count: {tokens}")
    
    # Test direct content token counting
    if hasattr(api_client.adapter, 'count_tokens'):
        content_tokens = api_client.adapter.count_tokens(test_message)
        logger.info(f"Direct content token count: {content_tokens}")
    
    # Initialize conversation manager
    conversation_manager = ConversationManager(
        model_config=model_config,
        api_client=api_client,
        system_prompt="You are a helpful assistant."
    )
    
    # Create a new conversation
    conversation_id = conversation_manager.create_new_conversation()
    logger.info(f"Created new conversation: {conversation_id}")
    
    # Manually update token counts in the session
    initial_session = conversation_manager.conversation.session
    if initial_session and hasattr(initial_session, 'update_token_counts'):
        initial_session.update_token_counts(lambda content: api_client.count_tokens(content) if hasattr(api_client, 'count_tokens') else len(str(content)) // 4)
    
    # Add messages to the conversation
    await conversation_manager.process_message("Hello, can you tell me about token counting?")
    
    # Get token usage
    usage1 = conversation_manager.get_token_usage()
    logger.info(f"After first message - Token usage: {usage1}")
    
    # Add more messages
    await conversation_manager.process_message("How do you handle session boundaries?")
    
    # Get updated token usage
    usage2 = conversation_manager.get_token_usage()
    logger.info(f"After second message - Token usage: {usage2}")
    logger.info(f"Token increase: {usage2['total'] - usage1['total']}")
    
    # Create a continuation session
    logger.info("Simulating a session boundary...")
    
    # Force creation of a continuation session
    session = conversation_manager.conversation.session
    new_session = conversation_manager.session_manager.create_continuation_session(session)
    conversation_manager.conversation.session = new_session
    
    # Get token usage after continuation
    usage3 = conversation_manager.get_token_usage()
    logger.info(f"After session boundary - Token usage: {usage3}")
    
    # Add message to the new session
    await conversation_manager.process_message("Let's continue our conversation about token counting across sessions")
    
    # Get final token usage
    usage4 = conversation_manager.get_token_usage()
    logger.info(f"After continuing conversation - Token usage: {usage4}")
    logger.info(f"Token increase after boundary: {usage4['total'] - usage3['total']}")
    
    # Check session-level token stats
    logger.info("Session level token statistics:")
    for session_id, stats in usage4.get("sessions", {}).items():
        logger.info(f"  Session {session_id}: {stats.get('total', 0)} tokens")
    
    logger.info("Token counting test completed successfully")

async def test_token_budgeting():
    """Test token budgeting and trimming functionality"""
    logger.info("\n=== Starting Token Budgeting Test ===")
    
    # Initialize components
    config = Config.load_config()
    model_config = ModelConfig(
        model=config.model.default,
        provider=config.model.provider,
        api_base=config.api.base_url
    )
    api_client = APIClient(model_config=model_config)
    
    # Set a much smaller max_tokens to ensure we go over budget
    model_config.max_tokens = 200  # Reduce from 500 to 200
    conversation_manager = ConversationManager(
        model_config=model_config,
        api_client=api_client,
        system_prompt="You are a helpful assistant."
    )
    
    # Set token counter function
    token_counter = api_client.count_tokens
    
    # Create a new conversation
    conversation_id = conversation_manager.create_new_conversation()
    logger.info(f"Created new conversation: {conversation_id}")
    
    # Get initial token allocation
    context_window = conversation_manager.context_window
    initial_usage = context_window.get_token_usage()
    logger.info(f"Initial token budget allocation:")
    for category in MessageCategory:
        budget = context_window.get_budget(category)
        logger.info(f"  {category.name}: {budget.min_tokens}-{budget.max_tokens} tokens (current: {budget.current_tokens})")
    
    # Add system message - highest priority
    system_msg = conversation_manager.conversation.add_message(
        role="system",
        content="This is a critical system instruction that should never be trimmed.",
        category=MessageCategory.SYSTEM,
        metadata={"priority": "high"}
    )
    system_msg.tokens = token_counter(system_msg.content)  # Calculate tokens
    
    # Add context message - high priority
    context_content = """This is important context information that should be preserved as long as possible.
    It contains reference material that the assistant needs to provide accurate responses.
    The content is somewhat lengthy to ensure it consumes a good amount of tokens."""
    context_msg = conversation_manager.conversation.add_message(
        role="system",
        content=context_content,
        category=MessageCategory.CONTEXT,
        metadata={"priority": "medium"}
    )
    context_msg.tokens = token_counter(context_msg.content)  # Calculate tokens
    
    # Add several dialog messages - medium priority
    for i in range(3):  # Add fewer dialog messages to control token count
        user_content = f"This is user message {i+1}. It contains content that will consume tokens."
        user_msg = conversation_manager.conversation.add_message(
            role="user",
            content=user_content,
            category=MessageCategory.DIALOG,
            metadata={"priority": "normal"}
        )
        user_msg.tokens = token_counter(user_msg.content)  # Calculate tokens
        
        assistant_content = f"This is assistant response {i+1}. It provides a detailed answer to the user query."
        assistant_msg = conversation_manager.conversation.add_message(
            role="assistant",
            content=assistant_content,
            category=MessageCategory.DIALOG,
            metadata={"priority": "normal"}
        )
        assistant_msg.tokens = token_counter(assistant_msg.content)  # Calculate tokens
    
    # Add system output message - lowest priority
    output_msg = conversation_manager.conversation.add_message(
        role="system",
        content="This is a system output message with lower priority that would be trimmed first.",
        category=MessageCategory.SYSTEM_OUTPUT,
        metadata={"priority": "low"}
    )
    output_msg.tokens = token_counter(output_msg.content)  # Calculate tokens
    
    # Get the session
    session = conversation_manager.conversation.session
    
    # Print actual message counts before any processing
    logger.info(f"Added {len(session.messages)} messages to the session")
    for category in MessageCategory:
        category_msgs = [msg for msg in session.messages if msg.category == category]
        category_tokens = sum(msg.tokens for msg in category_msgs)
        logger.info(f"  {category.name}: {len(category_msgs)} messages, {category_tokens} tokens")
    
    # Calculate actual total tokens
    actual_total_tokens = sum(msg.tokens for msg in session.messages)
    logger.info(f"Total tokens in session: {actual_total_tokens}")
    
    # Reset the context window token usage to match what's in the session
    context_window.reset_usage()  # Clear existing counts
    
    # Manually update token usage for each message
    for msg in session.messages:
        context_window.update_usage(msg.category, msg.tokens)
    
    # Get token usage before trimming
    pre_trim_usage = context_window.get_token_usage()
    pre_trim_total = sum(pre_trim_usage.get(str(category), 0) for category in MessageCategory)
    logger.info(f"Pre-trimming token usage (calculated): {pre_trim_total} tokens")
    
    # Display rich output if available
    if has_rich:
        console.print(f"\nPre-trimming token usage (rich):")
        console.print(context_window.format_token_usage_rich())
    
    # Force trimming - capture the return value to use later
    logger.info(f"Trimming session with {len(session.messages)} messages and {session.total_tokens} tokens")
    trimmed_session = context_window.process_session(session)
    
    # Reset context window state to match the trimmed session
    context_window.reset_usage()  # Clear existing counts
    for msg in trimmed_session.messages:
        context_window.update_usage(msg.category, msg.tokens)
    
    # Get token usage after trimming
    post_trim_usage = context_window.get_token_usage()
    post_trim_total = sum(post_trim_usage.get(str(category), 0) for category in MessageCategory)
    logger.info(f"Post-trimming token usage (calculated): {post_trim_total} tokens")
    
    # Display rich output if available
    if has_rich:
        console.print(f"\nPost-trimming token usage (rich):")
        console.print(context_window.format_token_usage_rich())
    
    # Print message counts by category after trimming
    logger.info(f"After trimming: {len(trimmed_session.messages)} messages total")
    for category in MessageCategory:
        category_msgs = [msg for msg in trimmed_session.messages if msg.category == category]
        category_tokens = sum(msg.tokens for msg in category_msgs)
        logger.info(f"  {category.name}: {len(category_msgs)} messages, {category_tokens} tokens")
    
    # Check which categories were trimmed by comparing actual message counts
    logger.info("\nTrimming results:")
    for category in MessageCategory:
        pre_msgs = [msg for msg in session.messages if msg.category == category]
        post_msgs = [msg for msg in trimmed_session.messages if msg.category == category]
        pre_tokens = sum(msg.tokens for msg in pre_msgs)
        post_tokens = sum(msg.tokens for msg in post_msgs)
        
        if len(pre_msgs) > len(post_msgs) or pre_tokens > post_tokens:
            logger.info(f"  {category.name}: Removed {len(pre_msgs) - len(post_msgs)} messages, {pre_tokens - post_tokens} tokens")
        else:
            logger.info(f"  {category.name}: Unchanged ({len(post_msgs)} messages, {post_tokens} tokens)")
    
    # Check message counts
    pre_count = len(session.messages)
    post_count = len(trimmed_session.messages)
    messages_removed = pre_count - post_count
    logger.info(f"\nMessage counts:")
    logger.info(f"  Before trimming: {pre_count} messages")
    logger.info(f"  After trimming: {post_count} messages")
    logger.info(f"  Messages removed: {messages_removed}")
    
    logger.info("\nToken budgeting test completed successfully")

async def test_incremental_vs_batch_trimming():
    """Test that incremental and batch trimming produce equivalent results"""
    logger.info("\n=== Testing Incremental vs. Batch Trimming ===")
    
    # Setup with larger token budget to avoid min_tokens warning
    config = Config.load_config()
    model_config = ModelConfig(
        model=config.model.default,
        provider=config.model.provider,
        api_base=config.api.base_url,
        max_tokens=5000  # Much larger to avoid any budget issues
    )
    api_client = APIClient(model_config=model_config)
    
    # Add more logging to diagnose token counting
    test_content = "This is a test message for token counting"
    test_tokens = api_client.count_tokens([{"role": "user", "content": test_content}])
    logger.info(f"API token counter test: '{test_content}' = {test_tokens} tokens")
    
    # Sample messages with more content to ensure they have non-zero token counts
    messages = [
        {"role": "system", "content": "System instructions that contain important guidelines.", "category": MessageCategory.SYSTEM},
        {"role": "system", "content": "Important context information that provides background.", "category": MessageCategory.CONTEXT},
        {"role": "user", "content": "First user message with a detailed question.", "category": MessageCategory.DIALOG},
        {"role": "assistant", "content": "First assistant response providing a comprehensive answer.", "category": MessageCategory.DIALOG},
        {"role": "user", "content": "Second user message following up on the previous response.", "category": MessageCategory.DIALOG},
        {"role": "assistant", "content": "Second assistant response that builds on the previous information.", "category": MessageCategory.DIALOG},
        {"role": "system", "content": "System output message containing diagnostic information.", "category": MessageCategory.SYSTEM_OUTPUT},
    ]
    
    # Test 1: Incremental adding (trims as it goes)
    incremental_mgr = ConversationManager(model_config=model_config, api_client=api_client)
    incremental_id = incremental_mgr.create_new_conversation()
    
    # Add messages one by one with logging
    logger.info("Adding messages incrementally with token counts:")
    for idx, msg in enumerate(messages):
        # Add message
        new_msg = incremental_mgr.conversation.add_message(
            role=msg["role"],
            content=msg["content"],
            category=msg["category"]
        )
        
        # Log the token count
        logger.info(f"Message {idx+1}: {new_msg.tokens} tokens")
    
    # Test 2: Batch processing (adds all then trims)
    batch_mgr = ConversationManager(model_config=model_config, api_client=api_client)
    batch_id = batch_mgr.create_new_conversation()
    
    # Get the session and context window from the manager
    batch_session = batch_mgr.conversation.session
    context_window = batch_mgr.context_window
    
    # Log token counter info
    if hasattr(context_window, 'token_counter'):
        logger.info(f"Token counter source: {context_window.token_counter.__module__ if hasattr(context_window.token_counter, '__module__') else 'unknown'}")
    
    # Add all messages at once
    for msg in messages:
        message = Message(
            role=msg["role"],
            content=msg["content"],
            category=msg["category"]
        )
        batch_session.messages.append(message)
    
    # Analyze session to set token counts
    logger.info("Analyzing batch session to set token counts")
    stats = context_window.analyze_session(batch_session)
    logger.info(f"Analysis results: {stats}")
    
    # Log token counts of batch messages
    logger.info("Batch message token counts:")
    for idx, msg in enumerate(batch_session.messages):
        logger.info(f"Message {idx+1}: {msg.tokens} tokens")
    
    # Now do the batch trim
    trimmed_session = context_window.process_session(batch_session)
    batch_mgr.conversation.session = trimmed_session
    
    # Compare results with more detailed logging
    incremental_tokens = incremental_mgr.get_token_usage()
    batch_tokens = batch_mgr.get_token_usage()
    
    logger.info("Incremental Addition Results:")
    logger.info(f"Total tokens: {incremental_tokens.get('total', 0)}")
    logger.info(f"Messages: {len(incremental_mgr.conversation.session.messages)}")
    
    logger.info("Batch Processing Results:")
    logger.info(f"Total tokens: {batch_tokens.get('total', 0)}")
    logger.info(f"Messages: {len(batch_mgr.conversation.session.messages)}")
    
    # Add rich formatting if available
    if has_rich:
        console.print("\nIncremental Addition Results:")
        console.print(incremental_mgr.context_window.format_token_usage_rich())
        
        console.print("\nBatch Processing Results:")
        console.print(batch_mgr.context_window.format_token_usage_rich())
    
    # Log differences
    logger.info(f"Token count difference: {incremental_tokens['total'] - batch_tokens['total']}")
    logger.info(f"Message count difference: {len(incremental_mgr.conversation.session.messages) - len(batch_mgr.conversation.session.messages)}")

async def test_multimodal_content_handling():
    """Test token counting and trimming with multi-modal content"""
    logger.info("\n=== Testing Multi-Modal Content Handling ===")
    
    # Setup with moderate token budget
    config = Config.load_config()
    model_config = ModelConfig(
        model=config.model.default,
        provider=config.model.provider,
        api_base=config.api.base_url,
        max_tokens=300  # Moderate budget that will force image trimming
    )
    api_client = APIClient(model_config=model_config)
    
    # Create a manager
    conversation_manager = ConversationManager(
        model_config=model_config,
        api_client=api_client
    )
    
    # Create a new conversation
    conversation_id = conversation_manager.create_new_conversation()
    
    # Add a system message
    conversation_manager.conversation.add_message(
        role="system",
        content="You are a helpful assistant.",
        category=MessageCategory.SYSTEM
    )
    
    # Add a message with an image reference
    # For test purposes, we'll simulate an image using a structured content format
    image_content = [
        {"type": "text", "text": "Here's an image:"},
        {"type": "image_url", "image_url": {"url": "https://example.com/image1.jpg"}}
    ]
    
    image_msg = conversation_manager.conversation.add_message(
        role="user",
        content=image_content,
        category=MessageCategory.DIALOG
    )
    # Simulate high token count for the image
    image_msg.tokens = 1000  # Images typically cost a lot of tokens
    
    # Add another image message
    image_content2 = [
        {"type": "text", "text": "And another image:"},
        {"type": "image_url", "image_url": {"url": "https://example.com/image2.jpg"}}
    ]
    
    image_msg2 = conversation_manager.conversation.add_message(
        role="user",
        content=image_content2,
        category=MessageCategory.DIALOG
    )
    # Simulate high token count for the second image
    image_msg2.tokens = 1000
    
    # Get token usage before trimming
    context_window = conversation_manager.context_window
    usage_before = context_window.get_token_usage()
    logger.info(f"Before image trimming - Total tokens: {usage_before['total']}")
    
    # Force image trimming
    session = conversation_manager.conversation.session
    stats = context_window.analyze_session(session)
    logger.info(f"Number of images detected: {stats['image_count']}")
    
    # Process the session (should trigger image trimming)
    trimmed_session = context_window.process_session(session)
    conversation_manager.conversation.session = trimmed_session
    
    # Check token usage after trimming
    usage_after = context_window.get_token_usage()
    logger.info(f"After image trimming - Total tokens: {usage_after['total']}")
    
    # Verify that image placeholders were created
    image_placeholders = 0
    for msg in trimmed_session.messages:
        if isinstance(msg.content, list):
            for part in msg.content:
                if isinstance(part, dict) and part.get("text", "").startswith("[Image removed"):
                    image_placeholders += 1
    
    logger.info(f"Image placeholders created: {image_placeholders}")
    logger.info(f"Token reduction from image trimming: {usage_before['total'] - usage_after['total']}")

async def test_cross_session_token_tracking():
    """Test token tracking across multiple session boundaries"""
    logger.info("\n=== Testing Cross-Session Token Tracking ===")
    
    # Setup components
    config = Config.load_config()
    model_config = ModelConfig(
        model=config.model.default,
        provider=config.model.provider,
        api_base=config.api.base_url,
        max_tokens=8000  # Use a higher value to avoid trimming during test
    )
    api_client = APIClient(model_config=model_config)
    
    # Initialize conversation manager with small max_messages_per_session
    conversation_manager = ConversationManager(
        model_config=model_config,
        api_client=api_client,
        max_messages_per_session=5  # Force session boundaries after 5 messages
    )
    
    # Create a new conversation
    conversation_id = conversation_manager.create_new_conversation()
    
    # Add a system message first to prime the conversation
    system_msg = conversation_manager.conversation.add_message(
        role="system",
        content="You are a helpful assistant for token counting tests.",
        category=MessageCategory.SYSTEM
    )
    system_msg.tokens = api_client.count_tokens(system_msg.content)
    
    # Messages with consistent lengths to make token counting more predictable
    messages = [
        "First message in session 1 with a consistent length.",
        "Second message in session 1 with a consistent length.",
        "Third message in session 1 with a consistent length.",
        "Fourth message in session 1 with a consistent length.",
        "Fifth message in session 1 with a consistent length.",
        "First message in session 2 with a consistent length.",
        "Second message in session 2 with a consistent length.",
        "Third message in session 2 with a consistent length.",
        "Fourth message in session 2 with a consistent length.",
        "Fifth message in session 2 with a consistent length.",
        "First message in session 3 with a consistent length.",
    ]
    
    # Storage for token tracking
    session_tokens = {}
    current_session_id = conversation_manager.get_current_session().id
    
    # Process messages one by one
    for i, msg in enumerate(messages):
        # Add message directly to avoid API calls
        user_msg = conversation_manager.conversation.add_message(
            role="user",
            content=msg,
            category=MessageCategory.DIALOG
        )
        # Calculate tokens for this message
        user_msg.tokens = api_client.count_tokens(user_msg.content)
        
        # Add a mock assistant response
        assistant_msg = conversation_manager.conversation.add_message(
            role="assistant",
            content=f"Response to your message: {msg}",
            category=MessageCategory.DIALOG
        )
        # Calculate tokens for this message
        assistant_msg.tokens = api_client.count_tokens(assistant_msg.content)
        
        # Force save after each message
        conversation_manager.save()
        
        # Check if we've crossed a session boundary
        new_session_id = conversation_manager.get_current_session().id
        if new_session_id != current_session_id:
            logger.info(f"Session boundary crossed: {current_session_id} → {new_session_id}")
            
            # Force save the index
            conversation_manager.session_manager._save_index(
                conversation_manager.session_manager.session_index
            )
            
            # Log token counts from the previous session
            previous_session = conversation_manager.session_manager.sessions.get(current_session_id)
            if previous_session:
                previous_tokens = previous_session[0].total_tokens
                logger.info(f"Previous session {current_session_id} token count: {previous_tokens}")
                session_tokens[current_session_id] = previous_tokens
            
            # Update current session ID
            current_session_id = new_session_id
    
    # Get token usage for the final session
    final_session = conversation_manager.get_current_session()
    final_tokens = final_session.total_tokens
    session_tokens[final_session.id] = final_tokens
    
    # Calculate total tokens directly from session objects
    direct_total = sum(session_tokens.values())
    
    # Get token usage via the conversation manager API
    api_usage = conversation_manager.get_token_usage()
    api_total = api_usage.get("total_all_sessions", api_usage.get("total", 0))
    
    # Report token usage across sessions
    logger.info("Token usage across sessions (direct count):")
    for session_id, tokens in session_tokens.items():
        logger.info(f"  Session {session_id}: {tokens} tokens")
    logger.info(f"Total tokens across all sessions (direct): {direct_total}")
    logger.info(f"Total tokens via API: {api_total}")
    
    # Verify token tracking in the session manager's index
    session_index = conversation_manager.session_manager.session_index
    for session_id, metadata in session_index.items():
        if session_id in session_tokens:
            logger.info(f"Session {session_id} - Index: {metadata.get('token_count', 'N/A')}, Calculated: {session_tokens[session_id]}")
    
    # Assert values match for validation
    assert abs(direct_total - api_total) < 50, f"Token counts don't match: {direct_total} vs {api_total}"

async def test_dynamic_budget_allocation():
    """Test dynamic allocation of token budget between categories"""
    logger.info("\n=== Testing Dynamic Budget Allocation ===")
    
    # This is a conceptual test - would require implementing the feature first
    
    # Setup with moderate token budget
    config = Config.load_config()
    model_config = ModelConfig(
        model=config.model.default,
        provider=config.model.provider,
        api_base=config.api.base_url,
        max_tokens=200  # Moderate budget
    )
    api_client = APIClient(model_config=model_config)
    
    # Create a manager with dynamic allocation enabled
    conversation_manager = ConversationManager(
        model_config=model_config,
        api_client=api_client
    )
    
    # Enable dynamic allocation in the context window
    # context_window = conversation_manager.context_window
    # context_window.enable_dynamic_allocation = True  # This would need to be implemented
    
    # Create a new conversation
    conversation_id = conversation_manager.create_new_conversation()
    
    # Add messages that would exceed the DIALOG category's standard budget
    # but can "borrow" from underused categories like SYSTEM_OUTPUT
    
    # For now, just log that this is a placeholder for a future test
    logger.info("Note: Dynamic budget allocation is a potential future enhancement")
    logger.info("This test serves as a placeholder for that functionality")

async def test_priority_based_trimming():
    """Test that messages are trimmed based on priority categories when token budget is exceeded"""
    logger.info("\n=== Testing Priority-Based Trimming ===")
    
    # Initialize with a VERY small token budget
    config = Config.load_config()
    model_config = ModelConfig(
        model=config.model.default,
        provider=config.model.provider,
        api_base=config.api.base_url,
        max_tokens=80  # Much smaller budget to force trimming
    )
    api_client = APIClient(model_config=model_config)
    
    # Create conversation manager with small token budget
    conversation_manager = ConversationManager(
        model_config=model_config,
        api_client=api_client,
        system_prompt=""  # Skip default system prompt to control tokens exactly
    )
    
    # Create a new conversation
    conversation_id = conversation_manager.create_new_conversation()
    logger.info(f"Created conversation with small token budget: {conversation_id}")
    
    # Set token counter function
    token_counter = api_client.count_tokens
    context_window = conversation_manager.context_window
    
    # First, check the default budget allocation
    logger.info("Initial token budget allocation:")
    for category in MessageCategory:
        budget = context_window.get_budget(category)
        logger.info(f"  {category.name}: {budget.min_tokens}-{budget.max_tokens} tokens (current: {budget.current_tokens})")
    
    # Create messages to fill each category
    # Note: We'll now use exact token counts for better control
    
    # SYSTEM message - should NEVER be trimmed
    system_content = "System instruction that must be preserved."
    system_msg = Message(
        role="system",
        content=system_content,
        category=MessageCategory.SYSTEM,
        metadata={"test_marker": "system_1"}
    )
    system_msg.tokens = token_counter(system_content)
    logger.info(f"Created SYSTEM message: {system_msg.tokens} tokens")
    
    # CONTEXT messages - should be preserved if possible
    context_content = "Important context information for the conversation."
    context_msg = Message(
        role="system",
        content=context_content,
        category=MessageCategory.CONTEXT,
        metadata={"test_marker": "context_1"}
    )
    context_msg.tokens = token_counter(context_content)
    logger.info(f"Created CONTEXT message: {context_msg.tokens} tokens")
    
    # DIALOG messages - medium priority
    user_content = "User question about priority-based message trimming?"
    user_msg = Message(
        role="user",
        content=user_content,
        category=MessageCategory.DIALOG,
        metadata={"test_marker": "dialog_user_1"}
    )
    user_msg.tokens = token_counter(user_content)
    logger.info(f"Created DIALOG user message: {user_msg.tokens} tokens")
    
    assistant_content = "Response explaining how priority-based trimming works."
    assistant_msg = Message(
        role="assistant",
        content=assistant_content,
        category=MessageCategory.DIALOG,
        metadata={"test_marker": "dialog_assistant_1"}
    )
    assistant_msg.tokens = token_counter(assistant_content)
    logger.info(f"Created DIALOG assistant message: {assistant_msg.tokens} tokens")
    
    # SYSTEM_OUTPUT messages - lowest priority, should be trimmed first
    output_content1 = "System output with lower priority information."
    output_msg1 = Message(
        role="system",
        content=output_content1,
        category=MessageCategory.SYSTEM_OUTPUT,
        metadata={"test_marker": "system_output_1"}
    )
    output_msg1.tokens = token_counter(output_content1)
    logger.info(f"Created SYSTEM_OUTPUT message 1: {output_msg1.tokens} tokens")
    
    output_content2 = "More system output with lowest priority."
    output_msg2 = Message(
        role="system",
        content=output_content2,
        category=MessageCategory.SYSTEM_OUTPUT,
        metadata={"test_marker": "system_output_2"}
    )
    output_msg2.tokens = token_counter(output_content2)
    logger.info(f"Created SYSTEM_OUTPUT message 2: {output_msg2.tokens} tokens")
    
    # Create a fresh session (to avoid auto-trimming during message addition)
    session = Session()
    
    # Add all messages to the session
    session.messages = [
        system_msg,
        context_msg, 
        user_msg,
        assistant_msg,
        output_msg1,
        output_msg2
    ]
    
    # Calculate total tokens to verify we've exceeded the budget
    total_tokens_before = sum(msg.tokens for msg in session.messages)
    logger.info(f"Total tokens before trimming: {total_tokens_before} tokens (budget: {model_config.max_tokens})")
    
    # Assert that we're guaranteed to exceed the budget now
    assert total_tokens_before > model_config.max_tokens, "Test setup error: Total tokens don't exceed budget"
    
    # Log pre-trimming message counts by category
    logger.info(f"\nPre-trimming message counts by category:")
    for category in MessageCategory:
        category_msgs = [msg for msg in session.messages if msg.category == category]
        category_token_count = sum(msg.tokens for msg in category_msgs)
        logger.info(f"  {category.name}: {len(category_msgs)} messages, {category_token_count} tokens")
    
    # Force trimming by processing the session
    logger.info(f"\nForcing trimming by processing session...")
    trimmed_session = context_window.process_session(session)
    
    # Log post-trimming message counts by category
    logger.info(f"\nPost-trimming message counts by category:")
    for category in MessageCategory:
        category_msgs = [msg for msg in trimmed_session.messages if msg.category == category]
        category_token_count = sum(msg.tokens for msg in category_msgs)
        logger.info(f"  {category.name}: {len(category_msgs)} messages, {category_token_count} tokens")
    
    # Calculate total tokens after trimming
    total_tokens_after = sum(msg.tokens for msg in trimmed_session.messages)
    logger.info(f"Total tokens after trimming: {total_tokens_after} tokens (budget: {model_config.max_tokens})")
    
    # VERIFICATION 1: Total tokens should be within budget
    assert total_tokens_after <= model_config.max_tokens, f"Trimming failed: {total_tokens_after} tokens still exceed budget"
    
    # VERIFICATION 2: SYSTEM messages should NEVER be trimmed
    system_msgs_before = [msg for msg in session.messages if msg.category == MessageCategory.SYSTEM]
    system_msgs_after = [msg for msg in trimmed_session.messages if msg.category == MessageCategory.SYSTEM]
    assert len(system_msgs_after) == len(system_msgs_before), "SYSTEM messages were trimmed incorrectly"
    
    # VERIFICATION 3: SYSTEM_OUTPUT should be trimmed first
    output_msgs_before = [msg for msg in session.messages if msg.category == MessageCategory.SYSTEM_OUTPUT]
    output_msgs_after = [msg for msg in trimmed_session.messages if msg.category == MessageCategory.SYSTEM_OUTPUT]
    
    # Only assert if we needed to trim SYSTEM_OUTPUT
    total_non_output_tokens = total_tokens_before - sum(msg.tokens for msg in output_msgs_before)
    if total_non_output_tokens < model_config.max_tokens:
        # We should have trimmed at least some SYSTEM_OUTPUT
        assert len(output_msgs_after) < len(output_msgs_before), "SYSTEM_OUTPUT messages weren't trimmed first"
    
    # Check markers to verify which messages survived trimming
    markers_after = [msg.metadata.get("test_marker") for msg in trimmed_session.messages if "test_marker" in msg.metadata]
    logger.info(f"Messages remaining after trimming: {markers_after}")
    
    # SYSTEM should always be preserved regardless of token pressure
    assert "system_1" in markers_after, "SYSTEM message was improperly trimmed"
    
    logger.info("\nPriority-based trimming test completed successfully")

async def test_conversation_continuity():
    """Test that conversation context is properly maintained across session boundaries"""
    logger.info("\n=== Testing Conversation Continuity Across Sessions ===")
    
    # Setup components
    config = Config.load_config()
    model_config = ModelConfig(
        model=config.model.default,
        provider=config.model.provider,
        api_base=config.api.base_url,
        max_tokens=8000  # Use a higher limit to avoid content trimming
    )
    api_client = APIClient(model_config=model_config)
    
    # Initialize conversation manager with small max_messages_per_session to force boundaries
    conversation_manager = ConversationManager(
        model_config=model_config,
        api_client=api_client,
        max_messages_per_session=5  # Force session boundaries after 5 messages
    )
    
    # Create a new conversation
    conversation_id = conversation_manager.create_new_conversation()
    logger.info(f"Created conversation {conversation_id}")
    
    # Add a SYSTEM message with unique identifiable content
    system_msg = conversation_manager.conversation.add_message(
        role="system",
        content="CRITICAL SYSTEM INSTRUCTION: This message must be preserved across all session boundaries. Secret code: ALPHA123",
        category=MessageCategory.SYSTEM,
        metadata={"test_marker": "system_instruction"}
    )
    
    # Add a CONTEXT message with unique identifiable content
    context_msg = conversation_manager.conversation.add_message(
        role="system",
        content="IMPORTANT CONTEXT: This context should be preserved across sessions. Reference number: CTX-456-BETA",
        category=MessageCategory.CONTEXT,
        metadata={"test_marker": "important_context"}
    )
    
    # Get the current session ID as the starting point
    original_session_id = conversation_manager.get_current_session().id
    
    # Add dialog messages to force session boundaries
    for i in range(1, 12):  # Add enough messages to create multiple session boundaries
        # Add user message
        user_msg = conversation_manager.conversation.add_message(
            role="user",
            content=f"User message {i}: This will help force session boundaries",
            category=MessageCategory.DIALOG
        )
        
        # Add assistant response
        assistant_msg = conversation_manager.conversation.add_message(
            role="assistant",
            content=f"Response {i}: Acknowledging your message about session boundaries",
            category=MessageCategory.DIALOG
        )
        
        # Save after each exchange
        conversation_manager.save()
    
    # Get the final session
    final_session_id = conversation_manager.get_current_session().id
    logger.info(f"Initial session: {original_session_id}, Final session: {final_session_id}")
    
    # Reconstruct the session chain from the session_index by following continued_from/continued_to links
    session_chain = []
    
    # Function to traverse the session chain in forward order
    def build_session_chain(start_id):
        chain = [start_id]
        current_id = start_id
        
        # Get the session index for easier access
        session_index = conversation_manager.session_manager.session_index
        
        # Loop through the continuation chain
        while current_id in session_index:
            metadata = session_index[current_id]
            if "continued_to" in metadata:
                next_id = metadata["continued_to"]
                chain.append(next_id)
                current_id = next_id
            else:
                break
                
        return chain
    
    # Build chain starting from original session
    session_chain = build_session_chain(original_session_id)
    
    # Report the session chain we've identified
    logger.info(f"Found session chain with {len(session_chain)} sessions:")
    for i, session_id in enumerate(session_chain):
        logger.info(f"  {i+1}. {session_id}")
    
    # Verify context preservation across sessions
    for i, session_id in enumerate(session_chain):
        # Load each session in the chain
        session_loaded = conversation_manager.load(session_id)
        assert session_loaded, f"Failed to load session {session_id}"
        
        session = conversation_manager.get_current_session()
        
        # Extract messages by category
        system_messages = [msg for msg in session.messages if msg.category == MessageCategory.SYSTEM]
        context_messages = [msg for msg in session.messages if msg.category == MessageCategory.CONTEXT]
        
        # Log session metadata
        logger.info(f"Session {i+1}/{len(session_chain)} ({session_id}):")
        
        # Check for system messages
        if i == 0:  # Original session
            # First session should have the original system message
            assert any("ALPHA123" in msg.content for msg in system_messages), "Original system instruction missing in first session"
            logger.info("  ✓ Original session contains system instruction with code ALPHA123")
        else:  # Continuation sessions
            # Continuation sessions should have the original system instruction carried forward
            has_original_system = any("ALPHA123" in msg.content for msg in system_messages)
            has_continuation_marker = any("Continuing from session" in msg.content for msg in system_messages)
            
            assert has_original_system, f"Session {session_id} is missing the original system instruction"
            assert has_continuation_marker, f"Session {session_id} is missing continuation marker"
            
            logger.info("  ✓ Continuation session preserved system instruction")
            logger.info("  ✓ Continuation session has proper transition marker")
        
        # Check context preservation
        has_context = any("CTX-456-BETA" in msg.content for msg in context_messages)
        assert has_context, f"Session {session_id} is missing the important context"
        logger.info("  ✓ Session preserved important context information")
        
        # Check metadata links - using session metadata directly
        metadata = session.metadata
        
        # Previous session link check
        if i > 0:  # Continuation sessions should link back to previous
            expected_previous = session_chain[i-1]
            if "continued_from" in metadata:
                actual_previous = metadata["continued_from"]
                assert actual_previous == expected_previous, f"Session links to wrong previous session. Expected: {expected_previous}, Got: {actual_previous}"
                logger.info(f"  ✓ Session correctly links to previous session {actual_previous}")
            else:
                logger.warning(f"  ⚠ Session missing 'continued_from' metadata")
            
        # Next session link check
        if i < len(session_chain) - 1:  # All but last session should link forward
            expected_next = session_chain[i+1]
            if "continued_to" in metadata:
                actual_next = metadata["continued_to"]
                assert actual_next == expected_next, f"Session links to wrong next session. Expected: {expected_next}, Got: {actual_next}"
                logger.info(f"  ✓ Session correctly links to next session {actual_next}")
            else:
                # Try loading it from the index in case it wasn't updated in the session object
                index_metadata = conversation_manager.session_manager.session_index.get(session_id, {})
                if "continued_to" in index_metadata:
                    actual_next = index_metadata["continued_to"]
                    assert actual_next == expected_next, f"Session index has wrong next link. Expected: {expected_next}, Got: {actual_next}"
                    logger.info(f"  ✓ Session index correctly links to next session {actual_next}")
                else:
                    logger.warning(f"  ⚠ Session missing 'continued_to' metadata (not in session or index)")
    
    # Final verification - load the last session and check if we can still access the original context
    conversation_manager.load(session_chain[-1])
    last_session = conversation_manager.get_current_session()
    
    # Check if system and context messages are still accessible
    all_content = " ".join([msg.content for msg in last_session.messages])
    assert "ALPHA123" in all_content, "Critical system instruction lost in final session"
    assert "CTX-456-BETA" in all_content, "Important context lost in final session"
    
    logger.info("\nConversation continuity test completed successfully")
    logger.info(f"Verified {len(session_chain)} sessions maintain proper context continuity")

class MockAPIClient:
    """Mock API client that can be configured to fail with specific messages"""
    
    def __init__(self):
        """Initialize the mock API client"""
        self.adapter = MockAdapter()
        self.error_trigger_words = ["error", "fail", "crash", "exception"]
        self.should_ignore_triggers = False
        
    def reset_triggers(self):
        """Reset the API client to ignore triggers for recovery testing"""
        self.should_ignore_triggers = True
        
    def count_tokens(self, content):
        """Count tokens and fail if content contains trigger words"""
        # Skip trigger check if we're in recovery mode
        if not self.should_ignore_triggers:
            content_str = str(content).lower()
            for trigger in self.error_trigger_words:
                if trigger in content_str:
                    raise Exception(f"Simulated API failure in count_tokens: Triggered by '{trigger}'")
        
        # Simple token counting simulation
        if isinstance(content, str):
            return len(content) // 4
        elif isinstance(content, list):
            return sum(len(str(item)) // 4 for item in content)
        else:
            return len(str(content)) // 4
            
    async def get_response(self, messages):
        """Get response and fail if any message contains trigger words"""
        # Skip trigger check if we're in recovery mode
        if not self.should_ignore_triggers:
            # Check if any message contains trigger words
            for msg in messages:
                content = str(msg.get("content", "")).lower()
                for trigger in self.error_trigger_words:
                    if trigger in content:
                        raise Exception(f"Simulated API failure in get_response: Triggered by '{trigger}'")
        
        # Return simple response if no triggers found
        return "This is a mock response"
    
    async def create_message(self, messages, max_tokens=None, temperature=None):
        """Create message and fail if any message contains trigger words"""
        # Skip trigger check if we're in recovery mode
        if not self.should_ignore_triggers:
            # Check if any message contains trigger words
            for msg in messages:
                content = str(msg.get("content", "")).lower()
                for trigger in self.error_trigger_words:
                    if trigger in content:
                        raise Exception(f"Simulated API failure in create_message: Triggered by '{trigger}'")
        
        # Mock response object if no triggers found
        return {
            "choices": [
                {
                    "message": {
                        "content": "This is a mock response"
                    }
                }
            ]
        }
        
    def process_response(self, response):
        """Process mock response"""
        if isinstance(response, dict) and "choices" in response:
            return response["choices"][0]["message"]["content"], []
        return "Mock response", []
        
    def set_system_prompt(self, prompt):
        """Mock setting system prompt"""
        pass

class MockAdapter:
    """Mock adapter for the mock API client"""
    
    def __init__(self):
        self.provider = "mock"
        
    def supports_system_messages(self):
        return True
    
    def format_messages(self, messages):
        return messages
    
    def count_tokens(self, content):
        # Simple token counting simulation
        if isinstance(content, str):
            return len(content) // 4
        elif isinstance(content, list):
            return sum(len(str(item)) // 4 for item in content)
        else:
            return len(str(content)) // 4
            
    def process_response(self, response):
        if isinstance(response, dict) and "choices" in response:
            return response["choices"][0]["message"]["content"], []
        return "Mock response", []

async def test_error_resilience():
    """Test system resilience when errors occur during processing"""
    logger.info("\n=== Testing Error Resilience ===")
    
    # Initialize with mock API client that fails on trigger words
    mock_api = MockAPIClient()
    
    # Create configuration with mock client
    model_config = ModelConfig(
        model="mock-model",
        provider="mock",
        api_base="https://mock-api.example.com",
        max_tokens=1000
    )
    
    # Create conversation manager with mock client
    conversation_manager = ConversationManager(
        model_config=model_config,
        api_client=mock_api,
        system_prompt="You are a helpful assistant."
    )
    
    # Create new conversation
    conversation_id = conversation_manager.create_new_conversation()
    logger.info(f"Created test conversation: {conversation_id}")
    
    # Step 1: Process first message (should succeed)
    logger.info("Step 1: Processing first message (should succeed)")
    response1 = await conversation_manager.process_message("Hello, how are you?")
    logger.info(f"Response received: {response1[:30]}...")
    
    # This should succeed
    assert response1 and "error" not in response1.lower(), "First message should succeed without errors"
    
    # Get token usage after first message
    usage1 = conversation_manager.get_token_usage()
    logger.info(f"Token usage after first message: {usage1['total']}")
    
    # Step 2: Process message with error trigger word (should fail)
    logger.info("Step 2: Processing message with error trigger (should fail)")
    response2 = await conversation_manager.process_message("This message should trigger an exception")
    logger.info(f"Response received: {response2[:30]}...")
    
    # This should return an error
    assert "error" in response2.lower(), "Message with trigger word should return error"
    
    # Step 3: Verify conversation state is preserved despite error
    logger.info("Step 3: Verifying conversation state preservation")
    session = conversation_manager.get_current_session()
    assert session is not None, "Session should still exist after error"
    
    # Check that user messages were preserved
    user_messages = [msg for msg in session.messages if msg.role == "user"]
    logger.info(f"User messages preserved: {len(user_messages)}")
    assert len(user_messages) >= 2, "User messages should be preserved after error"
    
    # Step 4: Reset API client to allow recovery
    logger.info("Step 4: Resetting API client to allow recovery")
    mock_api.reset_triggers()
    
    # Step 5: Resume conversation after error
    logger.info("Step 5: Resuming conversation after error")
    response3 = await conversation_manager.process_message("Can we continue our conversation now?")
    logger.info(f"Response received: {response3[:30]}...")
    assert "error" not in response3.lower(), "Should get successful response after recovery"
    
    # Step 6: Verify token counting is consistent after recovery
    logger.info("Step 6: Verifying token counting consistency")
    usage2 = conversation_manager.get_token_usage()
    logger.info(f"Token usage after recovery: {usage2['total']}")
    
    # Token count should have increased after recovery
    assert usage2["total"] > usage1["total"], "Token count should increase after recovery"
    
    # Step 7: Test token counting directly to verify it's still functional
    logger.info("Step 7: Testing token counting directly")
    test_content = "This is a test message for token counting"
    token_count = mock_api.count_tokens(test_content)
    logger.info(f"Direct token count: {token_count}")
    assert token_count > 0, "Token counting should work after recovery"
    
    logger.info("Error resilience test completed successfully")

if __name__ == "__main__":
    # Run all implemented tests in sequence
    
    # Test 1: Basic token counting
    asyncio.run(test_token_counting())
    
    # Test 2: Token budgeting and trimming
    asyncio.run(test_token_budgeting())
    
    # Test 3: Priority-based message trimming
    asyncio.run(test_priority_based_trimming())
    
    # Test 4: Conversation continuity across sessions
    asyncio.run(test_conversation_continuity())
    
    # Test 5: Error resilience and recovery
    asyncio.run(test_error_resilience())
    
    # Other tests - currently disabled
    # asyncio.run(test_incremental_vs_batch_trimming())
    # asyncio.run(test_multimodal_content_handling())
    # asyncio.run(test_cross_session_token_tracking())
    # asyncio.run(test_dynamic_budget_allocation())