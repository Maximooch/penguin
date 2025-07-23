# Penguin LLM Debugging Guide

This guide helps you debug issues with Claude Sonnet 4 through OpenRouter and other LLM integrations.

## Quick Diagnostics

### 1. Run Full Diagnostic
```bash
cd penguin
python debug_claude_sonnet.py --run-full-test
```

### 2. Validate Configuration Only
```bash
python debug_claude_sonnet.py --validate-config
```

### 3. Test Streaming Issues
```bash
python debug_claude_sonnet.py --test-streaming --verbose
```

## Your Specific Issue: Tool Results Not Processing

Based on your TUI debug log, the issue is:
1. ✅ Streaming works (reasoning tokens + content)
2. ✅ Tools execute successfully 
3. ❌ Assistant doesn't continue after receiving tool results

### Likely Causes
1. **Conversation Format**: Tool results may not be properly formatted for Claude
2. **Context Window**: Too many tokens causing truncation
3. **OpenRouter Handling**: Issue with how OpenRouter processes complex conversations
4. **Core Processing**: Issue in `core.py` conversation management

### Debugging Steps

#### Step 1: Check Conversation Format
```python
# In your core.py, add this debug logging:
logger.debug(f"Full conversation before API call: {json.dumps(messages, indent=2)}")
```

#### Step 2: Enable Enhanced Debugging
Add to your `config.yml`:
```yaml
diagnostics:
  enabled: true
  verbose_logging: true
  debug_llm: true  # New option
  debug_tools: true  # New option
```

#### Step 3: Test Different Models
Try with a simpler model to isolate the issue:
```yaml
model:
  default: "openai/gpt-3.5-turbo"  # Test with this first
```

#### Step 4: Check Tool Result Format
The issue might be in how tool results are added to conversation:
```python
# Check if tool results are being added correctly
conversation.append({
    "role": "system",  # or "tool"?
    "content": "Tool Result: ..."
})
```

## Enhanced Debugging Configuration

### Enable Debug Logging

1. **Set Environment Variables**:
```bash
export PENGUIN_DEBUG=true
export PENGUIN_LOG_LEVEL=DEBUG
```

2. **Update config.yml**:
```yaml
model:
  default: anthropic/claude-sonnet-4
  provider: openrouter
  client_preference: openrouter
  streaming_enabled: true
  temperature: 0.5
  max_tokens: 4000
  
diagnostics:
  enabled: true
  verbose_logging: true
  debug_requests: true
  debug_responses: true
  debug_streaming: true
  debug_tools: true
  save_conversations: true
```

### Debug Log Locations

Debug logs are saved to:
- `debug_logs/llm_debug_YYYYMMDD_HHMMSS.log` - Comprehensive LLM debugging
- `penguin/errors_log/` - Error logs
- `conversations/` - Conversation history (if enabled)

## Common Issues & Solutions

### 1. Empty Responses
**Symptoms**: Model returns empty string or "[Model finished with no content]"
**Solutions**:
- Try different model (GPT-3.5 vs Claude vs Gemini)
- Reduce context length
- Adjust temperature (try 0.7-0.9)
- Check for quota issues

### 2. Streaming Cuts Off
**Symptoms**: Streaming starts but stops mid-response
**Solutions**:
- Check network connectivity
- Increase timeout values
- Verify OpenRouter API key quotas
- Test with non-streaming mode

### 3. Tool Results Ignored
**Symptoms**: Tools execute but assistant doesn't respond (your issue!)
**Solutions**:
- Check conversation message formatting
- Verify tool result integration in core.py
- Test with simpler conversation history
- Try different models to isolate issue

### 4. OpenRouter Quota Issues
**Symptoms**: "Provider quota exceeded" errors
**Solutions**:
- Switch to different model/provider
- Check OpenRouter dashboard for usage
- Wait and retry (quotas reset)
- Use free tier models for testing

## Advanced Debugging

### 1. Enable Request/Response Logging
Add this to your OpenRouter gateway initialization:
```python
# In openrouter_gateway.py
self.logger.setLevel(logging.DEBUG)
```

### 2. Monitor Token Usage
```python
# Track token usage in real-time
from penguin.llm.debug_utils import get_debugger
debugger = get_debugger()
# Token usage will be logged automatically
```

### 3. Conversation Analysis
```python
# Analyze conversation for issues
from penguin.llm.debug_utils import get_debugger
debugger = get_debugger()
analysis = debugger.analyze_conversation_flow(conversation_messages)
print(json.dumps(analysis, indent=2))
```

## Model-Specific Notes

### Claude Sonnet 4
- Supports reasoning tokens (enable with `reasoning_enabled: true`)
- Context window: ~200K tokens
- Prefers structured conversations
- Tool results should be in "system" role

### GPT-4o via OpenRouter
- Reliable streaming support
- Good tool integration
- Context window: ~128K tokens
- Tool results can be "system" or "tool" role

### Gemini via OpenRouter
- Sometimes returns empty responses
- Better with higher temperature (0.8+)
- Context window: ~1M tokens
- Sensitive to conversation format

## Emergency Fallback

If all else fails, try this minimal configuration:
```yaml
model:
  default: "openai/gpt-3.5-turbo"
  provider: openrouter
  client_preference: openrouter
  streaming_enabled: false  # Disable streaming temporarily
  temperature: 0.7
  max_tokens: 2000
```

## Getting Help

1. **Run the diagnostic script** first
2. **Check the debug logs** in `debug_logs/`
3. **Share the conversation format** that's failing
4. **Test with different models** to isolate the issue
5. **Enable verbose logging** for detailed analysis

## Performance Tips

- Use `openai/gpt-3.5-turbo` for development/testing (faster, cheaper)
- Enable streaming only when needed
- Keep conversation history manageable (<20 messages)
- Monitor token usage to avoid quota issues
- Use reasoning tokens sparingly (they consume extra tokens) 