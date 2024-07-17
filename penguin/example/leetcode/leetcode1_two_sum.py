# LeetCode 1: Two Sum (Easy)

def two_sum(nums, target):
    """
    Given an array of integers nums and an integer target, return indices of the two numbers such that they add up to target.
    
    :param nums: List of integers
    :param target: Integer target sum
    :return: List of two indices
    """
    # Create a dictionary to store complement values and their indices
    complement_dict = {}
    
    # Iterate through the list with enumeration to get both index and value
    for i, num in enumerate(nums):
        complement = target - num
        
        # If the complement exists in our dictionary, we've found our pair
        if complement in complement_dict:
            return [complement_dict[complement], i]
        
        # Otherwise, add this number and its index to the dictionary
        complement_dict[num] = i
    
    # If no solution is found, return an empty list or raise an exception
    return []

# Example usage
nums = [2, 7, 11, 15]
target = 9
result = two_sum(nums, target)
print(f"Indices of two numbers that add up to {target}: {result}")

"""
How it works:
1. We use a dictionary (hash map) to store each number as we iterate through the list.
2. For each number, we calculate its complement (target - num) and check if it's already in the dictionary.
3. If the complement is found, we've found our pair and return their indices.
4. If not, we add the current number and its index to the dictionary and continue.

Time complexity: O(n) where n is the length of the input list.
Space complexity: O(n) in the worst case, where we might need to store almost all elements in the dictionary.

Real-world applications:
1. Financial software: Finding pairs of transactions that sum to a specific amount.
2. E-commerce: Identifying combinations of products that fit a certain budget.
3. Data analysis: Discovering relationships between data points that satisfy a particular condition.
4. Cryptography: In some cryptographic algorithms, finding pairs of numbers with specific properties.
"""