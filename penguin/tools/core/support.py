import base64
import difflib
import io
import os
import traceback
from pathlib import Path

from PIL import Image  # type: ignore


def create_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        return f"Folder created: {os.path.abspath(path)}"
    except Exception as e:
        return f"Error creating folder: {str(e)}"


def create_file(path: str, content: str = "") -> str:
    try:
        print(f"Attempting to create file at: {os.path.abspath(path)}")
        print(f"Current working directory: {os.getcwd()}")

        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        with open(path, "w") as f:
            f.write(content)
        return f"File created successfully at {os.path.abspath(path)}"
    except Exception as e:
        return f"Error creating file: {str(e)}\nStack trace: {traceback.format_exc()}"


def generate_and_apply_diff(original_content, new_content, full_path, encoding):
    print(f"Applying diff to {full_path} with encoding {encoding}")
    diff = list(
        difflib.unified_diff(
            original_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{full_path}",
            tofile=f"b/{full_path}",
            n=3,
        )
    )

    if not diff:
        return "No changes detected."

    try:
        with open(full_path, "w", encoding=encoding) as f:
            f.write(new_content)
        return f"Changes applied to {full_path}:\n" + "".join(diff)
    except Exception as e:
        return f"Error applying changes: {str(e)}"


def write_to_file(path, content):
    full_path = path
    encodings = ["utf-8", "latin-1", "ascii", "utf-16"]

    for encoding in encodings:
        try:
            if os.path.exists(full_path):
                with open(full_path, encoding=encoding) as f:
                    original_content = f.read()
                result = generate_and_apply_diff(
                    original_content, content, full_path, encoding
                )
            else:
                with open(full_path, "w", encoding=encoding) as f:
                    f.write(content)
                result = f"New file created and content written to: {full_path}"
            # Return after successful write
            return result
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        except Exception as e:
            print(f"Error with encoding '{encoding}': {str(e)}")
            continue
    return f"Error writing to file: Unable to encode with encodings: {', '.join(encodings)}"


def read_file(path):
    full_path = path
    encodings = ["utf-8", "latin-1", "ascii", "utf-16"]
    for encoding in encodings:
        try:
            with open(full_path, encoding=encoding) as f:
                content = f.read()
            return content
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return f"Error reading file: {str(e)}"
    return (
        f"Error reading file: Unable to decode with encodings: {', '.join(encodings)}"
    )


def list_files(path="."):
    try:
        full_path = os.path.normpath(path)

        if not os.path.exists(full_path):
            return f"Error: Directory does not exist: {path}"

        if not os.path.isdir(full_path):
            return f"Error: Not a directory: {path}"

        files = os.listdir(full_path)
        return "\n".join(
            [
                f"{f} ({'directory' if os.path.isdir(os.path.join(full_path, f)) else 'file'})"
                for f in files
            ]
        )
    except Exception as e:
        return f"Error listing files: {str(e)}"


def find_file(filename: str, search_path: str = ".") -> list[str]:
    full_search_path = Path(search_path)
    matches = list(full_search_path.rglob(filename))
    return [str(path.relative_to(full_search_path)) for path in matches]


def encode_image_to_base64(image_path):
    try:
        with Image.open(image_path) as img:
            max_size = (1024, 1024)
            img.thumbnail(max_size, Image.DEFAULT_STRATEGY)
            if img.mode != "RGB":
                img = img.convert("RGB")
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format="JPEG")
            return base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")
    except Exception as e:
        return f"Error encoding image: {str(e)}"


# Example usage:
# print(create_folder("test_folder"))
# print(create_file("test_file.txt", "Hello, World!"))
# print(write_to_file("test_file.txt", "Updated content"))
# print(read_file("test_file.txt"))
# print(list_files())
# print(encode_image_to_base64("test_image.jpg"))
