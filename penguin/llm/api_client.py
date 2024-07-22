"""
This module provides a client for interacting with the Anthropic Claude API.

The ClaudeAPIClient class is the main interface for making API requests and processing responses.
It handles tasks such as creating messages, encoding images, and counting tokens.

Example usage:
    model_config = ModelConfig()
    api_client = ClaudeAPIClient("your-api-key-here", model_config)
    response = api_client.create_message(
        model=model_config.model,
        max_tokens=model_config.max_tokens,
        system="You are a helpful AI assistant.",
        messages=[{"role": "user", "content": "Hello, how are you?"}],
        tools=[],
        tool_choice={"type": "auto"}
    )
    assistant_response, tool_uses = api_client.process_response(response)
    print(assistant_response)
    print(tool_uses)
"""

from anthropic import Anthropic
# Import the Anthropic library to interact with the Claude API

from .model_config import ModelConfig
# Import the ModelConfig class from the local model_config module

from PIL import Image
# Import the Image class from the Python Imaging Library (PIL) to handle image processing

import io
# Import the io module to work with in-memory file-like objects

import base64
# Import the base64 module to encode and decode binary data in base64 format

class ClaudeAPIClient:
    def __init__(self, api_key: str, model_config: ModelConfig):
        # The constructor takes an API key and a ModelConfig instance
        self.client = Anthropic(api_key=api_key)
        # Create an Anthropic client using the provided API key
        self.model_config = model_config
        # Store the ModelConfig instance for later use

    def create_message(self, model, max_tokens, system, messages, tools, tool_choice):
        try:
            # Call the Anthropic API to create a new message
            response = self.client.messages.create(
                model=model,  # The model to use for the request
                max_tokens=max_tokens,  # The maximum number of tokens to generate
                system=system,  # The system prompt or instructions
                messages=messages,  # The conversation history
                tools=tools,  # The list of available tools
                tool_choice=tool_choice  # The tool to use for the request
            )
            return response  # Return the API response
        except Exception as e:
            # If an exception occurs, raise a new exception with a descriptive error message
            raise Exception(f"Error calling Claude API: {str(e)}")

    def process_response(self, response):
        assistant_response = ""  # Initialize an empty string to store the assistant's response
        tool_uses = []  # Initialize an empty list to store tool uses

        # Iterate over the content blocks in the API response
        for content_block in response.content:
            if content_block.type == "text":
                # If the content block is text, append it to the assistant_response string
                assistant_response += content_block.text
            elif content_block.type == "tool_use":
                # If the content block is a tool use, add it to the tool_uses list
                tool_uses.append({
                    "name": content_block.name,  # The name of the tool
                    "input": content_block.input,  # The input provided to the tool
                    "id": content_block.id  # The unique identifier of the tool use
                })

        # Return the assistant's response and the list of tool uses
        return assistant_response, tool_uses

    def encode_image_to_base64(self, image_path):
        try:
            with Image.open(image_path) as img:
                # Open the image file at the specified path
                max_size = (1024, 1024)  # Set a maximum size for the image
                img.thumbnail(max_size, Image.DEFAULT_STRATEGY)  # Resize the image if necessary
                if img.mode != 'RGB':
                    # Convert the image to RGB mode if it's not already in that mode
                    img = img.convert('RGB')
                img_byte_arr = io.BytesIO()  # Create an in-memory file-like object
                img.save(img_byte_arr, format='JPEG')  # Save the image to the in-memory object as JPEG
                # Encode the image data as a base64 string and return it
                return base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
        except Exception as e:
            # If an exception occurs, return an error message
            return f"Error encoding image: {str(e)}"

    def count_tokens(self, text):
        try:
            # Call the Anthropic API to count the number of tokens in the given text
            token_count = self.client.count_tokens(text)
            return token_count  # Return the token count
        except Exception as e:
            print(f"Error counting tokens: {str(e)}")  # Print an error message if an exception occurs
            return 0  # Return 0 as the token count in case of an error

# Example usage:
# model_config = ModelConfig()
# api_client = ClaudeAPIClient("your-api-key-here", model_config)
# response = api_client.create_message(
#     model=model_config.model,
#     max_tokens=model_config.max_tokens,
#     system="You are a helpful AI assistant.",
#     messages=[{"role": "user", "content": "Hello, how are you?"}],
#     tools=[],
#     tool_choice={"type": "auto"}
# )
# assistant_response, tool_uses = api_client.process_response(response)
# print(assistant_response)
# print(tool_uses)