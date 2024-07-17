# LeetCode 23: Merge k Sorted Lists (Hard)

import heapq

# Definition for singly-linked list.
class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next

class Solution:
    def mergeKLists(self, lists):
        """
        Merge k sorted linked lists and return it as one sorted list.
        
        :param lists: List of heads of sorted linked lists
        :return: Head of the merged sorted linked list
        """
        # Custom class to make ListNode comparable
        class ComparableListNode:
            def __init__(self, node):
                self.node = node
            def __lt__(self, other):
                return self.node.val < other.node.val

        # Initialize the min-heap
        heap = []
        
        # Add the head of each list to the heap
        for i, l in enumerate(lists):
            if l:
                heapq.heappush(heap, ComparableListNode(l))
        
        dummy = ListNode(0)
        current = dummy
        
        # Process nodes from the heap
        while heap:
            smallest = heapq.heappop(heap).node
            current.next = smallest
            current = current.next
            
            if smallest.next:
                heapq.heappush(heap, ComparableListNode(smallest.next))
        
        return dummy.next

# Helper function to create a linked list from a Python list
def create_linked_list(arr):
    dummy = ListNode(0)
    current = dummy
    for val in arr:
        current.next = ListNode(val)
        current = current.next
    return dummy.next

# Helper function to convert a linked list to a Python list
def linked_list_to_list(head):
    result = []
    current = head
    while current:
        result.append(current.val)
        current = current.next
    return result

# Example usage
sol = Solution()

# Create sample sorted linked lists
list1 = create_linked_list([1,4,5])
list2 = create_linked_list([1,3,4])
list3 = create_linked_list([2,6])

# Merge the lists
merged = sol.mergeKLists([list1, list2, list3])

# Convert the result back to a Python list for easy printing
result = linked_list_to_list(merged)
print("Merged sorted list:", result)

"""
How it works:
1. We use a min-heap to efficiently find the smallest element among the heads of all lists.
2. We create a custom ComparableListNode class to make ListNode objects comparable (required for the heap).
3. We initialize the heap with the head nodes of all non-empty input lists.
4. We create a dummy node to simplify the merging process.
5. We repeatedly pop the smallest node from the heap, add it to our result list, and push its next node (if any) onto the heap.
6. This process continues until the heap is empty, at which point we've processed all nodes.

Time complexity: O(N log k), where N is the total number of nodes across all lists, and k is the number of lists.
                 We perform N heap operations, each taking log k time.
Space complexity: O(k) for the heap, which stores at most k nodes at any time.

Real-world applications:
1. Database Management: Merging sorted results from multiple database shards or partitions.
2. Distributed Computing: Combining sorted partial results from multiple machines in a distributed system.
3. External Sorting: When sorting large files that don't fit in memory, this algorithm can be used to merge sorted chunks.
4. Log Processing: Merging timestamped log files from multiple servers or services.
5. Financial Data Analysis: Combining sorted financial transactions or time series data from multiple sources.
6. Search Engine Indexing: Merging sorted document lists in inverted indices.
7. Sensor Data Fusion: Combining sorted data streams from multiple sensors in real-time systems.
8. Scheduling Algorithms: Merging multiple priority queues in advanced scheduling systems.
9. Network Packet Analysis: Combining sorted packet capture data from multiple network interfaces.
10. Genome Sequencing: Merging sorted DNA fragment lists in bioinformatics applications.

This algorithm is particularly useful in scenarios where you have multiple sorted sources of data that need to be 
combined efficiently. The use of a heap allows for a time-efficient solution that scales well with the number of 
input lists, making it suitable for handling large-scale data merging tasks in various domains.
"""