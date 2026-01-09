# Computer Use Implementation Report for Penguin

**Date:** 2025-01-09
**Status:** Research & Planning Phase
**Author:** Penguin Agent

## Executive Summary

Computer Use is a beta capability from Anthropic that enables Claude models to control a computer interface through screenshots and mouse/keyboard actions. This report analyzes how Computer Use could be integrated into Penguin's existing architecture, leveraging current browser automation infrastructure while adding new capabilities for GUI control.

**Key Finding:** Penguin is well-positioned to implement Computer Use with minimal architectural changes, thanks to existing PyDoll browser tools, modular tool system, and multi-agent orchestration capabilities.

## 1. Current Penguin Architecture Analysis

### 1.1 Relevant Existing Components

**Browser Automation Infrastructure:**
- **Location:** `penguin/tools/pydoll_tools.py` (33KB)
- **Current Capabilities:**
  - `PyDollBrowserNavigationTool` - Navigate to URLs
  - `PyDollBrowserInteractionTool` - Click, input, submit via selectors
  - `PyDollBrowserScreenshotTool` - Capture page screenshots
  - `PyDollBrowserScrollTool` - Scroll page or elements
- **Browser Manager:** `PyDollBrowserManager` with lifecycle management
- **Features:** Dev mode, timeout handling, retry logic, automatic cleanup

**Tool System:**
- **Location:** `penguin/tools/tool_manager.py` (182KB)
- **Architecture:**
  - Lazy loading for fast startup
  - Tool registry with schema definitions
  - Permission enforcement integration
  - Cached tool instances for performance
- **Registration Pattern:** Tools registered in `_tool_registry` dictionary

**Multi-Agent Orchestration:**
- **Location:** `penguin/multi/executor.py`
- **Capabilities:**
  - Semaphore-based concurrency control
  - Background task spawning
  - State machine (PENDING → RUNNING → COMPLETED/FAILED)
  - Wait operations for coordination

**LLM Adapters:**
- **Location:** `penguin/llm/provider_adapters.py`
- **Current Support:** OpenAI, LiteLLM, Anthropic
- **Image Handling:** Base64 encoding, resizing for vision models

### 1.2 Architecture Strengths for Computer Use

✅ **Modular Tool System:** Easy to register new Computer Use tools
✅ **Browser Infrastructure:** PyDoll provides solid foundation
✅ **Screenshot Pipeline:** Already captures and saves screenshots
✅ **Multi-Agent Support:** Can delegate Computer Use to specialized agents
✅ **Permission Model:** Built-in security controls
✅ **Lazy Loading:** Won't impact startup performance

## 2. Anthropic Computer Use API Overview

### 2.1 What is Computer Use?

Computer Use is a beta API capability that enables Claude to:
- View computer interfaces via screenshots
- Control mouse/keyboard (click, type, scroll)
- Navigate GUI elements without APIs
- Automate web apps and desktop tools
- Operate legacy systems with no API access

### 2.2 Technical Requirements

**Models:**
- `claude-3-5-sonnet-20241022`
- `claude-sonnet-4-5` (latest)

**Beta Headers:**
```
anthropic-beta: computer-use-2025-01-24
```

**Tool Types:**
- `computer_20241022` (original beta)
- `computer_20250124` (newer with region support)

### 2.3 Coordinate Scaling (Critical)

**The Challenge:**
- Screenshots are downscaled (max 1568px edge, ~1.15MP total)
- Claude returns coordinates in scaled space
- Must map back to real screen coordinates

**Solution:**
```python
scale = get_scale_factor(screen_width, screen_height)
scaled_width = int(screen_width * scale)
scaled_height = int(screen_height * scale)

# When capturing
screenshot = capture_and_resize(scaled_width, scaled_height)

# When executing
screen_x = claude_x / scale
screen_y = claude_y / scale
```

### 2.4 Tool Actions

Computer Use supports these actions:
- `screenshot` - Capture current display
- `mouse_move` - Move cursor to coordinates
- `mouse_down` / `mouse_up` - Mouse button states
- `click` - Click at coordinates
- `double_click` - Double click
- `drag` - Drag from point to point
- `type` - Type text
- `key` - Press special keys (Enter, Tab, etc.)
- `scroll` - Scroll at coordinates

