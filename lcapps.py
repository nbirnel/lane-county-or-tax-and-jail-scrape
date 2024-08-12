import re

def strip(text: str)->str:
    """
    Accept text.
    Return with extra whitespace removed.
    """
    return re.sub(r'\s+', ' ', text.strip())

