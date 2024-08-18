import os
import re
from collections import defaultdict

def count_lines(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            non_empty_lines = [line for line in lines if line.strip()]
            code_lines = []
            in_multiline_comment = False
            for line in non_empty_lines:
                stripped_line = line.strip()
                if stripped_line.startswith('"""') or stripped_line.startswith("'''"):
                    in_multiline_comment = not in_multiline_comment
                elif not in_multiline_comment and not stripped_line.startswith('#'):
                    code_lines.append(line)
            return len(code_lines)
    except UnicodeDecodeError:
        print(f"Warning: Unable to read file {file_path} due to encoding issues. Skipping.")
        return 0

def should_ignore(path, ignore_patterns):
    for pattern in ignore_patterns:
        if re.search(pattern, path):
            return True
    return False

def count_loc_in_directory(directory):
    total_loc = 0
    loc_by_ext = defaultdict(int)
    ignore_patterns = [
        r'/example/',
        r'/logs/',
        r'/penguin_venv/',
        r'/__pycache__/',
        r'/\.[^/]+/',  # Hidden directories
        r'(^|/)\.git/',
        r'\.(pyc|pyo|pyd|egg-info)$',
        r'(^|/)(\.gitignore|readme\.md|license\.txt)$'
    ]
    file_extensions = ('.py', '.js', '.ts', '.html', '.css', '.jsx', '.tsx', '.vue', '.scss', '.less', '.sql', '.sh', '.bat', '.ps1')
    
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not should_ignore(os.path.join(root, d), ignore_patterns)]
        for file in files:
            if file.endswith(file_extensions) and not should_ignore(os.path.join(root, file), ignore_patterns):
                file_path = os.path.join(root, file)
                loc = count_lines(file_path)
                total_loc += loc
                ext = os.path.splitext(file)[1]
                loc_by_ext[ext] += loc
    
    print(f"Debug - total_loc: {total_loc}")
    print(f"Debug - loc_by_ext: {dict(loc_by_ext)}")
    result = (total_loc, dict(loc_by_ext))
    print(f"Debug - result type: {type(result)}")
    print(f"Debug - result value: {result}")
    return result

def main():
    print(f"Current working directory: {os.getcwd()}")
    penguin_folder = '.'
    script_path = os.path.abspath(__file__)
    print(f"Script path: {script_path}")
    print(f"Script exists: {os.path.exists(script_path)}")

    result = count_loc_in_directory(penguin_folder)
    print(f"Debug - Main result type: {type(result)}")
    print(f"Debug - Main result value: {result}")
    
    if isinstance(result, tuple) and len(result) == 2:
        total_loc, loc_by_ext = result
        print(f"\nTotal lines of code in Penguin-AI: {total_loc}")
        print("\nBreakdown by file extension:")
        for ext, count in sorted(loc_by_ext.items(), key=lambda x: x[1], reverse=True):
            print(f"{ext}: {count}")
    else:
        print("Error: Unexpected result from count_loc_in_directory function")

if __name__ == "__main__":
    main()