## 3. Integration Strategy for Penguin

### 3.1 Phase 1: Tool Implementation (Foundation)

**New File:** `penguin/tools/computer_use_tools.py`

Key components to implement:
- `CoordinateScaler` class for coordinate mapping
- `ComputerUseTool` class with action handlers
- Screenshot capture with scaling
- Mouse actions (move, click, drag)
- Keyboard actions (type, key press)
- Scroll action

### 3.2 Phase 2: Tool Registration

**Modify:** `penguin/tools/tool_manager.py`

Add to `_tool_registry`:
- `computer_use` - Main tool
- `computer_screenshot` - Screenshot capture
- `computer_click` - Click action
- `computer_type` - Type action

### 3.3 Phase 3: Anthropic Adapter Enhancement

**Modify:** `penguin/llm/provider_adapters.py`

Enhance `AnthropicAdapter` with:
- Beta header support (`computer-use-2025-01-24`)
- Computer Use tool schema
- Display configuration

**Modify:** `penguin/llm/model_config.py`

Add fields:
- `computer_use_enabled: bool`
- `computer_use_display_width: Optional[int]`
- `computer_use_display_height: Optional[int]`

### 3.4 Phase 4: Specialized Agent

**New File:** `penguin/agents/computer_use_agent.py`

Create `ComputerUseAgent` class:
- Task execution loop
- Screenshot management
- Action orchestration
- Error handling and retry

**Register in PenguinCore:**
```python
core.register_agent(
    agent_id="computer_use_specialist",
    system_prompt="You are a Computer Use specialist...",
    persona="computer_use",
    model_config_id="claude-3-5-sonnet-computer-use",
    default_tools=["computer_use", "computer_screenshot", ...]
)
```

## 4. Implementation Roadmap

### 4.1 Phase 1: Core Tools (Week 1)
- [ ] Create `penguin/tools/computer_use_tools.py`
- [ ] Implement `CoordinateScaler` class
- [ ] Implement screenshot capture with scaling
- [ ] Implement mouse actions (move, click, drag)
- [ ] Implement keyboard actions (type, key press)
- [ ] Implement scroll action
- [ ] Add unit tests

### 4.2 Phase 2: Integration (Week 2)
- [ ] Register Computer Use tools in ToolManager
- [ ] Add tool schemas
- [ ] Enhance AnthropicAdapter with beta headers
- [ ] Add computer_use fields to ModelConfig
- [ ] Update config.yml with Computer Use settings
- [ ] Test tool registration and discovery

### 4.3 Phase 3: Agent Orchestration (Week 3)
- [ ] Create ComputerUseAgent class
- [ ] Implement task execution loop
- [ ] Add error handling and retry logic
- [ ] Implement progress reporting
- [ ] Register agent in PenguinCore
- [ ] Test end-to-end workflows

### 4.4 Phase 4: Advanced Features (Week 4)
- [ ] Region-based inspection (computer_20250124 feature)
- [ ] Multi-monitor support
- [ ] Performance optimization (caching, parallel actions)
- [ ] Security enhancements (sandboxing, permissions)
- [ ] Documentation and examples
- [ ] Integration tests

## 5. Technical Considerations

### 5.1 Security

**Risks:**
- Unrestricted GUI access
- Potential for malicious automation
- Credential exposure via screenshots

**Mitigations:**
- Use existing permission model
- Require explicit user approval for Computer Use
- Screenshot sanitization (blur sensitive areas)
- Action logging and audit trail
- Whitelist allowed applications/domains

### 5.2 Performance

**Optimizations:**
- Screenshot caching (only capture when changed)
- Lazy screenshot encoding
- Parallel action execution where safe
- Compressed screenshot transmission
- Region-based updates (partial screenshots)

**Metrics to Track:**
- Screenshot capture time
- Action execution latency
- Coordinate scaling overhead
- Token usage (images are expensive)

### 5.3 Compatibility

