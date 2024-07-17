# LeetCode 5: Longest Palindromic Substring (Medium)

def longest_palindrome(s):
    """
    Given a string s, return the longest palindromic substring in s.
    
    :param s: Input string
    :return: Longest palindromic substring
    """
    if not s:
        return ""

    start = 0
    max_length = 1

    def expand_around_center(left, right):
        while left >= 0 and right < len(s) and s[left] == s[right]:
            left -= 1
            right += 1
        return right - left - 1

    for i in range(len(s)):
        # Check for odd-length palindromes
        len1 = expand_around_center(i, i)
        # Check for even-length palindromes
        len2 = expand_around_center(i, i + 1)
        
        length = max(len1, len2)
        if length > max_length:
            max_length = length
            start = i - (length - 1) // 2

    return s[start:start + max_length]

# Example usage
s1 = "babad"
s2 = "cbbd"
s3 = "a"
s4 = "ac"

print(f"Longest palindromic substring in '{s1}': {longest_palindrome(s1)}")
print(f"Longest palindromic substring in '{s2}': {longest_palindrome(s2)}")
print(f"Longest palindromic substring in '{s3}': {longest_palindrome(s3)}")
print(f"Longest palindromic substring in '{s4}': {longest_palindrome(s4)}")

"""
How it works:
1. We use the "expand around center" technique to find palindromes.
2. For each character in the string, we consider it as a potential center of a palindrome.
3. We expand outwards from this center, checking both odd-length and even-length palindromes.
4. We keep track of the longest palindrome found so far.
5. Finally, we return the substring corresponding to the longest palindrome.

Time complexity: O(n^2) where n is the length of the string.
Space complexity: O(1) as we only use a constant amount of extra space.

Real-world applications:
1. Bioinformatics: Finding palindromic sequences in DNA or RNA, which can be important for gene regulation and structure.
2. Natural Language Processing: Identifying palindromes in text for linguistic analysis or text processing tasks.
3. Data Compression: Palindromic substrings can be efficiently encoded, potentially improving compression algorithms.
4. Cryptography: Some encryption techniques use palindromes as part of their algorithms or for generating keys.
5. Software Testing: Generating palindromic test cases for string manipulation functions.
6. Database Optimization: Finding and indexing palindromic substrings for efficient searching in text databases.
7. Computer Network Protocols: Some network protocols use palindromic bit sequences for synchronization or error detection.

This algorithm is particularly useful when dealing with string processing tasks that require identifying symmetry or 
repetitive patterns within the data. The efficient "expand around center" approach makes it suitable for processing 
large amounts of text data in various applications.
"""