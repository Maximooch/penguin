# OpenRouter Reasoning Token Fix Plan

## Issue Summary

The OpenRouter gateway is failing when reasoning tokens are enabled due to:

1. **SDK Incompatibility**: The OpenAI SDK doesn't support the `include_reasoning` parameter
2. **Response Handling Error**: The fallback HTTP implementation uses `response.atext()` which doesn't exist on httpx Response objects

## Root Cause Analysis

### Error 1: SDK Parameter Issue
```
TypeError: AsyncCompletions.create() got an unexpected keyword argument 'include_reasoning'
```

The code adds both `include_reasoning` and `reasoning` parameters to the SDK request:
- Line 233: `request_params["include_reasoning"] = True`
- Line 241: `request_params["reasoning"] = reasoning_config`

The OpenAI SDK doesn't recognize these OpenRouter-specific parameters.

### Error 2: Response Method Issue
```
AttributeError: 'Response' object has no attribute 'atext'
```

In `_handle_streaming_response` (line 508), the code tries to call `response.atext()` on an httpx Response object. The correct method is `response.text` (property) or `await response.aread()` (async method).

## Solution Strategy

### Phase 1: Immediate Fix (Priority)
1. **Separate SDK vs Direct API Parameters**
   - Never pass `include_reasoning` to the SDK
   - Only pass `reasoning` config through direct HTTP calls
   
2. **Fix Response Handling**
   - Change `response.atext()` to `response.text`
   - Ensure consistent error handling across streaming/non-streaming

3. **Improve Fallback Logic**
   - Detect reasoning models early
   - Use direct API for reasoning models from the start
   - Avoid unnecessary SDK attempts

### Phase 2: OpenAI Adapter (Future)
Create a proper adapter pattern to handle provider-specific features:

```python
class OpenAIAdapter:
    """Adapter to make OpenRouter API compatible with OpenAI SDK"""
    
    def prepare_request(self, params: Dict) -> Dict:
        """Convert OpenRouter params to SDK-compatible format"""
        sdk_params = params.copy()
        # Remove OpenRouter-specific params
        sdk_params.pop('include_reasoning', None)
        sdk_params.pop('reasoning', None)
        return sdk_params
    
    def should_use_direct_api(self, params: Dict) -> bool:
        """Determine if direct API is needed"""
        return 'reasoning' in params or 'include_reasoning' in params
```

## Implementation Steps

### Step 1: Fix Parameter Handling
```python
# In get_response method
if reasoning_config:
    # Don't add these to SDK params
    # request_params["include_reasoning"] = True  # REMOVE
    # request_params["reasoning"] = reasoning_config  # MOVE TO DIRECT API ONLY
    use_direct_api = True  # Force direct API for reasoning
```

### Step 2: Fix Response Error
```python
# In _handle_streaming_response
if response.status_code != 200:
    error_text = response.text  # Changed from response.atext()
```

### Step 3: Improve Error Handling
```python
except TypeError as e:
    if "unexpected keyword argument" in str(e):
        # Clear SDK-incompatible params and retry with direct API
        return await self._direct_api_call_with_reasoning(...)
```

## Testing Strategy

1. **Test Basic Reasoning**
   ```bash
   python misc/openrouter_reasoning_smoke.py -p "What is 2+2?" --stream
   ```

2. **Test Vision + Reasoning**
   ```bash
   python misc/openrouter_image_smoke.py --local image.png --stream
   ```

3. **Test Non-Reasoning Models**
   - Ensure regular models still work through SDK
   - Verify no performance regression

## Expected Outcomes

1. Reasoning models will work via direct HTTP API
2. Non-reasoning models continue using SDK (better performance)
3. Clear error messages when issues occur
4. Seamless fallback between SDK and direct API

## Future Enhancements

1. **Provider Abstraction Layer**
   - Create base Provider class
   - Implement OpenRouterProvider, AnthropicProvider, etc.
   - Handle provider-specific features cleanly

2. **Unified Streaming Handler**
   - Abstract SSE parsing
   - Handle provider-specific stream formats
   - Better error recovery

3. **Token Counting for Reasoning**
   - Track reasoning tokens separately
   - Update cost calculations
   - Show reasoning token usage in UI