**Platforms:**
- ✅ macOS: Full support via PyDoll
- ✅ Linux: Full support via PyDoll
- ⚠️ Windows: PyDoll support needs verification
- ❌ Mobile: Not supported (no desktop GUI)

### 5.4 Error Handling

**Common Failures:**
- Screenshot capture fails
- Element not found at coordinates
- Application window closed
- Permission denied
- Timeout on action

**Recovery Strategies:**
- Retry with exponential backoff
- Fallback to selector-based interaction
- Re-screenshot and retry
- Graceful degradation to standard browser tools
- User notification for manual intervention

## 6. Comparison: Computer Use vs. Current Browser Tools

| Feature | Current PyDoll | Computer Use |
|---------|---------------|--------------|
| **Interaction Method** | Selectors (CSS/XPath) | Coordinates |
| **Visual Feedback** | Manual screenshots | Automatic screenshots |
| **Flexibility** | High (DOM-aware) | Medium (pixel-based) |
| **Reliability** | High (stable selectors) | Medium (coordinate drift) |
| **Setup** | Browser only | Full desktop |
| **Use Cases** | Web automation | Any GUI app |
| **Learning Curve** | Medium | Low (natural language) |
| **Cost** | Standard tokens | Higher (images) |

**Recommendation:** Use both approaches:
- **Browser Tools:** For web apps with stable DOM (more reliable, cheaper)
- **Computer Use:** For desktop apps, legacy systems, visual testing

## 7. Example Use Cases

### 7.1 Web Form Automation
Current approach uses selectors:
- Navigate to URL
- Input text via CSS selectors
- Click submit button

Computer Use approach uses coordinates:
- Take screenshot
- Click at username field coordinates
- Type username
- Click at password field coordinates
- Type password
- Click submit button coordinates

### 7.2 Desktop App Automation
Only possible with Computer Use:
- Take screenshot of desktop
- Click app menu coordinates
- Select "Export" option
- Click "Save" button
- Type filename
- Press Enter

### 7.3 Visual Testing
Automated visual regression testing:
- Take screenshot
- Compare with baseline
- Highlight differences
- Take region screenshots for details

## 8. Configuration

### 8.1 Config.yml Additions

```yaml
# Computer Use Configuration
computer_use:
  enabled: false  # Opt-in by default
  model: claude-3-5-sonnet-20241022
  beta_header: computer-use-2025-01-24

  display:
    width: 1920
    height: 1080
    scale_factor: auto  # or explicit value

  performance:
    screenshot_cache: true
    parallel_actions: false
    max_screenshot_size_mb: 5

  security:
    require_approval: true
    allowed_applications: []
    blocked_domains: []
    screenshot_sanitization: true

  logging:
    log_actions: true
    save_screenshots: true
    screenshot_dir: ./screenshots/computer_use
```

### 8.2 Environment Variables

```bash
# Enable Computer Use
export PENGUIN_COMPUTER_USE_ENABLED=true

# Display configuration
export PENGUIN_COMPUTER_USE_WIDTH=1920
export PENGUIN_COMPUTER_USE_HEIGHT=1080

# Security
export PENGUIN_COMPUTER_USE_REQUIRE_APPROVAL=true
export PENGUIN_COMPUTER_USE_ALLOWED_APPS="Terminal,VS Code"
```

## 9. Testing Strategy

### 9.1 Unit Tests
- Coordinate scaling accuracy
- Screenshot capture and encoding
- Action execution (mock PyDoll)
- Error handling and recovery

### 9.2 Integration Tests
- End-to-end workflows
- Multi-agent coordination
- Permission enforcement
- Performance benchmarks

### 9.3 Manual Testing
- Real web applications
- Desktop applications
- Edge cases (popups, dialogs, animations)
- Multi-monitor setups

### 9.4 Test Scenarios
1. **Basic Navigation:** Navigate to URL, click button, verify page
2. **Form Filling:** Fill complex form with validation
3. **Multi-Step Task:** Login → Navigate → Perform action → Logout
4. **Error Recovery:** Handle missing elements, timeouts
5. **Performance:** Measure latency, token usage
6. **Security:** Test permission blocks, sanitization

