
from anthropic import Anthropic # type: ignore
# Import the Anthropic library to interact with the Claude API

from litellm import completion

# import openai

from .model_config import ModelConfig
# Import the ModelConfig class from the local model_config module

from PIL import Image # type: ignore
# Import the Image class from the Python Imaging Library (PIL) to handle image processing

import io
# Import the io module to work with in-memory file-like objects

import base64
# Import the base64 module to encode and decode binary data in base64 format


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

# class BaseAPIClient:
#     def create_message(self, model, max_tokens, system, messages, tools, tool_choice):
#         raise NotImplementedError

#     def process_response(self, response):
#         raise NotImplementedError

#     def count_tokens(self, text):
#         raise NotImplementedError    

# class OpenAIClient(BaseAPIClient):
#     def __init__(self, api_key: str):
#         openai.api_key = api_key

#     def create_message(self, model, max_tokens, system, messages, tools, tool_choice):
#         try:
#             response = openai.Completion.create(
#                 model=model,
#                 max_tokens=max_tokens,
#                 prompt=system + "\n" + "\n".join([msg["content"] for msg in messages])
#             )
#             return response
#         except Exception as e:
#             raise Exception(f"Error calling OpenAI API: {str(e)}")

#     def process_response(self, response):
#         assistant_response = response.choices[0].text.strip()
#         tool_uses = []  # OpenAI might not have tool uses in the same way
#         return assistant_response, tool_uses

#     def count_tokens(self, text):
#         try:
#             token_count = len(openai.Completion.create(model="text-davinci-003", prompt=text, max_tokens=1).choices[0].logprobs.tokens)
#             return token_count
#         except Exception as e:
#             print(f"Error counting tokens: {str(e)}")
#             return 0


