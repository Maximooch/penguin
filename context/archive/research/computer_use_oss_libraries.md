# Open Source Computer Use Libraries for Penguin Integration

**Date:** 2025-01-09
**Status:** Research & Planning Phase
**Author:** Penguin Agent

## Executive Summary

This report catalogs open-source, model-agnostic computer use libraries and frameworks that Penguin could integrate with to build a native, OSS-first computer use capability. These implementations provide vision-based GUI automation that works across different LLM providers and platforms.

**Key Finding:** Multiple mature OSS frameworks exist that Penguin can either integrate directly or learn from for implementing model-agnostic computer use.

## 1. Vision-Based Desktop Automation Libraries

### 1.1 SikuliX

**Repository:** [SikuliX](https://github.com/RaiMan/SikuliX)
**License:** MIT License
**Platform:** Windows, macOS, Linux

**Overview:**
- Classic open-source tool for automating anything visible on screen via image recognition
- Uses OpenCV for visual pattern matching
- Scriptable in Python (Jython) or Java
- Can click arbitrary areas, type text, wait for images, etc.

**Capabilities:**
- Image-based element detection and interaction
- Cross-platform desktop automation
- Screen capture and visual verification
- Mouse and keyboard control

**Penguin Integration Potential:**
- Mature, battle-tested library
- Pure vision-based (model-agnostic)
- Cross-platform support
- Uses Jython (not native Python)
- May be slower than modern alternatives

### 1.2 AutoIt

**Repository:** [AutoIt](https://www.autoitscript.com/site/autoit/)
**License:** MIT License
**Platform:** Windows only

**Overview:**
- Mature Windows automation language
- Strong GUI scripting and control-finding
- Pixel/image checks via add-ons
- Widely used for generic Windows automation

**Capabilities:**
- Windows desktop automation
- Control-based interaction (not pure vision)
- Pixel-based image detection
- COM and DLL integration

**Penguin Integration Potential:**
- Extremely mature and stable
- Windows-specific optimizations
- Windows-only (limits cross-platform)
- Not primarily vision-based

## 2. Modern Computer Vision Agents

### 2.1 AskUI Vision Agent

**Repository:** [askui/vision-agent](https://github.com/askui/vision-agent)
**License:** Open Source
**Platform:** Windows, macOS, Linux, Android, iOS, Citrix

**Overview:**
- General desktop + mobile UI control with computer vision
- Supports both RPA-style commands and agentic instructions
- Lets AI agents directly control mouse/keyboard
- Multi-platform with Citrix compatibility

**Architecture Components:**
1. Visual Understanding - Perceive and analyze interface state
2. Interpretation - Understand user intent via natural language
3. Planning - Determine sequence of actions
4. Execution - Perform interactions with UI elements
5. Verification - Confirm successful completion

**Features:**
- Multi-platform support (desktop + mobile)
- Single-step RPA commands and agentic intent-based instructions
- Python API with click, element detection, screenshot, annotation
- Conditional waits for UI elements
- In-background automation on Windows
- Flexible model swapping
- On-premise infrastructure for model retraining

**Installation:**
pip install askui[all]
# Requires Python 3.10+

**Penguin Integration Potential:**
- HIGH PRIORITY - Most comprehensive OSS solution
- True multi-platform (desktop + mobile)
- Agentic architecture (matches Penguin's design)
- Model-agnostic design
- Enterprise-ready features
- Python 3.10+ compatible
- May require API keys/tokens for some features

### 2.2 Skyvern

**Repository:** [Skyvern-AI/skyvern](https://github.com/Skyvern-AI/skyvern)
**License:** AGPL-3.0 (core), with managed cloud offering
**Platform:** Browser-based (Playwright)

**Overview:**
- Open-source, model-agnostic browser automation framework
- Combines LLMs + computer vision to drive real browsers
- Executes workflows via natural-language prompts
- Replaces brittle DOM/XPath automations

**Architecture Components:**
1. Playwright-based browser controller - DOM access, navigation, screenshots
2. Vision + LLM planner/executor - Swarm of agents for planning and execution
3. Multi-agent swarm design - Inspired by BabyAGI / AutoGPT
4. Workflow layer - Reusable building blocks for form filling, data extraction
5. API + Python client - Schema-driven outputs, single API endpoint

**Model-Agnostic Integration:**
- Pluggable with multiple LLM backends (OpenAI, Anthropic, Gemini, Ollama)
- Generic chat/completions interface
- Swap models without changing workflows
- Prompt-caching and context-tree optimizations

**Computer Vision Aspects:**
- Uses vision-enabled LLMs to interpret screenshots
- Combines visual cues + nearby text/labels
- Robust to UI/layout changes

**Execution Modes:**
- Explore/Agent Mode: LLM in loop, learning trajectories
- Compiled Replay Mode: Deterministic Playwright code, faster/cheaper
- Falls back to agent when flow breaks

**Penguin Integration Potential:**
- HIGH PRIORITY - Excellent browser automation
- Model-agnostic design (matches Penguin goals)
- Multi-agent swarm architecture
- Production-ready with optimizations
- Python client available
- Browser-only (not full desktop)
- AGPL license (copyleft requirements)

### 2.3 Magnitude

**Repository:** [sagekit/magnitude](https://github.com/sagekit/magnitude)
**License:** Open Source
**Platform:** Browser-based (Node/TypeScript)

**Overview:**
- Vision-first browser agent for web automation and testing
- Uses visually grounded models (Claude 3.5 Sonnet, Qwen2.5-VL)
- Acts based on pixels instead of DOM selectors
- Production-grade web automation

**Capabilities:**
- Natural-language browser automation
- Navigate any interface
- Interact via mouse and keyboard
- Extract structured data
- Verify UI with visual assertions

**Performance:**
- ~94% success on WebVoyager benchmark
- Outperforms DOM-based agents
- Robust to layout changes

**Penguin Integration Potential:**
- High performance on benchmarks
- Vision-first approach
- Model-agnostic (supports multiple vision LLMs)
- Node/TypeScript based (not Python)
- Browser-only (not full desktop)
- May need subprocess or API integration

### 2.4 Dieter

**Repository:** [dbpprt/dieter](https://github.com/dbpprt/dieter)
**License:** Open Source
**Platform:** Browser-based

**Overview:**
- Vision-powered browser automation agent
- Combines LLMs with computer vision
- Uses OmniParser's YOLO model for element detection
- Uses Apple Vision for OCR
- Uses Playwright for execution

**Architecture:**
- OmniParser: YOLO-based UI element detection
- Apple Vision: OCR for text extraction
- Playwright: Browser control
- LLM: Planning and decision making
- Maintains page state and history
- Supports interactive/non-interactive modes

**Penguin Integration Potential:**
- Uses OmniParser (mature UI detection)
- Python-based (Playwright)
- Vision-first approach
- Apple Vision (macOS only)
- Browser-only

### 2.5 VisionTasker

**Repository:** [AkimotoAyako/VisionTasker](https://github.com/AkimotoAyako/VisionTasker)
**License:** Open Source
**Platform:** Mobile (Android)

**Overview:**
- Research-grade mobile task automation agent
- Two-stage framework: Vision-based UI understanding + LLM planning
- Works from screenshots (no view hierarchy)
- Tested on 147 real-world Android tasks

**Penguin Integration Potential:**
- Mobile automation (unique niche)
- Research-grade, well-tested
- Mobile-only (not desktop)
- Research prototype (may not be production-ready)

## 3. UI Element Detection Models

### 3.1 OmniParser

**Repository:** [microsoft/OmniParser](https://github.com/microsoft/OmniParser)
**License:** AGPL (YOLO model), MIT (caption models)
**Platform:** Cross-platform (Python)

**Overview:**
- Microsoft's open-source UI element detection model
- Fine-tuned YOLOv8 Nano for icon detection
- Trained on 67,000 unique UI screenshots
- Combines YOLO + Florence 2 for caption generation

**Pipeline Components:**
1. YOLOv8 Nano Detection Model - Trained on 67K UI screenshots
2. Florence 2 Caption Model - Icon caption generation
3. OCR Integration - Extracts text bounding boxes
4. Adaptive bounding box merging - Removes redundant overlaps

**Installation:**
git clone https://github.com/microsoft/OmniParser.git
cd OmniParser
conda create -n omniparser python=3.12
conda activate omniparser
pip install -r requirements.txt

**Features:**
- Gradio demo interface
- Example notebooks
- Pre-trained models included
- Robust to various UI styles

**Penguin Integration Potential:**
- HIGH PRIORITY - Microsoft-backed, mature
- Pure Python implementation
- Excellent UI element detection
- Can be used as a component in Penguin's computer use
- AGPL license (compatible with OSS)
- AGPL on detection model (copyleft)
- May require GPU for good performance

## 4. Comparison Matrix

| Library | Platform | Vision-Based | Model-Agnostic | Python | License | Integration Complexity |
|---------|----------|--------------|----------------|--------|----------|---------------------|
| **SikuliX** | Win/Mac/Linux | Yes | Yes | Jython | MIT | Medium |
| **AutoIt** | Windows | Partial | Yes | No | MIT | Low |
| **AskUI** | Win/Mac/Linux/Mobile | Yes | Yes | Yes | Open Source | Low |
| **Skyvern** | Browser | Yes | Yes | Yes | AGPL | Low |
| **Magnitude** | Browser | Yes | Yes | No (Node) | Open Source | Medium |
| **Dieter** | Browser | Yes | Yes | Yes | Open Source | Low |
| **VisionTasker** | Android | Yes | Yes | Yes | Open Source | Medium |
| **OmniParser** | Cross-platform | Yes | Yes | Yes | AGPL/MIT | Low |

## 5. Recommended Integration Strategy for Penguin

### 5.1 Primary Recommendation: AskUI + OmniParser

**Rationale:**
- AskUI provides complete computer use framework
- OmniParser provides superior UI element detection
- Both are Python-based and model-agnostic
- Covers both desktop and browser automation

**Architecture:**
Penguin Core
    -> Computer Use Agent
    -> AskUI Vision Agent (execution)
    -> OmniParser (UI element detection)
    -> Playwright/PyDoll (browser control)

### 5.2 Secondary Recommendation: Skyvern for Browser

**Rationale:**
- Excellent for web automation
- Model-agnostic design
- Production-ready with optimizations
- Can complement AskUI for browser-specific tasks

### 5.3 Component-Based Approach

**Penguin could build its own stack using:**
1. UI Detection: OmniParser (Microsoft)
2. Browser Control: Playwright (existing PyDoll)
3. Desktop Control: PyAutoGUI or AskUI
4. Planning: Penguin's existing multi-agent system
5. LLM Interface: Model-agnostic adapters (already exists)

## 6. Implementation Roadmap

### Phase 1: Proof of Concept (Week 1)
- Install and test AskUI Vision Agent
- Install and test OmniParser
- Create basic Penguin tool wrapper for AskUI
- Test with simple desktop automation task

### Phase 2: Integration (Week 2)
- Register AskUI tools in ToolManager
- Create OmniParser detection tool
- Integrate with Penguin's multi-agent system
- Test with browser automation

### Phase 3: Hybrid Approach (Week 3)
- Integrate Skyvern for browser tasks
- Create routing logic (desktop -> AskUI, browser -> Skyvern)
- Implement fallback mechanisms
- Add error handling and retry

### Phase 4: Production (Week 4)
- Performance optimization
- Security and permission controls
- Documentation and examples
- Testing and validation

## 7. Configuration

### 7.1 Config.yml Additions

computer_use:
  enabled: false
  mode: hybrid  # options: askui, skyvern, omniparser, hybrid

  askui:
    enabled: true
    workspace_id: ${ASKUI_WORKSPACE_ID}
    token: ${ASKUI_TOKEN}
    platform: auto  # auto, windows, macos, linux

  skyvern:
    enabled: true
    api_key: ${SKYVERN_API_KEY}
    base_url: https://api.skyvern.ai

  omniparser:
    enabled: true
    model_path: ./models/omniparser
    confidence_threshold: 0.7
    device: cuda  # cuda, cpu, auto

  routing:
    desktop_tasks: askui  # askui, omniparser
    browser_tasks: skyvern  # skyvern, askui, omniparser
    fallback: askui  # fallback when primary fails

## 8. Testing Strategy

### 8.1 Unit Tests
- OmniParser detection accuracy
- AskUI tool execution
- Skyvern workflow execution
- Error handling and retry logic

### 8.2 Integration Tests
- End-to-end desktop automation
- End-to-end browser automation
- Multi-agent coordination
- Routing between different backends

### 8.3 Manual Testing
- Real desktop applications
- Real web applications
- Edge cases (popups, dialogs, animations)
- Performance benchmarks

## 9. Open Questions

### 9.1 Technical Questions
1. Should Penguin use a single backend or multiple?
2. How to handle fallback when one backend fails?
3. Should we cache OmniParser results?
4. How to integrate with existing permission model?
5. Should we support coordinate-based AND selector-based?

### 9.2 Licensing Questions
1. AGPL license implications for Penguin (MIT/Apache?)
2. Can we use OmniParser in a commercial product?
3. What are copyleft requirements?

### 9.3 Performance Questions
1. How to optimize for low-latency interactions?
2. Should we batch multiple detections?
3. How to minimize token usage with screenshots?

## 10. Recommendations

### 10.1 Immediate Actions (Next 2 Weeks)
1. Proof of Concept: Test AskUI and OmniParser
2. License Review: Consult legal on AGPL implications
3. Architecture Decision: Choose primary backend
4. Performance Testing: Benchmark against Anthropic Computer Use

### 10.2 Short Term (1-2 Months)
1. Phase 1-2 Implementation: Core tools and integration
2. Documentation: User guide and API reference
3. Examples: Sample workflows and use cases
4. Testing: Comprehensive test suite

### 10.3 Long Term (3-6 Months)
1. Advanced Features: Custom models, optimizations
2. Performance: Caching, batching, parallel execution
3. Ecosystem: Integrations with popular apps
4. Feedback: User testing and iteration

### 10.4 Strategic Considerations
- Model-Agnostic First: Don't lock into Anthropic-only
- OSS Compliance: Respect AGPL and other copyleft licenses
- Performance Matters: Optimize for low latency
- Security First: Implement strict permission controls
- User Choice: Allow users to choose backend

## 11. Conclusion

Multiple mature OSS libraries exist for computer use that Penguin can leverage:

**Primary Recommendations:**
1. AskUI Vision Agent - Best for full desktop automation
2. OmniParser - Best for UI element detection
3. Skyvern - Best for browser automation

**Implementation Strategy:**
- Use AskUI as primary desktop backend
- Use OmniParser for UI element detection
- Use Skyvern for browser-specific tasks
- Build hybrid routing logic in Penguin
- Maintain model-agnostic design

**Estimated Effort:** 3-4 weeks for full integration
**Risk Level:** Low (mature, tested libraries)
**Value:** High (OSS, model-agnostic, production-ready)

**Next Steps:**
1. Review licensing implications of AGPL
2. Set up proof of concept with AskUI
3. Test OmniParser integration
4. Begin Phase 1 implementation

---

## Appendix A: Repository Links

### Primary Libraries
- AskUI Vision Agent: https://github.com/askui/vision-agent
- Skyvern: https://github.com/Skyvern-AI/skyvern
- Magnitude: https://github.com/sagekit/magnitude
- Dieter: https://github.com/dbpprt/dieter
- VisionTasker: https://github.com/AkimotoAyako/VisionTasker

### UI Detection Models
- OmniParser: https://github.com/microsoft/OmniParser

### Classic Libraries
- SikuliX: https://github.com/RaiMan/SikuliX
- AutoIt: https://www.autoitscript.com/site/autoit/

## Appendix B: License Summary

| Library | License | Copyleft | Commercial Use | Modifications |
|---------|----------|-----------|----------------|--------------|
| **SikuliX** | MIT | No | Yes | Yes |
| **AutoIt** | MIT | No | Yes | Yes |
| **AskUI** | Open Source | Unknown | Unknown | Unknown |
| **Skyvern** | AGPL-3.0 | Yes | Yes | Must share source |
| **Magnitude** | Open Source | Unknown | Unknown | Unknown |
| **Dieter** | Open Source | Unknown | Unknown | Unknown |
| **VisionTasker** | Open Source | Unknown | Unknown | Unknown |
| **OmniParser** | AGPL/MIT | Partial | Yes | Partial (AGPL on model) |

## Appendix C: Performance Benchmarks

### WebVoyager Benchmark
- Magnitude: ~94% success rate
- DOM-based agents: Lower success rate
- Anthropic Computer Use: ~85% success rate (estimated)

### Performance Metrics to Track
- Task completion rate
- Average task completion time
- Token usage per task
- Screenshot processing time
- UI element detection accuracy

---

**End of Report**
