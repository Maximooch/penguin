
INFO:     engine.llm_step.start request=ff2b8ca6-521e-46dc-8603-ba15941635a9 session=session_20260509_210523_4d051ef4 agent=default cm=0x1455dced0 conv=0x1455ddd50 conv_session=session_20260509_210523_4d051ef4 msgs=446 last_role=tool last_preview='<redacted>' streaming=True tools=True
INFO:     engine.context.snapshot request=ff2b8ca6-521e-46dc-8603-ba15941635a9 session=session_20260509_210523_4d051ef4 agent=default formatted_messages=446 roles={'system': 8, 'assistant': 343, 'user': 69, 'tool': 26} total_chars=729218 approx_tokens=182304 session_messages=446 session_tokens=178983 category_tokens={'SYSTEM': 12543, 'DIALOG': 75742, 'CONTEXT': 52290, 'SYSTEM_OUTPUT': 38408} largest=[{'id': 'msg_8eb3e1c5', 'role': 'system', 'category': 'CONTEXT', 'tokens': 19969, 'chars': 84137}, {'id': 'msg_33692d2b', 'role': 'system', 'category': 'SYSTEM', 'tokens': 12543, 'chars': 53445}, {'id': 'msg_b0a9a489', 'role': 'system', 'category': 'CONTEXT', 'tokens': 12442, 'chars': 47071}, {'id': 'msg_bbf9e8b5', 'role': 'system', 'category': 'CONTEXT', 'tokens': 7869, 'chars': 31736}, {'id': 'msg_0a0c02ec', 'role': 'tool', 'category': 'SYSTEM_OUTPUT', 'tokens': 6155, 'chars': 24000}] previews=False
INFO:     engine.llm_step.tools_prepared request=ff2b8ca6-521e-46dc-8603-ba15941635a9 session=session_20260509_210523_4d051ef4 agent=default schemas=36 tool_choice=auto
INFO:     engine.llm_attempt.start request=ff2b8ca6-521e-46dc-8603-ba15941635a9 session=session_20260509_210523_4d051ef4 model=gpt-5.5 provider=openai streaming=True messages=446 tools=36
INFO:     openai.oauth.resolve source=store_oauth has_access=True has_refresh=True has_expires=True has_account=True
INFO:     openai.request.route route=oauth_codex model=gpt-5.5 stream=True service_tier=priority has_access=True has_refresh=True has_expires=True has_account=True
INFO:     openai.oauth.codex.request_start diag_id=oaoc_52eb2312a7 requested_stream=True transport_stream=True model=gpt-5.5 model_fallback=False input_items=464 instructions_present=True store=False service_tier=priority has_account_id=True has_reasoning=True
ERROR:    OpenAI OAuth Codex stream_event_error failed (diag_id=oaoc_52eb2312a7, model=gpt-5.5, model_fallback=False, input_is_list=True, input_items=464, instructions_present=True, store=False, error_type=RuntimeError) detail={"type": "service_unavailable_error", "code": "server_is_overloaded", "message": "Our servers are currently overloaded. Please try again later.", "param": null}
NoneType: None
ERROR:    [Request:ff2b8ca6-521e-46dc-8603-ba15941635a9] llm.handler.failure diag_id=oaoc_52eb2312a7 category=network handler=OpenAIAdapter provider=openai model=gpt-5.5 detail=OpenAI OAuth Codex stream_event_error failed (diag_id=oaoc_52eb2312a7, model=gpt-5.5, model_fallback=False, input_is_list=True, input_items=464, instructions_present=True, store=False, error_type=RuntimeError) detail={"type": "service_unavailable_error", "code": "server_is_overloaded", "message": "Our servers are currently overloaded. Please try again later.", "param": null}
RuntimeError: {"type": "service_unavailable_error", "code": "server_is_overloaded", "message": "Our servers are currently overloaded. Please try again later.", "param": null}

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/api_client.py", line 882, in get_response
    response_text = await self.client_handler.get_response(
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 954, in get_response
    accumulated = await self.create_completion(
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 832, in create_completion
    return await self._create_oauth_codex_completion(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 1637, in _create_oauth_codex_completion
    return await self._stream_codex_oauth(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 1918, in _stream_codex_oauth
    self._raise_codex_transport_error(
  File "/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/adapters/openai.py", line 2394, in _raise_codex_transport_error
    raise LLMProviderError(llm_error) from error
penguin.llm.contracts.LLMProviderError: OpenAI OAuth Codex stream_event_error failed (diag_id=oaoc_52eb2312a7, model=gpt-5.5, model_fallback=False, input_is_list=True, input_items=464, instructions_present=True, store=False, error_type=RuntimeError) detail={"type": "service_unavailable_error", "code": "server_is_overloaded", "message": "Our servers are currently overloaded. Please try again later.", "param": null}
INFO:     openai.oauth.resolve source=store_oauth has_access=True has_refresh=True has_expires=True has_account=True
INFO:     openai.request.route route=oauth_codex model=gpt-5.5 stream=False service_tier=priority has_access=True has_refresh=True has_expires=True has_account=True
INFO:     openai.oauth.codex.request_start diag_id=oaoc_0ae5a8cd48 requested_stream=False transport_stream=True model=gpt-5.5 model_fallback=False input_items=464 instructions_present=True store=False service_tier=priority has_account_id=True has_reasoning=True