## 10. Open Questions & Risks

### 10.1 Technical Risks
- **Coordinate Drift:** UI changes may break coordinate-based actions
- **Screenshot Latency:** May slow down interaction loops
- **Token Costs:** Images are expensive (~1000+ tokens each)
- **Platform Support:** Windows compatibility uncertain

### 10.2 Architectural Questions
1. Should Computer Use be a separate agent or integrated into existing agents?
2. How to handle fallback when Computer Use fails?
3. Should we cache screenshots between actions?
4. How to integrate with existing permission model?
5. Should we support both coordinate and selector modes?

### 10.3 User Experience
1. How to show Computer Use actions in UI (CLI/TUI/Web)?
2. Should users approve each action or batch approve?
3. How to visualize coordinate-based actions?
4. How to debug when actions fail?

## 11. Recommendations

### 11.1 Immediate Actions (Next 2 Weeks)
1. ✅ **Proof of Concept:** Implement basic screenshot + click workflow
2. ✅ **Test with Anthropic API:** Verify beta header and tool schema
3. ✅ **Coordinate Scaling:** Implement and test scaling logic
4. ✅ **Security Review:** Assess permission model integration

### 11.2 Short Term (1-2 Months)
1. ✅ **Phase 1-2 Implementation:** Core tools and integration
2. ✅ **Documentation:** User guide and API reference
3. ✅ **Examples:** Sample workflows and use cases
4. ✅ **Testing:** Comprehensive test suite

### 11.3 Long Term (3-6 Months)
1. ✅ **Advanced Features:** Region inspection, multi-monitor
2. ✅ **Performance:** Optimization and caching
3. ✅ **Ecosystem:** Integrations with popular apps
4. ✅ **Feedback:** User testing and iteration

### 11.4 Strategic Considerations
- **Start as Opt-In:** Computer Use should be disabled by default
- **Complement, Don't Replace:** Keep existing browser tools
- **Focus on Reliability:** Prioritize robustness over features
- **Monitor Costs:** Track token usage and optimize
- **Security First:** Implement strict permission controls

## 12. Conclusion

Penguin's architecture is well-suited for Computer Use integration. The existing tool system, browser infrastructure, and multi-agent capabilities provide a solid foundation. The main implementation effort involves:

1. **Creating Computer Use tools** with coordinate scaling
2. **Enhancing the Anthropic adapter** with beta headers
3. **Implementing a specialized agent** for Computer Use tasks
4. **Adding security controls** and permission enforcement

**Estimated Effort:** 4-6 weeks for full implementation
**Risk Level:** Medium (coordinate-based approach is less reliable than selectors)
**Value:** High (enables automation of desktop apps and legacy systems)

**Next Steps:**
1. Review this report with stakeholders
2. Prioritize use cases for initial implementation
3. Allocate development resources
4. Begin Phase 1 implementation

---

## Appendix A: Key Implementation Files

### Files to Create:
- `penguin/tools/computer_use_tools.py` - Main Computer Use tools
- `penguin/agents/computer_use_agent.py` - Specialized agent

### Files to Modify:
- `penguin/tools/tool_manager.py` - Register tools
- `penguin/llm/provider_adapters.py` - Add beta header support
- `penguin/llm/model_config.py` - Add Computer Use config
- `config.yml` - Add Computer Use settings

## Appendix B: References

### Anthropic Documentation
- [Computer Use API](https://docs.anthropic.com/en/docs/build-with-claude/computer-use)
- [Tool Use](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
- [Messages API](https://docs.anthropic.com/en/api/messages)

### Penguin Architecture
- `architecture.md` - System architecture overview
- `penguin/tools/pydoll_tools.py` - Browser automation
- `penguin/tools/tool_manager.py` - Tool system
- `penguin/llm/provider_adapters.py` - LLM adapters
- `penguin/multi/executor.py` - Multi-agent execution

### External Libraries
- [PyDoll](https://github.com/pydoll-python/pydoll) - Browser automation
- [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python) - Anthropic API
- [Pillow](https://pillow.readthedocs.io/) - Image processing

---

**End of Report**
