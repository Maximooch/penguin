#!/usr/bin/env python3
"""Debug test for reasoning toggle functionality."""

import re

def test_regex():
    content = '''<details>
<summary>🧠 Click to show / hide internal reasoning</summary>

Let me think about this step by step.

First, I need to understand the problem.

</details>

Here is my response based on the reasoning above.'''
    
    print("Testing regex pattern...")
    print("Original content:")
    print(repr(content))
    print()
    
    # Test the regex pattern
    details_pattern = r'<details([^>]*)>(.*?)</details>'
    matches = re.findall(details_pattern, content, flags=re.DOTALL)
    print(f"Regex matches found: {len(matches)}")
    for i, match in enumerate(matches):
        print(f"Match {i+1}:")
        print(f"  Attributes: {repr(match[0])}")
        print(f"  Body (first 100 chars): {repr(match[1][:100])}")
        print(f"  Contains brain emoji: {'🧠' in match[1]}")
    print()
    
    # Test the toggle function
    def toggle_details(match):
        attrs = match.group(1).strip()
        body = match.group(2)
        
        print(f"Processing match - attrs: {repr(attrs)}, brain in body: {'🧠' in body}")
        
        # Check if it's a reasoning block by looking for the brain emoji in the body
        if '🧠' in body:
            # Toggle by adding/removing 'open' attribute
            if 'open' in attrs:
                # Currently open, close it
                new_attrs = attrs.replace('open', '').replace('  ', ' ').strip()
                new_attrs = ' ' + new_attrs if new_attrs else ''
                result = f'<details{new_attrs}>{body}</details>'
                print(f"  Closing - result: {repr(result[:50])}...")
                return result
            else:
                # Currently closed, open it
                new_attrs = attrs + ' open' if attrs else ' open'
                result = f'<details{new_attrs}>{body}</details>'
                print(f"  Opening - result: {repr(result[:50])}...")
                return result
        return match.group(0)  # Return unchanged
    
    # Apply the regex substitution
    new_content = re.sub(details_pattern, toggle_details, content, flags=re.DOTALL)
    
    print("Result:")
    print(f"Content changed: {new_content != content}")
    print(f"Contains 'open': {'open' in new_content}")
    print("New content:")
    print(repr(new_content[:200]))

if __name__ == "__main__":
    test_regex()