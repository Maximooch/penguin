import random


def print_random_number() -> int:
    value = random.randint(1, 100)
    print(value)
    return value


if __name__ == "__main__":
    result = print_random_number()
    print(f"RESULT={result}")
