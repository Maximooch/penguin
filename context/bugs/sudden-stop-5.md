
INFO:     core.stream.finalize request=07281c57-64c9-4ad0-8b25-904c7ff4719f session=session_20260506_022252_7fb0cf40 conversation=session_20260506_022252_7fb0cf40 agent=default effective_conv_session=session_20260506_022252_7fb0cf40 persisted=True message_len=62 events=2 empty=False
INFO:     engine.stream.finalize.done request=07281c57-64c9-4ad0-8b25-904c7ff4719f session=session_20260506_022252_7fb0cf40 agent=default conv_session=session_20260506_022252_7fb0cf40 response_len=62 finalized=True
INFO:     engine.llm_step.done request=07281c57-64c9-4ad0-8b25-904c7ff4719f session=session_20260506_022252_7fb0cf40 agent=default conv_session=session_20260506_022252_7fb0cf40 response_len=62 actions=1 usage={'input_tokens': 85332, 'output_tokens': 226, 'reasoning_tokens': 104, 'cache_read_tokens': 2432, 'cache_write_tokens': 0, 'total_tokens': 85558, 'cost': 0.0}
INFO:     127.0.0.1:52754 - "GET /session/session_20260506_022252_7fb0cf40 HTTP/1.1" 200 OK
INFO:     engine.scope.reuse request=07281c57-64c9-4ad0-8b25-904c7ff4719f session=session_20260506_022252_7fb0cf40 agent=default cache=1 base_cm=0x10ac335d0 scoped_cm=0x10b7a3010 scoped_session=session_20260506_022252_7fb0cf40
INFO:     engine.scope.reuse request=07281c57-64c9-4ad0-8b25-904c7ff4719f session=session_20260506_022252_7fb0cf40 agent=default cache=1 base_cm=0x10ac335d0 scoped_cm=0x10b7a3010 scoped_session=session_20260506_022252_7fb0cf40
INFO:     engine.llm_step.start request=07281c57-64c9-4ad0-8b25-904c7ff4719f session=session_20260506_022252_7fb0cf40 agent=default cm=0x10b7a3010 conv=0x10b7a0f10 conv_session=session_20260506_022252_7fb0cf40 msgs=214 last_role=tool last_preview='{"error": "/Users/maximusputnam/Code/Penguin/penguin/.venv/bin/python: No module named black", "tool": "execute_comma...' streaming=True tools=True
INFO:     openai.oauth.resolve source=store_oauth has_access=True has_refresh=True has_expires=True has_account=True
INFO:     openai.request.route route=oauth_codex model=gpt-5.5 stream=True service_tier=priority has_access=True has_refresh=True has_expires=True has_account=True
INFO:     openai.oauth.codex.request_start diag_id=oaoc_a97caf2623 requested_stream=True transport_stream=True model=gpt-5.5 model_fallback=False input_items=250 instructions_present=True store=False service_tier=priority has_account_id=True has_reasoning=True
ERROR:    OpenAI OAuth Codex stream_request failed (diag_id=oaoc_a97caf2623, status=503, model=gpt-5.5, model_fallback=False, input_is_list=True, input_items=250, instructions_present=True, store=False, service_tier=priority, latency_ms=328) detail=upstream connect error or disconnect/reset before headers. retried and the latest reset reason: remote connection failure, transport failure reason: delayed connect error: Connection refused, trace={'cf-ray': '9f7ac782a85d5e9e-IAH'}
ERROR:    [Request:07281c57-64c9-4ad0-8b25-904c7ff4719f] llm.handler.failure diag_id=oaoc_a97caf2623 category=provider_unavailable handler=OpenAIAdapter provider=openai model=gpt-5.5 detail=OpenAI OAuth Codex stream_request failed (diag_id=oaoc_a97caf2623, status=503, model=gpt-5.5, model_fallback=False, input_is_list=True, input_items=250, instructions_present=True, store=False, service_tier=priority, latency_ms=328) detail=upstream connect error or disconnect/reset before headers. retried and the latest reset reason: remote connection failure, transport failure reason: delayed connect error: Connection refused, trace={'cf-ray': '9f7ac782a85d5e9e-IAH'}
Traceback (most recent call last):
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/api_client.py", line 709, in get_response
    response_text = await self.client_handler.get_response(
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 675, in get_response
    accumulated = await self.create_completion(
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 558, in create_completion
    return await self._create_oauth_codex_completion(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 1204, in _create_oauth_codex_completion
    return await self._stream_codex_oauth(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 1358, in _stream_codex_oauth
    self._raise_codex_error(
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 1669, in _raise_codex_error
    raise LLMProviderError(llm_error)
penguin.llm.contracts.LLMProviderError: OpenAI OAuth Codex stream_request failed (diag_id=oaoc_a97caf2623, status=503, model=gpt-5.5, model_fallback=False, input_is_list=True, input_items=250, instructions_present=True, store=False, service_tier=priority, latency_ms=328) detail=upstream connect error or disconnect/reset before headers. retried and the latest reset reason: remote connection failure, transport failure reason: delayed connect error: Connection refused, trace={'cf-ray': '9f7ac782a85d5e9e-IAH'}
INFO:     engine.stream.finalize.start request=07281c57-64c9-4ad0-8b25-904c7ff4719f session=session_20260506_022252_7fb0cf40 agent=default conv_session=session_20260506_022252_7fb0cf40 streaming=True response_len=67
INFO:     core.stream.persist session=session_20260506_022252_7fb0cf40 agent=default manager=0x10ac32dd0 message_id=msg_1778099809.875198 saved=True message_len=67 category=MessageCategory.DIALOG
INFO:     core.stream.finalize request=07281c57-64c9-4ad0-8b25-904c7ff4719f session=session_20260506_022252_7fb0cf40 conversation=session_20260506_022252_7fb0cf40 agent=default effective_conv_session=session_20260506_022252_7fb0cf40 persisted=True message_len=67 events=1 empty=False
INFO:     engine.stream.finalize.done request=07281c57-64c9-4ad0-8b25-904c7ff4719f session=session_20260506_022252_7fb0cf40 agent=default conv_session=session_20260506_022252_7fb0cf40 response_len=67 finalized=True
INFO:     engine.llm_step.done request=07281c57-64c9-4ad0-8b25-904c7ff4719f session=session_20260506_022252_7fb0cf40 agent=default conv_session=session_20260506_022252_7fb0cf40 response_len=67 actions=0 usage={}
INFO:     core.process.trace.done request=07281c57-64c9-4ad0-8b25-904c7ff4719f session=session_20260506_022252_7fb0cf40 conversation=session_20260506_022252_7fb0cf40 status=completed iterations=36 actions=59 usage={'input_tokens': 85332, 'output_tokens': 226, 'reasoning_tokens': 104, 'cache_read_tokens': 2432, 'cache_write_tokens': 0, 'total_tokens': 85558, 'cost': 0.0} response_len=67
INFO:     opencode.usage.applied session=session_20260506_022252_7fb0cf40 message=msg_session_20260506_022252_7fb0cf40_1778099443276_00 input=85332 output=226 reasoning=104 cache_read=2432 cache_write=0 total=85558 cost=0.0
INFO:     127.0.0.1:52754 - "GET /session/session_20260506_022252_7fb0cf40 HTTP/1.1" 200 OK
INFO:     chat.trace.after_process request=07281c57-64c9-4ad0-8b25-904c7ff4719f session=session_20260506_022252_7fb0cf40 status=completed iterations=36 response_len=67 actions=59 usage={'input_tokens': 85332, 'output_tokens': 226, 'reasoning_tokens': 104, 'cache_read_tokens': 2432, 'cache_write_tokens': 0, 'total_tokens': 85558, 'cost': 0.0} process_ms=371853.76 preview='Error: LLM upstream is unavailable. Diagnostic ID: oaoc_a97caf2623.'
INFO:     session.title.auto_refresh session=session_20260506_022252_7fb0cf40 status=scheduled
INFO:     chat.trace.response request=07281c57-64c9-4ad0-8b25-904c7ff4719f session=session_20260506_022252_7fb0cf40 response_len=67 reasoning_len=6435 aborted=False preview='Error: LLM upstream is unavailable. Diagnostic ID: oaoc_a97caf2623.'
INFO:     session.title.auto_refresh session=session_20260506_022252_7fb0cf40 attempt=1 status=already_titled title='Error: LLM request timed out. Diagnostic ID: oaoc_1b5cdadf34.'