"""Serialization utilities for converting between objects and dictionaries.

This module provides helper functions for converting dataclasses to/from dictionaries
for JSON serialization and database storage.
"""

from dataclasses import asdict, fields, is_dataclass
from typing import Any, Dict, Type, TypeVar, Union
import json

T = TypeVar('T')


def to_dict(obj: Any) -> Dict[str, Any]:
    """Convert a dataclass instance to a dictionary.
    
    Args:
        obj: The dataclass instance to convert
        
    Returns:
        Dictionary representation of the object
    """
    if is_dataclass(obj):
        return asdict(obj)
    elif hasattr(obj, 'to_dict'):
        return obj.to_dict()
    else:
        return obj


def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
    """Create a dataclass instance from a dictionary.
    
    Args:
        cls: The dataclass type to create
        data: Dictionary of data to populate the instance
        
    Returns:
        Instance of the specified dataclass type
    """
    if is_dataclass(cls):
        # Get field names and types for the dataclass
        field_names = {f.name for f in fields(cls)}
        # Filter data to only include valid fields
        filtered_data = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered_data)
    else:
        return cls(**data)


def to_json(obj: Any, indent: int = None) -> str:
    """Convert an object to JSON string.
    
    Args:
        obj: Object to serialize
        indent: JSON indentation level
        
    Returns:
        JSON string representation
    """
    return json.dumps(to_dict(obj), indent=indent, default=str)


def from_json(cls: Type[T], json_str: str) -> T:
    """Create an object from JSON string.
    
    Args:
        cls: The class type to create
        json_str: JSON string to deserialize
        
    Returns:
        Instance of the specified type
    """
    data = json.loads(json_str)
    return from_dict(cls, data) 