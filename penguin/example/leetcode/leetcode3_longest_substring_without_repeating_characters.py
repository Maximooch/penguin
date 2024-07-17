# LeetCode 3: Longest Substring Without Repeating Characters (Medium)

def length_of_longest_substring(s):
    """
    Given a string s, find the length of the longest substring without repeating characters.
    
    :param s: Input string
    :return: Length of the longest substring without repeating characters
    """
    # Dictionary to store the last seen position of each character
    char_index = {}
    
    # Two pointers: start of the current substring and iterator
    start = 0
    max_length = 0
    
    # Iterate through the string
    for end, char in enumerate(s):
        # If the character is already in the current substring, 
        # move the start pointer to the right of the last occurrence
        if char in char_index and char_index[char] >= start:
            start = char_index[char] + 1
        else:
            # Update max_length if the current substring is longer
            max_length = max(max_length, end - start + 1)
        
        # Update the last seen position of the character
        char_index[char] = end
    
    return max_length

# Example usage
s1 = "abcabcbb"
s2 = "bbbbb"
s3 = "pwwkew"

print(f"Length of longest substring without repeating characters in '{s1}': {length_of_longest_substring(s1)}")
print(f"Length of longest substring without repeating characters in '{s2}': {length_of_longest_substring(s2)}")
print(f"Length of longest substring without repeating characters in '{s3}': {length_of_longest_substring(s3)}")

"""
How it works:
1. We use a sliding window approach with two pointers: 'start' and 'end'.
2. We maintain a dictionary 'char_index' to keep track of the last seen position of each character.
3. As we iterate through the string:
   - If we encounter a repeating character, we move the 'start' pointer to the right of its last occurrence.
   - We update the max_length if the current substring is longer than the previous max.
   - We always update the last seen position of the current character.
4. The final max_length gives us the length of the longest substring without repeating characters.

Time complexity: O(n) where n is the length of the string.
Space complexity: O(min(m, n)) where m is the size of the character set.

Real-world applications:
1. Data compression: Identifying repeated patterns in data for efficient compression algorithms.
2. Network packet analysis: Detecting unique sequences in network traffic for security or optimization purposes.
3. Genetic sequence analysis: Finding non-repeating subsequences in DNA or protein sequences.
4. Text processing: Analyzing linguistic patterns or identifying unique phrases in natural language processing.
5. Cryptography: Generating or analyzing keys based on non-repeating character sequences.
"""