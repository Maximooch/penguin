import os
import base64
import anthropic
from dotenv import load_dotenv
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)

# Load environment variables
load_dotenv()

def test_image_upload(image_path):
    """Test direct image upload to Claude"""
    print(f"Testing with image: {image_path}")
    
    if not os.path.exists(image_path):
        print(f"Error: Image file not found: {image_path}")
        return
    
    # Get file size and info
    file_size = os.path.getsize(image_path) / 1024  # KB
    print(f"Image file size: {file_size:.1f} KB")
    
    try:
        # Read and encode image directly
        with open(image_path, "rb") as img_file:
            encoded_image = base64.b64encode(img_file.read()).decode("utf-8")
        
        print(f"Encoded image length: {len(encoded_image)} chars")
        
        # Initialize Anthropic client
        client = anthropic.Anthropic()
        
        # Make the API call with simplest possible structure
        print("Sending request to Anthropic...")
        message = client.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
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
    # Get image path from command line or use default
    import sys
    image_path = sys.argv[1] if len(sys.argv) > 1 else "/Users/maximusputnam/Downloads/image.png"
    test_image_upload(image_path) 