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
from penguin.system.state import MessageCategory, Message

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
    
    # Setup with tiny token budget to force trimming
    config = Config.load_config()
    model_config = ModelConfig(
        model=config.model.default,
        provider=config.model.provider,
        api_base=config.api.base_url,
        max_tokens=100  # Very small budget
    )
    api_client = APIClient(model_config=model_config)
    token_counter = api_client.count_tokens
    
    # Sample messages to add
    messages = [
        {"role": "system", "content": "System instructions", "category": MessageCategory.SYSTEM},
        {"role": "system", "content": "Important context", "category": MessageCategory.CONTEXT},
        {"role": "user", "content": "First user message", "category": MessageCategory.DIALOG},
        {"role": "assistant", "content": "First assistant response", "category": MessageCategory.DIALOG},
        {"role": "user", "content": "Second user message", "category": MessageCategory.DIALOG},
        {"role": "assistant", "content": "Second assistant response", "category": MessageCategory.DIALOG},
        {"role": "system", "content": "System output message", "category": MessageCategory.SYSTEM_OUTPUT},
    ]
    
    # Test 1: Incremental adding (trims as it goes)
    incremental_mgr = ConversationManager(model_config=model_config, api_client=api_client)
    incremental_id = incremental_mgr.create_new_conversation()
    
    # Add messages one by one
    for msg in messages:
        incremental_mgr.conversation.add_message(
            role=msg["role"],
            content=msg["content"],
            category=msg["category"]
        )
    
    # Test 2: Batch processing (adds all then trims)
    batch_mgr = ConversationManager(model_config=model_config, api_client=api_client)
    batch_id = batch_mgr.create_new_conversation()
    
    # Turn off automatic trimming
    batch_session = batch_mgr.conversation.session
    
    # Add all messages at once without trimming
    for msg in messages:
        message = Message(
            role=msg["role"],
            content=msg["content"],
            category=msg["category"],
            tokens=token_counter(msg["content"])
        )
        batch_session.messages.append(message)
    
    # Now do a single batch trim
    batch_mgr.context_window.process_session(batch_session)
    
    # Compare results
    incremental_tokens = incremental_mgr.get_token_usage()
    batch_tokens = batch_mgr.get_token_usage()
    
    logger.info("Incremental Addition Results:")
    if has_rich:
        console.print(incremental_mgr.context_window.format_token_usage_rich())
    else:
        logger.info(incremental_mgr.context_window.format_token_usage())
    
    logger.info("Batch Processing Results:")
    if has_rich:
        console.print(batch_mgr.context_window.format_token_usage_rich())
    else:
        logger.info(batch_mgr.context_window.format_token_usage())
    
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
        api_base=config.api.base_url
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
    
    # Add messages until we cross several session boundaries
    messages = [
        "First message in session 1",
        "Second message in session 1",
        "Third message in session 1",
        "Fourth message in session 1",
        "Fifth message in session 1",
        "First message in session 2",
        "Second message in session 2",
        "Third message in session 2",
        "Fourth message in session 2",
        "Fifth message in session 2",
        "First message in session 3",
    ]
    
    session_tokens = {}
    current_session_id = conversation_manager.get_current_session().id
    
    for i, msg in enumerate(messages):
        # Process the message
        response = await conversation_manager.process_message(msg)
        
        # Check if we've crossed a session boundary
        new_session_id = conversation_manager.get_current_session().id
        if new_session_id != current_session_id:
            logger.info(f"Session boundary crossed: {current_session_id} → {new_session_id}")
            # Store the previous session's tokens
            usage = conversation_manager.get_token_usage()
            session_tokens[current_session_id] = usage.get("total", 0)
            current_session_id = new_session_id
    
    # Get token usage for the final session
    usage = conversation_manager.get_token_usage()
    session_tokens[current_session_id] = usage.get("total", 0)
    
    # Report token usage across sessions
    logger.info("Token usage across sessions:")
    total_tokens = 0
    for session_id, tokens in session_tokens.items():
        logger.info(f"  Session {session_id}: {tokens} tokens")
        total_tokens += tokens
    
    logger.info(f"Total tokens across all sessions: {total_tokens}")
    
    # Verify token tracking in the session manager's index
    session_index = conversation_manager.session_manager.session_index
    for session_id, metadata in session_index.items():
        if session_id in session_tokens:
            logger.info(f"Session {session_id} - Index: {metadata.get('token_count', 'N/A')}, Calculated: {session_tokens[session_id]}")

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

if __name__ == "__main__":
    # Existing test - token counting across sessions
    # asyncio.run(test_token_counting())
    
    # Token budgeting test - already implemented
    # asyncio.run(test_token_budgeting())
    
    # New tests
    asyncio.run(test_incremental_vs_batch_trimming())
    # asyncio.run(test_multimodal_content_handling())
    # asyncio.run(test_cross_session_token_tracking())
    # asyncio.run(test_dynamic_budget_allocation()) 