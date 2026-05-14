
INFO:     openai.request.route route=oauth_codex model=gpt-5.5 stream=True service_tier=priority has_access=True has_refresh=True has_expires=True has_account=True
INFO:     openai.oauth.codex.request_start diag_id=oaoc_fb7e567108 requested_stream=True transport_stream=True model=gpt-5.5 model_fallback=False input_items=242 instructions_present=True store=False service_tier=priority has_account_id=True has_reasoning=True
ERROR:    [Request:17a80dee-0db4-42b2-9459-dfbfc2f5bb80] llm.handler.failure diag_id=llm_c21c906571 category=runtime handler=OpenAIAdapter provider=openai model=gpt-5.5 detail=[Errno 2] No such file or directory
Traceback (most recent call last):
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/api_client.py", line 709, in get_response
    response_text = await self.client_handler.get_response(
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 675, in get_response
    accumulated = await self.create_completion(
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 558, in create_completion
    return await self._create_oauth_codex_completion(
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 1204, in _create_oauth_codex_completion
    return await self._stream_codex_oauth(
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 1345, in _stream_codex_oauth
    async with httpx.AsyncClient(timeout=60.0) as client:
  File "/Users/maximusputnam/Code/Penguin/penguin/.venv/lib/python3.9/site-packages/httpx/_client.py", line 1402, in __init__
  File "/Users/maximusputnam/Code/Penguin/penguin/.venv/lib/python3.9/site-packages/httpx/_client.py", line 1445, in _init_transport
  File "/Users/maximusputnam/Code/Penguin/penguin/.venv/lib/python3.9/site-packages/httpx/_transports/default.py", line 297, in __init__
  File "/Users/maximusputnam/Code/Penguin/penguin/.venv/lib/python3.9/site-packages/httpx/_config.py", line 40, in create_ssl_context
  File "/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/ssl.py", line 745, in create_default_context
    context.load_verify_locations(cafile, capath, cadata)
FileNotFoundError: [Errno 2] No such file or directory
INFO:     engine.stream.finalize.start request=17a80dee-0db4-42b2-9459-dfbfc2f5bb80 session=session_20260501_114119_30863fae agent=default conv_session=session_20260501_114119_30863fae streaming=True response_len=57
INFO:     core.stream.persist session=session_20260501_114119_30863fae agent=default manager=0x109d11160 message_id=msg_1777666618.984891 saved=True message_len=57 category=MessageCategory.DIALOG
INFO:     core.stream.finalize request=17a80dee-0db4-42b2-9459-dfbfc2f5bb80 session=session_20260501_114119_30863fae conversation=session_20260501_114119_30863fae agent=default effective_conv_session=session_20260501_114119_30863fae persisted=True message_len=57 events=1 empty=False
INFO:     engine.stream.finalize.done request=17a80dee-0db4-42b2-9459-dfbfc2f5bb80 session=session_20260501_114119_30863fae agent=default conv_session=session_20260501_114119_30863fae response_len=57 finalized=True
INFO:     engine.llm_step.done request=17a80dee-0db4-42b2-9459-dfbfc2f5bb80 session=session_20260501_114119_30863fae agent=default conv_session=session_20260501_114119_30863fae response_len=57 actions=0 usage={}
INFO:     core.process.trace.done request=17a80dee-0db4-42b2-9459-dfbfc2f5bb80 session=session_20260501_114119_30863fae conversation=session_20260501_114119_30863fae status=completed iterations=21 actions=54 usage={'input_tokens': 92452, 'output_tokens': 552, 'reasoning_tokens': 448, 'cache_read_tokens': 41344, 'cache_write_tokens': 0, 'total_tokens': 93004, 'cost': 0.0} response_len=57
INFO:     opencode.usage.applied session=session_20260501_114119_30863fae message=msg_session_20260501_114119_30863fae_1777666343551_00 input=92452 output=552 reasoning=448 cache_read=41344 cache_write=0 total=93004 cost=0.0
INFO:     chat.trace.after_process request=17a80dee-0db4-42b2-9459-dfbfc2f5bb80 session=session_20260501_114119_30863fae status=completed iterations=21 response_len=57 actions=54 usage={'input_tokens': 92452, 'output_tokens': 552, 'reasoning_tokens': 448, 'cache_read_tokens': 41344, 'cache_write_tokens': 0, 'total_tokens': 93004, 'cost': 0.0} process_ms=282379.51 preview='Error: LLM request failed. Diagnostic ID: llm_c21c906571.'
INFO:     session.title.auto_refresh session=session_20260501_114119_30863fae status=scheduled
INFO:     chat.trace.response request=17a80dee-0db4-42b2-9459-dfbfc2f5bb80 session=session_20260501_114119_30863fae response_len=57 reasoning_len=3867 aborted=False preview='Error: LLM request failed. Diagnostic ID: llm_c21c906571.'
INFO:     session.title.auto_refresh session=session_20260501_114119_30863fae attempt=1 status=already_titled title='MCP Docs Scraping and SDK Architecture Onboarding'
INFO:     127.0.0.1:53449 - "GET /session/session_20260501_114119_30863fae HTTP/1.1" 200 OK