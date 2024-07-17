# LeetCode 102: Binary Tree Level Order Traversal (Medium)

from collections import deque

# Definition for a binary tree node.
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right

def level_order(root):
    """
    Given the root of a binary tree, return the level order traversal of its nodes' values.
    (i.e., from left to right, level by level)
    
    :param root: Root node of the binary tree
    :return: List of lists representing the level order traversal
    """
    if not root:
        return []
    
    result = []
    queue = deque([root])
    
    while queue:
        level_size = len(queue)
        current_level = []
        
        for _ in range(level_size):
            node = queue.popleft()
            current_level.append(node.val)
            
            if node.left:
                queue.append(node.left)
            if node.right:
                queue.append(node.right)
        
        result.append(current_level)
    
    return result

# Example usage
# Constructing a sample binary tree
#       3
#      / \
#     9  20
#       /  \
#      15   7

root = TreeNode(3)
root.left = TreeNode(9)
root.right = TreeNode(20)
root.right.left = TreeNode(15)
root.right.right = TreeNode(7)

print("Level Order Traversal:", level_order(root))

"""
How it works:
1. We use a queue (implemented with deque for efficiency) to perform a breadth-first search (BFS) on the tree.
2. We process the tree level by level, keeping track of the number of nodes at each level.
3. For each level, we remove all nodes currently in the queue (which represent the current level),
   add their values to the current level list, and add their children to the queue for the next level.
4. We repeat this process until the queue is empty, meaning we've processed all levels of the tree.

Time complexity: O(n), where n is the number of nodes in the tree. We visit each node exactly once.
Space complexity: O(m), where m is the maximum number of nodes at any level in the tree. 
                  In the worst case of a complete binary tree, this can be up to n/2.

Real-world applications:
1. File System Traversal: Representing directory structures and traversing them level by level.
2. Network Topology Analysis: Analyzing computer networks where each node represents a device or router.
3. Organizational Hierarchy: Visualizing and processing company structures or family trees.
4. Game AI: Representing game states in strategy games or puzzle solvers.
5. Compiler Design: Representing and traversing abstract syntax trees in compilers.
6. Circuit Design: Analyzing digital circuits where components are organized in a tree-like structure.
7. HTML/XML Parsing: Traversing DOM (Document Object Model) structures in web development.
8. Biological Classification: Representing and traversing taxonomic hierarchies in biology.
9. Decision Trees: Implementing and traversing decision trees in machine learning algorithms.
10. Database Indexing: Implementing and traversing B-trees or similar structures used in database indexes.

This algorithm is particularly useful when you need to process data that has a hierarchical structure and you want to 
handle it level by level. The breadth-first approach ensures that all nodes at a given depth are processed before 
moving to the next level, which can be crucial in many real-world scenarios where level-based priority is important.
"""