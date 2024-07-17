# LeetCode 4: Median of Two Sorted Arrays (Hard)

def find_median_sorted_arrays(nums1, nums2):
    """
    Given two sorted arrays nums1 and nums2 of size m and n respectively, return the median of the two sorted arrays.
    The overall run time complexity should be O(log(m+n)).
    
    :param nums1: First sorted array
    :param nums2: Second sorted array
    :return: Median of the two sorted arrays
    """
    # Ensure nums1 is the smaller array for simplicity
    if len(nums1) > len(nums2):
        nums1, nums2 = nums2, nums1
    
    m, n = len(nums1), len(nums2)
    low, high = 0, m
    
    while low <= high:
        partition_x = (low + high) // 2
        partition_y = (m + n + 1) // 2 - partition_x
        
        max_left_x = float('-inf') if partition_x == 0 else nums1[partition_x - 1]
        min_right_x = float('inf') if partition_x == m else nums1[partition_x]
        
        max_left_y = float('-inf') if partition_y == 0 else nums2[partition_y - 1]
        min_right_y = float('inf') if partition_y == n else nums2[partition_y]
        
        if max_left_x <= min_right_y and max_left_y <= min_right_x:
            # We have found the correct partition
            if (m + n) % 2 == 0:
                return (max(max_left_x, max_left_y) + min(min_right_x, min_right_y)) / 2
            else:
                return max(max_left_x, max_left_y)
        elif max_left_x > min_right_y:
            # We need to move partition_x to the left
            high = partition_x - 1
        else:
            # We need to move partition_x to the right
            low = partition_x + 1
    
    raise ValueError("Input arrays are not sorted")

# Example usage
nums1 = [1, 3]
nums2 = [2]
print(f"Median of {nums1} and {nums2}: {find_median_sorted_arrays(nums1, nums2)}")

nums3 = [1, 2]
nums4 = [3, 4]
print(f"Median of {nums3} and {nums4}: {find_median_sorted_arrays(nums3, nums4)}")

"""
How it works:
1. We use a binary search approach on the smaller array (nums1) to find the correct partition point.
2. The partition divides both arrays into left and right halves.
3. We adjust the partition until we find a point where:
   - All elements in the left half are smaller than all elements in the right half
   - The number of elements in the left half is (m+n+1)//2
4. Once we find this partition, we can easily calculate the median.

Time complexity: O(log(min(m,n))) where m and n are the lengths of the input arrays.
Space complexity: O(1) as we only use a constant amount of extra space.

Real-world applications:
1. Statistical analysis: Finding the median of large datasets that are already sorted but stored separately.
2. Data integration: Combining and analyzing sorted data from multiple sources in big data environments.
3. Signal processing: Merging and finding central tendencies in sorted signal data from different sensors.
4. Financial analysis: Calculating median values from sorted financial data coming from different markets or time periods.
5. Bioinformatics: Analyzing sorted genetic data from different experiments or species to find median characteristics.
6. Performance benchmarking: Merging sorted performance metrics from different systems and finding the overall median.

This algorithm is particularly useful when dealing with very large datasets that are already sorted, as it allows 
finding the median without merging the entire datasets, which would be much more time and memory intensive.
"""