import os
import base64
import mimetypes
import anthropic
from dotenv import load_dotenv

# Load environment variables (for ANTHROPIC_API_KEY)
load_dotenv()

def test_anthropic_vision(image_path):
    """Test Anthropic vision capabilities directly with their API."""
    print(f"Testing with image: {image_path}")
    
    # Verify the image exists
    if not os.path.exists(image_path):
        print(f"Error: Image file not found: {image_path}")
        return
    
    # Get file size
    file_size = os.path.getsize(image_path)
    print(f"Image file size: {file_size} bytes")
    
    try:
        # Detect the correct mime type
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type or not mime_type.startswith('image/'):
            print("Could not detect mime type, defaulting to image/png")
            mime_type = "image/png"  # Default to PNG instead of JPEG
        
        print(f"Using mime type: {mime_type}")
        
        # Read and encode image
        with open(image_path, "rb") as img_file:
            encoded_image = base64.b64encode(img_file.read()).decode("utf-8")
        
        # Initialize Anthropic client
        client = anthropic.Anthropic()
        
        # Print API key status (masked)
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            print(f"API key found: {api_key[:4]}...{api_key[-4:]}")
        else:
            print("Warning: No ANTHROPIC_API_KEY found in environment")
        
        # Make the API call following Anthropic's documentation
        print("Sending request to Anthropic...")
        message = client.messages.create(
            model="claude-3-7-sonnet-20250219",  # Use your preferred Claude model
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,  # Use detected mime type
                                "data": encoded_image
                            }
                        },
                        {
                            "type": "text",
                            "text": "Describe this image in detail."
                        }
                    ]
                }
            ]
        )
        
        # Print the response
        print("\nAnthropic Response:")
        print(message.content[0].text)
        
        return True
    
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return False

if __name__ == "__main__":
    # You can pass the image path as a command line argument or hardcode it here
    import sys
    image_path = sys.argv[1] if len(sys.argv) > 1 else "/Users/maximusputnam/Downloads/image.png"
    test_anthropic_vision(image_path) 