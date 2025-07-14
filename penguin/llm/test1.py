from penguin.core import PenguinCore
import asyncio

# # Automatic reasoning detection and configuration
# core = asyncio.run(PenguinCore.create(
#     model="deepseek/deepseek-r1",
#     provider="openrouter"
# ))

# # See the model think step by step
# response = asyncio.run(core.process_message(
#     "Solve this complex problem step by step... Which is larger? 9.11 or 9.9?",
#     streaming=True
# ))

# print(response)

# Automatic reasoning detection
core = await PenguinCore.create(model="deepseek/deepseek-r1")

# See model's thought process
async def reasoning_callback(chunk: str, message_type: str):
    if message_type == "reasoning":
        print(f"🤔 THINKING: {chunk}")
    else:
        print(f"💭 ANSWER: {chunk}")

response = await core.process(
    "Complex problem here...",
    streaming=True,
    stream_callback=reasoning_callback
)
